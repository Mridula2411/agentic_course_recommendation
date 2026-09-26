"""Course database access for the agents.

    python course_db.py    # reload student ratings and recompute derived columns
"""
import json
import os
import re
import sqlite3
import time

import pandas as pd


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "data", "kth_courses.db")
RATINGS_FILE = os.path.join(SCRIPT_DIR, "Database.xlsx")

ALLOWED_TABLES = {"courses", "student_ratings"}
QUERY_TIMEOUT = 5.0  # seconds; longer queries are aborted

# Schema as described to the retrieval agent
SCHEMA_DESCRIPTION = """
Table courses: one row per KTH second-cycle (master's level) course, scraped from the
course's public page.
- course_code TEXT (primary key, e.g. 'DH2323'), course_name TEXT, url TEXT
- credits REAL (ECTS, e.g. 7.5)
- periods TEXT: comma-separated study periods the course runs in, e.g. 'P1, P2';
  '' when the page lists no current offering. P1-P2 are autumn, P3-P4 spring.
- terms TEXT: upcoming offerings, e.g. 'Autumn 2026, Spring 2027'
- language TEXT (e.g. 'English', 'Swedish')
- description TEXT (course contents), learning_outcomes TEXT
- prerequisites TEXT (required), recommended_prerequisites TEXT
- grading_scale TEXT: 'A-F' (letter grades) or 'P/F' (pass/fail)
- examination TEXT: modules like 'LABA (Laboratory work, 3.0 cr, P/F); PROA (Project, 3.0 cr, A-F)'.
  Projects PRO*; assignments INL*; labs LAB*; seminars SEM*; exercises ÖVN*.
- has_written_exam INTEGER: 1 if any module is a written exam (including home and
  partial exams), 0 if not. Oral exams do not count. Use this for "no exam" requests.
- programmes TEXT: '; '-separated programmes the course is part of, with names such as
  "Master's Programme, Interactive Media Technology" or codes like HCID, CSVG, TEDA
- main_field TEXT, offered_by TEXT (school/department, e.g. 'EECS/Computer Science'),
  education_cycle TEXT, supplementary_info TEXT
- status TEXT: 'ok' or 'needs_review' (use status = 'ok' unless asked otherwise)

Table student_ratings: student data for some courses only (join on course_code).
- course_code TEXT, pass_rate REAL (0-1, e.g. 0.85), difficulty REAL (1 easy - 5 hard),
  rating REAL (student course rating, 1-5), reviews TEXT (free-text student reviews)
- source TEXT: 'survey' (real student data) or 'synthetic' (randomly generated demo data)
"""

RATINGS_TABLE = """
CREATE TABLE IF NOT EXISTS student_ratings (
    course_code TEXT PRIMARY KEY,
    pass_rate REAL,
    difficulty REAL,
    rating REAL,
    reviews TEXT,
    source TEXT NOT NULL     -- 'survey' or 'synthetic'
)
"""


def ratings_table(db):
    """Create student_ratings, rebuilding it if it predates the source column."""
    columns = [row[1] for row in db.execute("PRAGMA table_info(student_ratings)")]
    if columns and "source" not in columns:
        db.execute("DROP TABLE student_ratings")
    db.execute(RATINGS_TABLE)


def is_written_exam(module):
    """Whether an examination module is a written exam (oral exams are not)."""
    code, kind = module.get("code", "").upper(), module.get("kind", "").lower()
    if "oral" in kind and "written" not in kind:
        return False
    if code.startswith(("TEN", "KON")):  # KTH codes for exams and partial exams
        return True
    return bool(re.search(r"\bexam", kind)) and "assignment" not in kind


def update_derived_columns(db):
    """Compute columns the agents filter on from the structured examination data."""
    columns = [row[1] for row in db.execute("PRAGMA table_info(courses)")]
    if "has_written_exam" not in columns:
        db.execute("ALTER TABLE courses ADD COLUMN has_written_exam INTEGER")
    rows = db.execute("SELECT course_code, examination_json FROM courses").fetchall()
    db.executemany(
        "UPDATE courses SET has_written_exam = ? WHERE course_code = ?",
        [(int(any(is_written_exam(m) for m in json.loads(exams or "[]"))), code) for code, exams in rows],
    )
    db.commit()


