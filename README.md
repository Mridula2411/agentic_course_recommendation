# AI Course Recommendation System

A natural language course search system that converts your requirements into database queries.

## What It Does

Ask for courses in plain English, get filtered results based on your criteria.

Examples:
- "I want a programming course with projects but no exams"
- "Show me mandatory TIMTM courses"
- "Easy courses with high pass rate"
- "Pass/fail courses with lab work"

## How It Works

1. Natural Language Processing: Gemini AI extracts intent from your query
2. Safe Query Building: Converts intent to SQL with parameterized queries (prevents SQL injection)
3. Database Setup: Queries course database with your filters
4. JSON Output: Results saved to `results/course_results.json`

## Supported Filters

- Major/Program: TIMTM, HCID, CSID, TEDA, etc.
- Credits: min/max credit requirements
- Difficulty: 1 (easy) to 5 (hard)
- Pass Rate: minimum pass percentage
- Examination Type: projects, assignments, exams, labs, seminars
- Grading: pass/fail vs letter graded
- Status: mandatory vs elective courses
- Keywords: search in course names, descriptions, learning outcomes

## Setup

1. Install dependencies:
```bash
pip install pandas openpyxl google-genai
```

2. Set your Gemini API key in the shell. Do not commit the key:
```bash
export GEMINI_API_KEY="your-gemini-api-key"
```

3. Configure Python environment

4. Run the FastAPI backend:
```bash
uvicorn api:app --reload
```

5. Start the React frontend:
```bash
cd Course_Recommendation_React
npm install
npm run dev
```

6. Open your browser and go to:
```
http://localhost:5173
```
or the URL shown in the terminal.

## How the Integration Works

- The React search bar sends your query to the FastAPI backend (`/recommend` endpoint).
- FastAPI processes the input, runs Gemini AI intent extraction, builds a safe SQL query, and returns course results.
- Results are rendered live in the React UI.

## Troubleshooting

- If you see `Failed to fetch results` in the UI:
	- Make sure FastAPI backend is running and reachable at `http://localhost:8000`.
	- Check backend logs for errors (missing dependencies, CORS, etc).
	- Ensure your frontend sends JSON with `{ "user_input": "your search string" }`.
- If you see CORS errors, make sure your FastAPI app includes:
```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
		CORSMiddleware,
		allow_origins=["*"],
		allow_credentials=True,
		allow_methods=["*"],
		allow_headers=["*"],
)
```

## Files

- `app.py` - Main application loop
- `nlp_engine.py` - Gemini AI intent extraction
- `query_engine.py` - Safe SQL query builder
- `data_setup.py` - Database initialization from Excel
- `Database.xlsx` - Source course data
- `courses.db` - SQLite database (auto-generated)
- `results/course_results.json` - Query results

## Security

Uses parameterized queries to prevent SQL injection - user input is never directly inserted into SQL commands.
