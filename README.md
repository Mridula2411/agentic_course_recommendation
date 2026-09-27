# KTH Course Advisor

A multi-agent assistant that helps KTH master's students find courses. You describe what you want in plain language and it searches a database of scraped KTH course data, then answers follow-up questions about the results.

```
You:      pass/fail courses about sustainability
Advisor:  Finds pass/fail courses about sustainability, courses centred on it first. (25 courses)
You:      which of these is the easiest?
Advisor:  SA2001 Sustainable development and research methodology in mathematics is rated
          1.0 for difficulty (demo data) ...                                  [Fact-checked]
```

## Contents

- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Using the app](#using-the-app)
- [Other ways to run it](#other-ways-to-run-it)
- [Configuration](#configuration)
- [Updating the course data](#updating-the-course-data)
- [Evaluation](#evaluation)
- [How it works](#how-it-works)
- [Troubleshooting](#troubleshooting)
- [Project structure](#project-structure)

## Requirements

- Python 3.10 or newer
- Node.js 20 or newer (for the web app)
- A **Gemini API key** with billing enabled ([Google AI Studio](https://aistudio.google.com/apikey)). The free tier allows only about 20 requests a day, which is a few questions.
- An **OpenAI API key** (optional). Used to fact-check answers and to run the OpenAI judge in the evaluation. Without it the app still works, answers are just not fact-checked.

## Quick start

The course database (`data/kth_courses.db`) is included, so you do not need to scrape anything to try the app.

**1. Install**

```bash
git clone <this repo>
cd agentic_course_recommendation
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd Course_Recommendation_React
npm install
cd ..
```

**2. Set your API keys**

```bash
export GEMINI_API_KEY=your-gemini-key
export OPENAI_API_KEY=your-openai-key      # optional
```

These only last for the current terminal. To avoid typing them every time, add the same lines to `~/.zshrc` (or `~/.bashrc`) and open a new terminal. Never commit keys or paste them anywhere public; Google disables Gemini keys it finds exposed.

**3. Start the backend** (terminal 1)

```bash
source .venv/bin/activate
uvicorn api:app --reload
```

Wait for `Uvicorn running on http://127.0.0.1:8000`.

**4. Start the frontend** (terminal 2)

```bash
cd Course_Recommendation_React
npm run dev
```

**5. Open http://localhost:5173** and click one of the example searches.

## Using the app

Type a request in the search bar, or click an example. You can then keep the conversation going:

| You type | What happens |
|---|---|
| `machine learning courses taught in English` | A new search. Results appear as course cards. |
| `only the ones in P2` | Narrows the current results. |
| `sort them by student rating` | Re-orders the current results. |
| `which of these is the easiest and why?` | The advisor answers from the courses shown and highlights its picks. |
| `hi` or something vague | A short reply or a clarifying question. |

What you see on screen:

- **Course cards** show the code, credits, student rating, pass rate, study periods, whether there is a written exam, the grading scale, a short description and a link to the official KTH course page.
- **demo data** badge: this course has no real survey data, so its rating, pass rate and reviews are generated placeholders. The advisor also writes "(demo data)" whenever it uses those values.
- **Advisor's picks**: after a follow-up question, the courses the advisor recommends are shown first, outlined, with the reason on each card.
- **How this was found**: expand it under a search to see every SQL query the retrieval agent tried, including failed ones and how it fixed them.
- **Fact-checked** / **Revised after a fact-check**: every advisor answer is checked against the course data by a separate model. If problems were found, the answer was rewritten and you can expand the note to see what was fixed.
- **New conversation** clears the chat and results.

Things to keep in mind:

- The database covers 379 second-cycle courses, almost all from the EECS school (363). Only 11 SCI courses are included so far, because the SCI crawl was interrupted.
- Real student ratings and reviews exist for 57 courses. Everything marked "demo data" is made up and only there to demonstrate the app.
- Periods and terms reflect the course pages at the time they were scraped. Always check the linked course page before registering.

## Other ways to run it

Chat in the terminal (no frontend needed):

```bash
python orchestrator.py
```

Type `new` to start over and `exit` to quit. Each reply shows which route was taken, and searches print their SQL.

Run a single search and see every step the retrieval agent took:

```bash
python retrieval_agent.py project-based courses with no written exam in period 1
```

The original one-shot pipeline is still available at `POST /recommend`; the web app uses `POST /chat`:

```bash
curl -X POST localhost:8000/chat -H 'Content-Type: application/json' \
     -d '{"message": "quantum computing courses"}'
```

Send the returned `session_id` with the next message to continue the same conversation.

## Configuration

All settings are environment variables.

| Variable | Default | Used for |
|---|---|---|
| `GEMINI_API_KEY` | required | Agents, scraper, synthetic reviews |
| `OPENAI_API_KEY` | not set | Fact-check verifier and OpenAI judge |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Router, retrieval agent, advisor, extractor |
| `VERIFIER_MODEL` | `gpt-6-luna` | Fact-check verifier |
| `ADVICE_VERIFIER` | on when `OPENAI_API_KEY` is set | Set to `off` to skip the fact-check |
| `JUDGE_PROVIDER` | `openai` | Default judge for `evaluate.py` |
| `JUDGE_MODEL` | `gpt-6-sol` | OpenAI judge model |
| `GEMINI_JUDGE_MODEL` | `gemini-3.1-pro-preview` | Gemini judge model |

## Updating the course data

Only needed if you want fresher data or more courses. The scraper is polite: it respects `robots.txt`, waits 2 seconds between requests, backs off when kth.se struggles and caches every page, so a stopped run resumes where it left off.

```bash
python scraper.py --discover-only   # list the courses to scrape and estimate the time
python scraper.py --dry-run         # download and cache pages only, no Gemini calls
python scraper.py                   # download and extract with Gemini
python scraper.py --delay 6         # slower, if kth.se starts blocking requests
python course_db.py                 # reload the survey ratings from Database.xlsx
python synthetic_ratings.py         # add demo ratings for courses without any
```

`--schools EECS SCI` chooses the schools, `--refresh` re-downloads and re-extracts everything, and `python synthetic_ratings.py --remove` deletes all demo ratings. Adding real ratings to `Database.xlsx` and running `python course_db.py` replaces the demo data for those courses.

## Evaluation

`evaluate.py` runs 15 test conversations (22 turns, in `eval_cases.py`) through the full pipeline and grades every step. Routes, hard constraints (periods, grading, exams, credits, language) and must-include courses are checked in code. SQL quality, result relevance and the advisor's answers are graded by LLM judges.

```bash
python evaluate.py --no-judge                  # code checks only, fast and cheap
python evaluate.py                             # with the OpenAI judge
python evaluate.py --judges openai gemini      # two judges on the same outputs, with agreement stats
python evaluate.py --no-verifier               # advisor without the fact-check, for comparison
python evaluate.py --repeat 3                  # run each case 3 times to measure consistency
python evaluate.py --cases greeting compare-two
```

Each run writes a Markdown report and a JSON file to `eval_results/`. A full run with one judge costs roughly $0.50 in API usage.

Latest results:

| Metric | Result |
|---|---|
| Routing accuracy | 100% |
| Searches where every course meets the constraints | 100% |
| Key courses found | 100% |
| SQL faithfulness (1-5) | 4.93 |
| Relevance of top 10 results | 0.90 |
| Advice grounded in data (1-5) | 4.75 |
| Advice answers the question / clarity (1-5) | 5.0 / 5.0 |
| Demo data labelled | 100% |

Findings worth noting:

- **Two judges, different families.** Graded on the same outputs, the OpenAI and Gemini judges gave identical scores 87-100% of the time. In the five steps where they disagreed, checking by hand showed the OpenAI judge was right each time; the Gemini judge was more lenient towards the Gemini agents.
- **The evaluation found real bugs.** For example, the retrieval agent searched for `'%ML%'`, which also matched "HTML" and returned 331 of 379 courses. A code-level check now rejects such short terms.
- **The fact-check made no measurable difference on this test set.** It checked every answer and found nothing to fix, because the advisor already labels demo data reliably. Harder advice cases are needed to measure its value properly.
- **Main remaining weakness:** keyword search cannot always tell a course that is about a topic from one that only mentions it, so loosely related courses appear lower in the results.

## How it works

```
Offline
  scraper.py + extractor.py   KTH course pages -> structured records (Gemini), validated in code
  course_db.py                student ratings and reviews from Database.xlsx
  synthetic_ratings.py        demo ratings for courses without survey data
          |
          v
  data/kth_courses.db

Chat
  orchestrator.py     routes each message: search / refine / advise / reply
  retrieval_agent.py  writes SQL, tests it, fixes or relaxes it, submits the final query
  advisor_agent.py    answers questions about the courses currently shown
  verifier.py         fact-checks each answer (OpenAI); the advisor revises once if needed

Evaluation
  evaluate.py + judge.py   code checks and LLM judges on eval_cases.py
```

Design decisions:

- **Scraping happens offline.** The chat only reads from the database, so it never depends on kth.se being up.
- **Model-written SQL runs on a locked-down connection:** read-only, SELECT on the course tables only (enforced by SQLite's authorizer), stopped after 5 seconds. Very short `LIKE` terms are rejected.
- **The code, not the model, returns the results.** The retrieval agent submits its final query and every matching course is returned, so nothing is dropped between agents.
- **Exact constraints are computed in code**, for example `has_written_exam`, instead of being inferred by a model.
- **Advice is checked before it is shown** by a model from a different family than the advisor. A failed check never blocks the answer. The evaluation judge is a separate, stronger model, so checking and grading stay independent.
- **Synthetic data is labelled end to end:** a `source` column in the database, "(demo data)" on every generated value the advisor sees, a badge in the UI and a check in the judge.

## Troubleshooting

| Problem | Fix |
|---|---|
| `GEMINI_API_KEY is not set` | Export it in the same terminal that runs the command. Each new terminal needs it again unless it is in `~/.zshrc`. |
| The page loads but searches say "Could not reach the server" | The backend is not running. Start `uvicorn api:app --reload` in another terminal. |
| `429 RESOURCE_EXHAUSTED ... PerDay` | The Gemini free-tier daily quota is used up. Enable billing on the key's Google Cloud project. |
| `403 ... reported as leaked` or `has been suspended` | Google disabled the key. Delete it and create a new one, ideally in a new project. |
| `You have no credits remaining` (OpenAI) | Add credits to the OpenAI account, or set `ADVICE_VERIFIER=off` and use `--judges gemini` for evaluation. |
| `404 ... model is no longer available` | Set the matching model variable (`GEMINI_MODEL`, `VERIFIER_MODEL`, `JUDGE_MODEL`, `GEMINI_JUDGE_MODEL`) to a model your account can use. |
| Answers show "Not fact-checked" | The OpenAI check failed; the backend terminal shows why. Answers are still shown. |
| The shell shows `dquote>` | A quote was left open, often from pasting. Press Ctrl+C and retype the command. |
| `unrecognized arguments: # ...` | zsh does not treat `#` as a comment when pasted. Run commands without the trailing comments. |
| The scraper stops with "kth.se is not responding" | kth.se is down or rate-limiting. Wait, then run `python scraper.py --delay 6`; it resumes from the cache. |

## Project structure

```
api.py                  FastAPI backend: POST /chat (agents) and POST /recommend (original pipeline)
orchestrator.py         router and conversation state
retrieval_agent.py      SQL-writing retrieval agent
advisor_agent.py        advisor for follow-up questions
verifier.py             fact-check for advisor answers
course_db.py            database schema, read-only SQL runner, survey ratings loader
llm.py                  shared Gemini client
scraper.py              KTH course scraper
extractor.py            course page -> structured record
synthetic_ratings.py    demo ratings and reviews
evaluate.py             evaluation runner and report
judge.py                LLM judges (OpenAI and Gemini)
eval_cases.py           test conversations
data/kth_courses.db     course database
Database.xlsx           student survey data
Course_Recommendation_React/   web app (React + Vite)

app.py, nlp_engine.py, query_engine.py, data_setup.py   original one-shot pipeline
```