def load_student_ratings():
    """Copy pass rates, difficulty, ratings and reviews from Database.xlsx."""
    df = pd.read_excel(RATINGS_FILE, header=3)
    df = df.rename(columns={
        "COURSE CODE": "course_code", "PASS PERCENTAGE ": "pass_rate",
        "STUDENT DIFFICULTY RATING": "difficulty", "STUDENT COURSE RATING": "rating",
        "STUDENT REVIEWS": "reviews",
    })[["course_code", "pass_rate", "difficulty", "rating", "reviews"]]
    df = df.dropna(subset=["course_code"])
    df["course_code"] = df["course_code"].astype(str).str.strip().str.upper()
    df["pass_rate"] = pd.to_numeric(df["pass_rate"], errors="coerce") / 100
    for column in ["difficulty", "rating"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["source"] = "survey"
    with sqlite3.connect(DB_PATH) as db:
        ratings_table(db)
        db.execute("DELETE FROM student_ratings WHERE source = 'survey'")
        # survey data replaces synthetic rows for the same course
        db.executemany("DELETE FROM student_ratings WHERE course_code = ?", [(c,) for c in df["course_code"]])
        df.to_sql("student_ratings", db, if_exists="append", index=False)
    return len(df)


def _authorize(action, arg1, arg2, db_name, trigger):
    # only reads of the course tables and function calls are allowed
    if action == sqlite3.SQLITE_SELECT or action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_RECURSIVE:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        return sqlite3.SQLITE_OK if arg1 in ALLOWED_TABLES else sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_DENY


def read_only_connection():
    """A connection that can only SELECT from the course tables, with a time limit."""
    db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.set_authorizer(_authorize)
    return db


def run_select(sql, max_rows=None):
    """Run one read-only SELECT. Returns (columns, rows as dicts); raises ValueError on bad SQL."""
    statement = sql.strip().rstrip(";").strip()
    if ";" in statement:
        raise ValueError("Only a single statement is allowed")
    if not re.match(r"(?is)^(select|with)\b", statement):
        raise ValueError("Only SELECT queries are allowed")

    db = read_only_connection()
    deadline = time.monotonic() + QUERY_TIMEOUT
    db.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)
    try:
        cursor = db.execute(statement)
        rows = cursor.fetchmany(max_rows) if max_rows else cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        return columns, [dict(row) for row in rows]
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e):
            raise ValueError(f"Query took longer than {QUERY_TIMEOUT:.0f}s and was stopped") from e
        raise ValueError(str(e)) from e
    except sqlite3.DatabaseError as e:
        raise ValueError(str(e)) from e
    finally:
        db.close()


def fetch_courses(course_codes):
    """Full course rows with student ratings, in the order given."""
    codes = [c.strip().upper() for c in course_codes]
    if not codes:
        return []
    placeholders = ", ".join("?" for _ in codes)
    _, rows = run_select_params(
        f"SELECT c.*, r.pass_rate, r.difficulty, r.rating, r.reviews, r.source AS ratings_source FROM courses c "
        f"LEFT JOIN student_ratings r USING (course_code) WHERE c.course_code IN ({placeholders})",
        codes,
    )
    by_code = {row["course_code"]: row for row in rows}
    return [by_code[c] for c in codes if c in by_code]


def run_select_params(sql, params):
    db = read_only_connection()
    try:
        cursor = db.execute(sql, params)
        return [d[0] for d in cursor.description], [dict(row) for row in cursor.fetchall()]
    finally:
        db.close()


if __name__ == "__main__":
    print(f"Loaded student ratings for {load_student_ratings()} courses into {os.path.relpath(DB_PATH, SCRIPT_DIR)}")
    with sqlite3.connect(DB_PATH) as db:
        update_derived_columns(db)
    print("Updated derived columns (has_written_exam)")
