# KTH Course Advisor

A multi-agent assistant that helps KTH master's students find courses. You describe what you want in plain language ("pass/fail courses about sustainability", "only the ones in P2", "which of these is easiest?") and it searches a database of scraped course data and answers follow-up questions.

## Architecture

```
Offline
  scraper.py + extractor.py   KTH course pages -> structured records (Gemini), validated in code
  course_db.py                student ratings and reviews from Database.xlsx
  synthetic_ratings.py        placeholder ratings for courses without survey data (labelled as demo data)
          |
          v
  data/kth_courses.db

Chat
  orchestrator.py     routes each message: search / refine / advise / reply
  retrieval_agent.py  writes SQL, tests it, fixes or relaxes it, submits the final query
  advisor_agent.py    answers questions about the courses currently shown
  verifier.py         fact-checks each answer (OpenAI); the advisor revises once if needed

Evaluation
  evaluate.py + judge.py   code checks and LLM judges (OpenAI and Gemini) on eval_cases.py
```

A few decisions worth knowing about:

- **Scraping happens offline.** The chat only reads from the database, so it never depends on kth.se being up.
- **Model-written SQL runs on a locked-down connection.** It is read-only, limited to SELECT on the course tables through SQLite's authorizer, and stopped after 5 seconds. Very short `LIKE` terms such as `'%AI%'` are rejected because they match inside other words.
- **The code, not the model, returns the results.** The retrieval agent submits a query and every matching course is returned, so no results are dropped between agents.
- **Constraints the data can answer exactly are computed in code**, for example `has_written_exam`, instead of being inferred by a model.
- **Advice is fact-checked before it is shown.** An OpenAI model checks each answer against the course data; if it finds problems, the advisor revises once. A failed check never blocks the answer. The evaluation judge is a separate, stronger model, so the check and the grading stay independent.
- **Synthetic ratings are labelled.** Every row has a `source` (`survey` or `synthetic`), and synthetic values are marked "(demo data)" wherever the advisor uses them.

## Data

- 379 second-cycle courses from KTH's EECS and SCI schools, scraped from public course pages (credits, periods, examination modules, prerequisites, learning outcomes, programmes).
- Pass rates, difficulty, ratings and reviews from a student survey for 57 courses (`Database.xlsx`).
- Generated placeholder ratings for the remaining courses, for demo purposes only.

The course lists come from the same endpoint KTH's course search page uses. The scraper respects `robots.txt`, waits between requests, backs off on errors and caches everything.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export GEMINI_API_KEY=...          # agents and scraper
export OPENAI_API_KEY=...          # fact-check verifier and OpenAI judge
```

Optional: `GEMINI_MODEL` (default `gemini-2.5-flash`), `GEMINI_JUDGE_MODEL` (default `gemini-3.1-pro-preview`), `VERIFIER_MODEL` (default `gpt-6-luna`), `JUDGE_MODEL` (default `gpt-6-sol`), `ADVICE_VERIFIER=off` to skip the fact-check.

## Usage

Web app:

```bash
uvicorn api:app --reload                               # backend on :8000
cd Course_Recommendation_React && npm install && npm run dev   # frontend on :5173
```

Search results show as course cards; follow-up questions highlight the advisor's picks with a reason, and each search has a "How this was found" panel with the agent's SQL attempts.

Chat in the terminal:

```bash
python orchestrator.py
```

Run one search:

```bash
python retrieval_agent.py project-based courses with no written exam in period 1
```

Rebuild or extend the data:

```bash
python scraper.py --discover-only   # count courses to scrape
python scraper.py                   # scrape and extract (resumes from the cache)
python course_db.py                 # reload survey ratings
python synthetic_ratings.py         # fill courses that have no ratings
```

Evaluate:

```bash
python evaluate.py --no-judge                 # code checks only
python evaluate.py --judges openai gemini     # both judges, with agreement stats
```

Reports are written to `eval_results/`.

## Evaluation

15 test conversations (22 turns). Routing, constraints and must-include courses are checked in code; the rest is graded by two judges from different model families on the same outputs.

| Metric | Result |
|---|---|
| Routing accuracy | 100% |
| Searches where every course meets the constraints | 100% |
| Key courses found | 100% |
| SQL faithfulness (1-5) | 4.87 (OpenAI) / 5.0 (Gemini) |
| Relevance of top 10 results | 0.90 / 0.98 |
| Advice grounded in data (1-5) | 5.0 / 5.0 |
| Advice completeness (1-5) | 4.75 / 5.0 |

The judges gave identical scores 87-100% of the time. In the five steps where they disagreed, checking by hand showed the OpenAI judge was right each time, and the Gemini judge was more lenient towards the Gemini agents.

The main remaining weakness is loosely related courses in the results: keyword search cannot always tell a course that is about a topic from one that only mentions it.

## Original pipeline

The first version (`app.py`, `nlp_engine.py`, `query_engine.py`, `data_setup.py`) turns a request into filters with a single Gemini call. It is still available at the `/recommend` endpoint; the web app uses `/chat`.
