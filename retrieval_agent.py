"""Retrieval agent: writes and tests SQL for a course request. The final query is
run by the code, so every matching course is returned.

    python retrieval_agent.py easy courses with projects in P2
"""
import re
import sys

from google.genai import types

import course_db
from llm import MODEL, make_client


MAX_STEPS = 8          # model calls before the final query is forced
PREVIEW_ROWS = 25      # rows the agent sees per test query
PREVIEW_TEXT = 120     # characters per text value in the preview
MAX_RESULTS = 100      # courses returned to the app

# LIKE '%AI%' on free text also matches "detail", '%ML%' matches "HTML", etc.
TEXT_LIKE = re.compile(r"(course_name|description|learning_outcomes)\s+(?:NOT\s+)?LIKE\s+'%([^%']*)%'", re.IGNORECASE)
MIN_TERM_LENGTH = 4

INSTRUCTIONS = f"""
You are the retrieval agent of a course recommendation system for KTH master's
students. Turn the student's request into one SQLite SELECT query over this database:

{course_db.SCHEMA_DESCRIPTION}

HOW TO WORK
1. Write a query with run_sql and look at the results.
2. If it fails, fix it. If it returns nothing, relax it: broaden topic words, drop the
   least important condition, and say so in your summary. Never drop a condition the
   student stated as a must.
3. Check the rows actually fit the request; refine if they do not.
4. Call submit_query with the final SQL and a one-sentence summary of what it finds
   (and anything you relaxed).

QUERY RULES
- The query must return c.course_code (alias courses as c). Selecting other columns
  is fine; the app fetches full course details itself.
- Include c.status = 'ok'.
- Topics: match several related terms with OR across c.course_name, c.description and
  c.learning_outcomes, e.g. graphic design -> '%graphic%', '%visuali%', '%design%'.
  LIKE is case-insensitive for English letters.
- Never use abbreviations of 3 letters or fewer as LIKE terms on text columns: '%AI%'
  also matches "detail", '%ML%' matches "HTML". Spell terms out ('%artificial
  intelligence%', '%machine learning%'), or pad them with spaces ('% AI %').
- Hard constraints (periods, credits, grading, exam types, language) go in WHERE.
  Soft wishes ("ideally", "prefer", "best", "easy") go in ORDER BY instead.
- Periods: c.periods LIKE '%P2%'. Several periods: OR them.
- "No exam" / "no written exam": c.has_written_exam = 0 (oral exams still allowed).
- Student ratings exist for only some courses: use LEFT JOIN student_ratings r
  USING (course_code), and do not filter on r.* unless the student explicitly asks
  (e.g. "pass rate above 90%"); use them in ORDER BY with NULLS LAST instead.
  If the student asks for real reviews or ratings only, add r.source = 'survey'.
- If the student explicitly asks to sort or rank by something ("sort by rating",
  "best rated", "easiest first"), that comes FIRST in ORDER BY; topic relevance is
  only a tie-breaker then.
- Otherwise order the most relevant courses first. For topic requests, rank by where
  the topic appears, then by any soft wishes, e.g.
  ORDER BY CASE WHEN c.course_name LIKE '%topic%' THEN 0
                WHEN c.description LIKE '%topic%' THEN 1 ELSE 2 END, r.rating DESC NULLS LAST
  Many syllabi mention broad themes (sustainability, ethics) only in their learning
  outcomes; those courses are only loosely "about" the topic, so rank them last.
- Use word stems and spelling variants: '%sustainab%' covers sustainable and
  sustainability; use % for spaces or hyphens that may vary: '%human%computer%interaction%'.
- Keep multi-word topics together: search '%space physics%', not '%space%' OR
  '%physics%', which matches every physics course. Add closely related phrases
  (e.g. '%plasma%' for space physics) rather than generic single words.
"""


def _preview(columns, rows):
    def short(value):
        if isinstance(value, str) and len(value) > PREVIEW_TEXT:
            return value[:PREVIEW_TEXT] + "..."
        return value
    return {"columns": columns, "rows": [{k: short(v) for k, v in row.items()} for row in rows]}


