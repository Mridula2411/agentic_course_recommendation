"""Evaluates the pipeline on the conversations in eval_cases.py.

Routes, hard constraints and must-include courses are checked in code; SQL,
relevance and advice quality are graded by one or two LLM judges.

    python evaluate.py
    python evaluate.py --judges openai gemini
    python evaluate.py --no-verifier          # advisor answers without the fact-check
    python evaluate.py --no-judge
    python evaluate.py --cases greeting ml-refine-advise
    python evaluate.py --repeat 3
"""
from datetime import datetime
from statistics import mean
import argparse
import json
import os
import time
import traceback

from course_db import is_written_exam
from eval_cases import CASES
from orchestrator import Orchestrator, Session


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(SCRIPT_DIR, "eval_results")


def course_violations(course, checks):
    """Hard-constraint checks for one returned course."""
    problems = []
    periods = course.get("periods") or ""
    text = " ".join(course.get(f) or "" for f in ("course_name", "description", "learning_outcomes")).lower()
    exams = course.get("examination") or ""
    if "periods_include" in checks and checks["periods_include"] not in periods:
        problems.append(f"not in {checks['periods_include']} ({periods or 'no period'})")
    if "periods_any" in checks and not any(p in periods for p in checks["periods_any"]):
        problems.append(f"not in {'/'.join(checks['periods_any'])} ({periods or 'no period'})")
    if "grading" in checks and course.get("grading_scale") != checks["grading"]:
        problems.append(f"graded {course.get('grading_scale')}")
    if checks.get("no_written_exam") and any(is_written_exam(m) for m in json.loads(course.get("examination_json") or "[]")):
        problems.append("has a written exam")
    if "exam_includes" in checks and not any(term.lower() in exams.lower() for term in checks["exam_includes"]):
        problems.append(f"no {'/'.join(checks['exam_includes'])} module")
    if "max_credits" in checks and (course.get("credits") or 0) > checks["max_credits"]:
        problems.append(f"{course.get('credits')} credits")
    if "min_credits" in checks and (course.get("credits") or 0) < checks["min_credits"]:
        problems.append(f"{course.get('credits')} credits")
    if "language_contains" in checks and checks["language_contains"].lower() not in (course.get("language") or "").lower():
        problems.append(f"taught in {course.get('language')}")
    if "topic_any" in checks and not any(t.lower() in text for t in checks["topic_any"]):
        problems.append("off topic")
    if "programmes_contains" in checks and checks["programmes_contains"] not in (course.get("programmes") or ""):
        problems.append(f"not in {checks['programmes_contains']}")
    if "min_pass_rate" in checks and (course.get("pass_rate") is None or course["pass_rate"] < checks["min_pass_rate"]):
        problems.append(f"pass rate {course.get('pass_rate')}")
    return problems


def check_results(courses, total, checks):
    violations = {c["course_code"]: p for c in courses if (p := course_violations(c, checks))}
    codes = {c["course_code"] for c in courses}
    missing = [code for code in checks.get("must_include", []) if code not in codes]
    count_problems = []
    if total < checks.get("min_results", 0):
        count_problems.append(f"only {total} results (expected at least {checks['min_results']})")
    return {
        "passed": not violations and not missing and not count_problems,
        "violations": violations,
        "violation_rate": len(violations) / len(courses) if courses else 0.0,
        "missing": missing,
        "required": len(checks.get("must_include", [])),
        "count_problems": count_problems,
    }


def judged(grade):
    """Run a judge call; a judge failure is recorded instead of stopping the evaluation."""
    try:
        return grade()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:200]}"}


def run_turn(orchestrator, judges, session, turn):
    shown_before = session.search
    started = time.monotonic()
    try:
        result = orchestrator.handle(session, turn["message"])
    except Exception as e:
        return {"message": turn["message"], "expected_route": turn["route"], "error": f"{type(e).__name__}: {e}",
                "trace": traceback.format_exc(limit=3)}
    record = {
        "message": turn["message"],
        "expected_route": turn["route"],
        "route": result["route"],
        "route_ok": result["route"] in turn["route"],
        "seconds": round(time.monotonic() - started, 1),
        "reply": result["message"],
    }
    if result["search"]:
        record["sql"] = result["search"]["sql"]
        record["total"] = result["search"]["total"]
        record["result_codes"] = [c["course_code"] for c in result["courses"]]
        record["retrieval_steps"] = len(result["search"]["steps"])
        if turn.get("checks"):
            record["checks"] = check_results(result["courses"], result["search"]["total"], turn["checks"])
        previous_sql = shown_before["sql"] if result["route"] == "refine" and shown_before else None
        record["judges"] = {
            j.name: judged(lambda j=j: j.retrieval(turn["message"], result.get("request"), previous_sql, session.search))
            for j in judges
        }
    if result["route"] == "advise":
        record["highlighted"] = [h["course_code"] for h in result["highlighted"]]
        record["verification"] = result.get("verification")
        record["judges"] = {
            j.name: judged(lambda j=j: j.advice(turn["message"], shown_before["courses"], result["message"], result["highlighted"]))
            for j in judges
        }
    return record


def jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 1.0


def avg(values):
    values = [v for v in values if v is not None]
    return round(mean(values), 2) if values else None


CODE_METRICS = [
    ("routing_accuracy", "Routing accuracy"),
    ("constraint_pass_rate", "Searches where every course meets the constraints"),
    ("courses_violating_constraints", "Share of returned courses violating a constraint"),
    ("must_include_recall", "Key courses found (must-include recall)"),
    ("result_consistency", "Result overlap across repeated runs (Jaccard)"),
    ("advice_revised", "Advice answers revised after the fact-check"),
    ("verifier_errors", "Fact-check failures"),
    ("seconds_per_turn", "Seconds per turn"),
]

# (key, label, step, kind): kind is "score" (1-5), "bool", or "share" (0-1)
JUDGE_METRICS = [
    ("sql_faithfulness", "SQL faithfulness (1-5)", "retrieval", "score"),
    ("precision_at_10", "Relevance of top 10 results", "retrieval", "share"),
    ("summary_honest", "Honest search summaries", "retrieval", "bool"),
    ("groundedness", "Advice grounded in data (1-5)", "advice", "score"),
    ("answers_question", "Advice answers the question (1-5)", "advice", "score"),
    ("completeness", "Advice completeness (1-5)", "advice", "score"),
    ("clarity", "Advice clarity (1-5)", "advice", "score"),
    ("demo_labels_ok", "Synthetic data labelled as demo", "advice", "bool"),
]


def step_of(turn):
    return "retrieval" if "sql" in turn else "advice"


def grade(turn, judge_name):
    """A judge's grade for a turn, or None if it was not graded or the judge failed."""
    g = turn.get("judges", {}).get(judge_name)
    return g if g and "error" not in g else None


def judge_summary(turns, judge_name):
    graded = [t for t in turns if grade(t, judge_name)]
    summary = {key: avg([grade(t, judge_name)[key] for t in graded if step_of(t) == step])
               for key, _, step, _ in JUDGE_METRICS}
    summary["failures"] = sum(1 for t in turns if "error" in t.get("judges", {}).get(judge_name, {}))
    return summary


def agreement(turns, a, b):
    """How closely two judges agree on the same outputs."""
    both = [t for t in turns if grade(t, a) and grade(t, b)]
    result = {}
    for key, _, step, kind in JUDGE_METRICS:
        pairs = [(grade(t, a)[key], grade(t, b)[key]) for t in both if step_of(t) == step]
        pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
        if not pairs:
            result[key] = None
        elif kind == "score":
            result[key] = {"mean_abs_diff": avg([abs(x - y) for x, y in pairs]),
                           "exact": avg([x == y for x, y in pairs])}
        elif kind == "bool":
            result[key] = {"agree": avg([x == y for x, y in pairs])}
        else:  # relevance: compare the per-course verdicts
            verdicts = [(grade(t, a)["relevant"][c], grade(t, b)["relevant"][c])
                        for t in both if step_of(t) == "retrieval"
                        for c in grade(t, a).get("relevant", {}) if c in grade(t, b).get("relevant", {})]
            result[key] = {"agree": avg([x == y for x, y in verdicts]), "mean_abs_diff": avg([abs(x - y) for x, y in pairs])}
    return result


def disagreements(runs, a, b):
    """Steps where two judges clearly disagree: worth checking by hand."""
    found = []
    for run in runs:
        for t in run["turns"]:
            ga, gb = grade(t, a), grade(t, b)
            if not ga or not gb:
                continue
            reasons = []
            for key, label, step, kind in JUDGE_METRICS:
                if step != step_of(t) or ga.get(key) is None or gb.get(key) is None:
                    continue
                if kind == "score" and abs(ga[key] - gb[key]) >= 2:
                    reasons.append(f"{label}: {ga[key]} vs {gb[key]}")
                elif kind == "bool" and ga[key] != gb[key]:
                    reasons.append(f"{label}: {ga[key]} vs {gb[key]}")
                elif kind == "share" and abs(ga[key] - gb[key]) >= 0.3:
                    reasons.append(f"{label}: {ga[key]:.2f} vs {gb[key]:.2f}")
            if reasons:
                found.append({"case": run["case"], "message": t["message"], "reasons": reasons})
    return found


