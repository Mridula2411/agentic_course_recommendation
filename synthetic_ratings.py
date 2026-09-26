"""Generates placeholder ratings and reviews for courses without survey data.
Rows are stored with source = 'synthetic' and shown as demo data.

    python synthetic_ratings.py
    python synthetic_ratings.py --seed 7
    python synthetic_ratings.py --remove
"""
import argparse
import random
import sqlite3

from google.genai import types
from pydantic import BaseModel

from course_db import DB_PATH, ratings_table
from llm import MODEL, make_client


BATCH_SIZE = 20
DESCRIPTION_LIMIT = 400

INSTRUCTIONS = """
You write short, realistic student reviews of university courses for a demo dataset.
For each course you get its name, a description, and fixed numbers: pass rate,
difficulty (1 easy - 5 hard) and overall rating (1-5). Write one review per course,
1-3 sentences, in the voice of a master's student, that is consistent with those
numbers and the course content (e.g. a hard, low-rated course gets a critical
review). Vary tone and topics: workload, teaching, projects, exams, usefulness.
"""


class Review(BaseModel):
    course_code: str
    review: str


class Reviews(BaseModel):
    reviews: list[Review]


def random_numbers(rng):
    difficulty = rng.randint(1, 5)
    rating = round(rng.uniform(2.5, 5.0), 1)
    # harder courses tend to have lower pass rates
    pass_rate = round(min(1.0, max(0.5, 1.02 - 0.07 * difficulty + rng.gauss(0, 0.05))), 3)
    return {"pass_rate": pass_rate, "difficulty": float(difficulty), "rating": rating}


def write_reviews(client, batch):
    prompt = "\n\n".join(
        f"{c['course_code']} {c['course_name']}\n"
        f"Description: {(c['description'] or '')[:DESCRIPTION_LIMIT]}\n"
        f"Pass rate {c['pass_rate']:.0%}, difficulty {c['difficulty']:.0f}/5, rating {c['rating']}/5"
        for c in batch
    )
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=INSTRUCTIONS,
            response_mime_type="application/json",
            response_schema=Reviews,
            temperature=1.0,
        ),
    )
    reviews = response.parsed.reviews if response.parsed else []
    return {r.course_code.strip().upper(): r.review for r in reviews}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--remove", action="store_true", help="delete all synthetic ratings")
    args = parser.parse_args()

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    ratings_table(db)
    if args.remove:
        deleted = db.execute("DELETE FROM student_ratings WHERE source = 'synthetic'").rowcount
        db.commit()
        print(f"Removed {deleted} synthetic ratings")
        return

    courses = [dict(row) for row in db.execute(
        "SELECT course_code, course_name, description FROM courses "
        "WHERE course_code NOT IN (SELECT course_code FROM student_ratings) ORDER BY course_code"
    )]
    print(f"{len(courses)} courses without ratings")
    rng = random.Random(args.seed)
    for course in courses:
        course.update(random_numbers(rng))

    client = make_client()
    saved = 0
    for start in range(0, len(courses), BATCH_SIZE):
        batch = courses[start:start + BATCH_SIZE]
        reviews = write_reviews(client, batch)
        rows = [
            (c["course_code"], c["pass_rate"], c["difficulty"], c["rating"], reviews.get(c["course_code"]), "synthetic")
            for c in batch
        ]
        db.executemany("INSERT OR REPLACE INTO student_ratings VALUES (?, ?, ?, ?, ?, ?)", rows)
        db.commit()
        saved += len(rows)
        missing = sum(1 for c in batch if c["course_code"] not in reviews)
        print(f"  {saved}/{len(courses)} saved" + (f" ({missing} without a review)" if missing else ""))

    counts = dict(db.execute("SELECT source, COUNT(*) FROM student_ratings GROUP BY source").fetchall())
    print(f"Student ratings: {counts.get('survey', 0)} survey, {counts.get('synthetic', 0)} synthetic")


if __name__ == "__main__":
    main()