class RetrievalAgent:

    def __init__(self, client=None, model=None):
        self.client = client or make_client()
        self.model = model or MODEL
        tools = [types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name="run_sql",
                description="Run a test SELECT query. Returns the row count and the first rows.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {"sql": {"type": "string"}},
                    "required": ["sql"],
                },
            ),
            types.FunctionDeclaration(
                name="submit_query",
                description="Submit the final query. The app runs it and shows every matching course.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string"},
                        "summary": {"type": "string", "description": "One sentence: what the query finds and anything relaxed"},
                    },
                    "required": ["sql", "summary"],
                },
            ),
        ])]
        self.config = types.GenerateContentConfig(system_instruction=INSTRUCTIONS, tools=tools, temperature=0)
        self.final_config = self.config.model_copy(update={"tool_config": types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="ANY", allowed_function_names=["submit_query"])
        )})

    @staticmethod
    def _short_terms(sql):
        """LIKE terms on text columns short enough to match inside other words."""
        return [term for _, term in TEXT_LIKE.findall(sql)
                if len(term) < MIN_TERM_LENGTH and term == term.strip()]

    def _run_sql(self, sql):
        if short := self._short_terms(sql):
            return {"error": f"LIKE terms {short} are too short: they match inside other words "
                             f"(e.g. 'AI' in 'detail'). Spell them out or pad with spaces ('% AI %')."}
        try:
            columns, rows = course_db.run_select(sql)
        except ValueError as e:
            return {"error": str(e)}
        return {"row_count": len(rows), **_preview(columns, rows[:PREVIEW_ROWS])}

    def _submit(self, sql, summary):
        """Run the final query. Returns (result, response_for_model)."""
        if short := self._short_terms(sql):
            return None, {"error": f"LIKE terms {short} are too short: they match inside other words. "
                                   f"Spell them out or pad with spaces, then submit again."}
        try:
            columns, rows = course_db.run_select(sql)
        except ValueError as e:
            return None, {"error": f"{e}. Fix the query and submit again."}
        if "course_code" not in columns:
            return None, {"error": "The query must return a course_code column. Fix it and submit again."}
        codes = list(dict.fromkeys(row["course_code"] for row in rows))
        result = {
            "sql": sql,
            "summary": summary,
            "total": len(codes),
            "courses": course_db.fetch_courses(codes[:MAX_RESULTS]),
        }
        return result, {"status": "submitted", "row_count": len(codes)}

    def run(self, request, previous_sql=None):
        """Find the courses for a request. Returns {sql, summary, total, courses, steps}."""
        prompt = f"Student request: {request}"
        if previous_sql:
            prompt += (
                "\n\nThe student is refining an earlier search. Build on its SQL, keeping its "
                f"conditions unless the request changes them:\n{previous_sql}"
            )
        history = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]
        steps = []

        for step in range(MAX_STEPS):
            config = self.final_config if step == MAX_STEPS - 1 else self.config
            response = self.client.models.generate_content(model=self.model, contents=history, config=config)
            if not response.candidates or not response.candidates[0].content:
                raise RuntimeError("Gemini returned no content")
            history.append(response.candidates[0].content)

            calls = response.function_calls or []
            if not calls:
                history.append(types.Content(role="user", parts=[types.Part.from_text(
                    text="Use run_sql to test a query, then submit_query with the final SQL."
                )]))
                continue

            result, parts = None, []
            for call in calls:
                args = dict(call.args or {})
                sql = args.get("sql", "")
                if call.name == "run_sql":
                    output = self._run_sql(sql)
                elif call.name == "submit_query":
                    call_result, output = self._submit(sql, args.get("summary", ""))
                    result = call_result or result
                else:
                    output = {"error": f"Unknown tool {call.name}"}
                steps.append({"tool": call.name, "sql": sql, "rows": output.get("row_count"), "error": output.get("error")})
                parts.append(types.Part.from_function_response(name=call.name, response=output))
            history.append(types.Content(role="user", parts=parts))

            if result:
                return {**result, "steps": steps}

        raise RuntimeError("Retrieval agent did not submit a query")


def main():
    request = " ".join(sys.argv[1:]) or input("Request: ")
    result = RetrievalAgent().run(request)
    for step in result["steps"]:
        outcome = f"error: {step['error']}" if step["error"] else f"{step['rows']} rows"
        print(f"[{step['tool']}] {outcome}\n    {' '.join(step['sql'].split())}")
    print(f"\n{result['summary']}\n{result['total']} courses:")
    for course in result["courses"]:
        extra = f", rating {course['rating']}" if course.get("rating") is not None else ""
        print(f"  {course['course_code']} {course['course_name']} ({course['credits']} cr, "
              f"{course['periods'] or 'no period'}{extra})")


if __name__ == "__main__":
    main()