def summarize(runs, judge_names):
    turns = [t for run in runs for t in run["turns"]]
    ok = [t for t in turns if "error" not in t]
    checked = [t for t in ok if "checks" in t]
    summary = {
        "turns": len(turns),
        "errors": len(turns) - len(ok),
        "routing_accuracy": avg([t["route_ok"] for t in ok]),
        "constraint_pass_rate": avg([t["checks"]["passed"] for t in checked]),
        "courses_violating_constraints": avg([t["checks"]["violation_rate"] for t in checked]),
        "seconds_per_turn": avg([t["seconds"] for t in ok]),
    }
    checks = [t["verification"] for t in ok if t.get("verification")]
    summary["advice_revised"] = avg([v.get("revised", False) for v in checks if "error" not in v])
    summary["verifier_errors"] = sum("error" in v for v in checks) if checks else None
    # share of the required (must-include) courses that were returned
    required = sum(t["checks"]["required"] for t in checked)
    missing = sum(len(t["checks"]["missing"]) for t in checked)
    summary["must_include_recall"] = round(1 - missing / required, 2) if required else None

    # overlap of result sets for the same turn across repeated runs
    by_turn = {}
    for run in runs:
        for i, t in enumerate(run["turns"]):
            if "result_codes" in t:
                by_turn.setdefault((run["case"], i), []).append(t["result_codes"])
    pairs = [jaccard(a, b) for sets in by_turn.values() for i, a in enumerate(sets) for b in sets[i + 1:]]
    summary["result_consistency"] = round(mean(pairs), 2) if pairs else None

    summary["judges"] = {name: judge_summary(ok, name) for name in judge_names}
    if len(judge_names) == 2:
        summary["agreement"] = agreement(ok, *judge_names)
        summary["disagreements"] = disagreements(runs, *judge_names)
    return summary


def fmt(value):
    return "n/a" if value is None else value


def agreement_text(entry, kind):
    if entry is None:
        return "n/a"
    if kind == "score":
        return f"±{entry['mean_abs_diff']} avg diff, {entry['exact']:.0%} identical"
    if kind == "bool":
        return f"{entry['agree']:.0%} agree"
    if entry["agree"] is None:
        return "n/a"
    return f"{entry['agree']:.0%} of course verdicts agree"


def markdown_report(summary, runs, meta):
    names = meta["judges"]
    lines = [
        f"# Evaluation report ({meta['started']})",
        "",
        f"Agents: `{meta['model']}`; fact-check: `{meta['verifier'] or 'off'}`; "
        f"judges: {', '.join(f'`{n}`' for n in names) or 'off'}; "
        f"{len(runs)} conversation runs, {summary['turns']} turns, {summary['errors']} errors.",
        "",
        "## Checked by code",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    lines += [f"| {label} | {fmt(summary[key])} |" for key, label in CODE_METRICS]

    if names:
        compare = len(names) == 2
        lines += ["", "## Graded by judges", "",
                  "| Metric | " + " | ".join(f"`{n}`" for n in names) + (" | Agreement |" if compare else ""),
                  "|---|" + "---|" * len(names) + ("---|" if compare else "")]
        for key, label, _, kind in JUDGE_METRICS:
            row = f"| {label} | " + " | ".join(str(fmt(summary["judges"][n][key])) for n in names)
            if compare:
                row += f" | {agreement_text(summary['agreement'][key], kind)}"
            lines.append(row + " |")
        lines.append("| Judge failures | " + " | ".join(str(summary["judges"][n]["failures"]) for n in names)
                     + (" | |" if compare else " |"))
        if compare:
            lines += ["", "### Where the judges disagree", ""]
            if summary["disagreements"]:
                lines.append("Score gaps of 2+ points, 30%+ relevance gaps, or opposite verdicts. Check these by hand.")
                lines.append("")
                for d in summary["disagreements"]:
                    lines.append(f"- [{d['case']}] **{d['message']}**: {'; '.join(d['reasons'])}")
            else:
                lines.append("No large disagreements.")

    lines += ["", "## Turns", ""]
    for run in runs:
        lines.append(f"### {run['case']}" + (f" (run {run['repeat'] + 1})" if meta["repeat"] > 1 else ""))
        for t in run["turns"]:
            if "error" in t:
                lines.append(f"- **{t['message']}**: ERROR {t['error']}")
                continue
            status = "" if t["route_ok"] else f" (WRONG, expected {'/'.join(t['expected_route'])})"
            lines.append(f"- **{t['message']}**: `{t['route']}`{status}, {t['seconds']}s")
            if "checks" in t:
                c = t["checks"]
                verdict = "all constraints met" if c["passed"] else "constraint problems"
                lines.append(f"  - {t['total']} results, {verdict}"
                             + (f"; missing {', '.join(c['missing'])}" if c["missing"] else "")
                             + (f"; {'; '.join(c['count_problems'])}" if c["count_problems"] else ""))
                for code, problems in list(c["violations"].items())[:5]:
                    lines.append(f"    - {code}: {', '.join(problems)}")
            v = t.get("verification")
            if v:
                if "error" in v:
                    lines.append(f"  - fact-check failed: {v['error']}")
                else:
                    lines.append(f"  - fact-check: {'revised, ' + str(len(v['problems'])) + ' problems' if v['revised'] else 'passed'}")
                    lines += [f"    - {p}" for p in v.get("problems", [])[:3]]
            for name, j in t.get("judges", {}).items():
                if "error" in j:
                    lines.append(f"  - `{name}` failed: {j['error']}")
                    continue
                if "sql_faithfulness" in j:
                    lines.append(f"  - `{name}`: SQL {j['sql_faithfulness']}/5, relevance {fmt(j['precision_at_10'])}, "
                                 f"summary {'honest' if j['summary_honest'] else 'misleading'}")
                else:
                    lines.append(f"  - `{name}`: grounded {j['groundedness']}/5, answers {j['answers_question']}/5, "
                                 f"complete {j['completeness']}/5, clear {j['clarity']}/5, "
                                 f"demo labels {'ok' if j['demo_labels_ok'] else 'MISSING'}")
                lines += [f"    - {issue}" for issue in j.get("issues", [])[:3]]
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", nargs="+", help="case ids to run (default: all)")
    parser.add_argument("--repeat", type=int, default=1, help="runs per case, for consistency")
    parser.add_argument("--judges", nargs="+", choices=["openai", "gemini"],
                        help="judge providers to grade with (default: JUDGE_PROVIDER)")
    parser.add_argument("--no-judge", action="store_true", help="code checks only")
    parser.add_argument("--no-verifier", action="store_true", help="turn off the advice fact-check")
    args = parser.parse_args()

    cases = [c for c in CASES if not args.cases or c["id"] in args.cases]
    judges = []
    if not args.no_judge:
        from judge import JUDGE_PROVIDER, Judge
        judges = [Judge(provider=p) for p in dict.fromkeys(args.judges or [JUDGE_PROVIDER])]
    orchestrator = Orchestrator(verify=not args.no_verifier)
    verifier = orchestrator.advisor.verifier
    meta = {"started": datetime.now().strftime("%Y-%m-%d %H:%M"), "model": orchestrator.model,
            "verifier": verifier.name if verifier else None,
            "judges": [j.name for j in judges], "repeat": args.repeat}

    runs = []
    for case in cases:
        for repeat in range(args.repeat):
            session = Session()
            turns = []
            for turn in case["turns"]:
                record = run_turn(orchestrator, judges, session, turn)
                turns.append(record)
                flag = "ERROR" if "error" in record else ("ok" if record["route_ok"] else "WRONG ROUTE")
                extra = ""
                if record.get("checks"):
                    extra = " constraints ok" if record["checks"]["passed"] else " CONSTRAINT PROBLEMS"
                print(f"[{case['id']}] {turn['message']!r} -> {record.get('route', '-')} ({flag}){extra}")
            runs.append({"case": case["id"], "repeat": repeat, "turns": turns})

    summary = summarize(runs, meta["judges"])
    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    with open(os.path.join(RESULTS_DIR, f"{stamp}.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "summary": summary, "runs": runs}, f, indent=2, ensure_ascii=False, default=str)
    with open(os.path.join(RESULTS_DIR, f"{stamp}.md"), "w", encoding="utf-8") as f:
        f.write(markdown_report(summary, runs, meta))

    print()
    for key, label in CODE_METRICS:
        print(f"{label}: {fmt(summary[key])}")
    for name in meta["judges"]:
        print(f"\nJudge {name} ({summary['judges'][name]['failures']} failures)")
        for key, label, _, kind in JUDGE_METRICS:
            line = f"  {label}: {fmt(summary['judges'][name][key])}"
            if "agreement" in summary and name == meta["judges"][-1]:
                line += f"   [agreement: {agreement_text(summary['agreement'][key], kind)}]"
            print(line)
    if summary.get("disagreements"):
        print(f"\n{len(summary['disagreements'])} steps where the judges disagree (see report)")
    print(f"\nReport: {os.path.relpath(os.path.join(RESULTS_DIR, stamp + '.md'), SCRIPT_DIR)}")


if __name__ == "__main__":
    main()
