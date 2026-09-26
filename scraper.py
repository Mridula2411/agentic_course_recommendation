"""Scrapes second-cycle KTH courses (EECS and SCI by default, plus the courses in
Database.xlsx) into data/kth_courses.db. Course lists come from the endpoint used
by KTH's course search page. Lists and pages are cached between runs.

    python scraper.py --discover-only
    python scraper.py --dry-run
    python scraper.py
    python scraper.py --refresh
"""
from datetime import datetime, timezone
import argparse
import json
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.robotparser
from collections import deque

import httpx
import pandas as pd
from bs4 import BeautifulSoup


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "data", "kth_courses.db")
SEED_FILE = os.path.join(SCRIPT_DIR, "Database.xlsx")

BASE_URL = "https://www.kth.se"
COURSE_URL = BASE_URL + "/student/kurser/kurs/{code}?l=en"
COURSE_LINK = re.compile(r"/student/kurser/kurs/([A-Z0-9]{6})\b")
COURSE_MENTION = re.compile(r"\b([A-Z]{2}[0-9][0-9A-Z]{3})\b")  # e.g. "DH2320" in prerequisites
USER_AGENT = "course-recommendation-research-bot (+https://github.com/Mridula2411/agentic_course_recommendation)"
CRAWL_DELAY = 2.0  # seconds between requests to kth.se
RETRY_WAITS = [15, 60, 180]  # seconds to back off after a timeout, 429 or 5xx
DEFAULT_MAX_COURSES = 5000

SEARCH_URL = BASE_URL + "/student/kurser/intern-api/sok/en"
SEARCH_LIMIT_WARNING = 250  # a list this long may have been cut off by the endpoint
# How to list each school's courses. EECS has no department codes in KTH's
# course search, so it is searched by course-code prefix; courses from other
# schools that share a prefix are dropped later using "Offered by".
SCHOOLS = {
    "EECS": {"patterns": [p + "2" for p in [
        "DA", "DD", "DH", "DM", "DN", "DT", "EF", "EG", "EH", "EI", "EJ", "EK", "EL", "EM",
        "EN", "EP", "EQ", "ET", "ID", "IE", "IF", "IH", "II", "IK", "IL", "IS", "IV",
    ]]},
    "SCI": {"departments": ["SA", "SD", "SE", "SF", "SG", "SH", "SI", "SK", "SM"]},
}
OFFERED_BY = re.compile(r"Offered by\n\s*([A-Z]+)/")

SCHEMA = """
CREATE TABLE IF NOT EXISTS course_lists (
    query TEXT PRIMARY KEY, -- search query string
    codes TEXT NOT NULL,    -- JSON list of course codes found
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS pages (
    course_code TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    http_status INTEGER,
    text TEXT,
    links TEXT,             -- JSON list of course codes linked from the page
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS courses (
    course_code TEXT PRIMARY KEY,
    university TEXT NOT NULL,
    url TEXT NOT NULL,
    course_name TEXT,
    credits REAL,
    education_cycle TEXT,
    periods TEXT,           -- e.g. "P1, P2"
    terms TEXT,
    language TEXT,
    description TEXT,
    learning_outcomes TEXT,
    prerequisites TEXT,
    recommended_prerequisites TEXT,
    grading_scale TEXT,     -- "A-F" or "P/F"
    examination TEXT,       -- e.g. "LABA (Laboratory work, 3.0 cr, P/F); PROA (...)"
    examination_json TEXT,
    programmes TEXT,
    main_field TEXT,
    offered_by TEXT,
    supplementary_info TEXT,
    status TEXT NOT NULL,   -- "ok" or "needs_review"
    validation_errors TEXT,
    model TEXT,
    extracted_at TEXT
);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_second_cycle(code):
    # KTH codes are two letters, a cycle digit, then three characters (DH2323)
    return len(code) == 6 and code[2] == "2"


def seed_codes():
    df = pd.read_excel(SEED_FILE, header=3)
    codes = df["COURSE CODE"].dropna().astype(str).str.strip().str.upper()
    return [c for c in dict.fromkeys(codes) if re.fullmatch(r"[A-Z]{2}[0-9A-Z]{4}", c)]


def is_degree_project(code, name):
    return code.endswith("X") or name.lower().startswith("degree project")


def offered_by(text):
    """The school a course page says offers the course, e.g. "EECS"."""
    m = OFFERED_BY.search(text or "")
    return m.group(1) if m else None


def page_text_and_links(html):
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("main#mainContent") or soup.find("main") or soup.body
    for tag in main.find_all(["script", "style", "nav"]):
        tag.decompose()
    text = re.sub(r"\n\s*\n+", "\n", main.get_text("\n")).strip()
    links = sorted({m.group(1) for a in soup.find_all("a", href=True) if (m := COURSE_LINK.search(a["href"]))})
    return text, links


def related_codes(text, links):
    """Courses linked from, or mentioned on, a page (prerequisites, related courses)."""
    return sorted(set(links) | set(COURSE_MENTION.findall(text or "")))


class CrawlStopped(Exception):
    """kth.se kept failing or throttling us; stop and let a later run resume from the cache."""


class Crawler:

    def __init__(self, db, delay=CRAWL_DELAY):
        self.db = db
        self.delay = delay
        self.http = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True)
        self._robots = None  # loaded on the first network request, so cached runs work offline
        self.last_request = 0.0
        self.fetched = 0

    def _get(self, url):
        """GET politely: fixed delay between requests, backing off on timeouts, 429 and 5xx."""
        waits = [0, *RETRY_WAITS]
        for attempt, backoff in enumerate(waits):
            if backoff:
                print(f"  waiting {backoff}s before retrying {url}")
                time.sleep(backoff)
            time.sleep(max(0.0, self.delay - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                response = self.http.get(url)
            except httpx.TransportError as e:
                problem = f"{type(e).__name__}"
                continue
            if response.status_code == 429 or response.status_code >= 500:
                problem = f"HTTP {response.status_code}"
                retry_after = response.headers.get("retry-after", "")
                if retry_after.isdigit() and attempt + 1 < len(waits):
                    waits[attempt + 1] = max(waits[attempt + 1], int(retry_after))
                continue
            return response
        raise CrawlStopped(f"kth.se is not responding ({problem}) after {len(RETRY_WAITS)} retries")

    def robots(self):
        if self._robots is None:
            self._robots = urllib.robotparser.RobotFileParser()
            self._robots.parse(self._get(BASE_URL + "/robots.txt").text.splitlines())
        return self._robots

    def course_list(self, params, refresh=False):
        """Second-cycle course codes matching a course search, cached in the database."""
        query = urllib.parse.urlencode({**params, "eduLevel[]": 2})
        if not refresh:
            row = self.db.execute("SELECT codes FROM course_lists WHERE query = ?", (query,)).fetchone()
            if row:
                return json.loads(row[0])
        url = f"{SEARCH_URL}?{query}"
        if not self.robots().can_fetch(USER_AGENT, url):
            raise CrawlStopped(f"robots.txt disallows {SEARCH_URL}")
        response = self._get(url)
        response.raise_for_status()
        results = response.json()["searchData"]["results"]
        self.fetched += 1
        if len(results) >= SEARCH_LIMIT_WARNING:
            print(f"  warning: {len(results)} results for {params}; the list may be cut off")
        codes = [r["kod"] for r in results if not is_degree_project(r["kod"], r.get("benamning", ""))]
        self.db.execute("INSERT OR REPLACE INTO course_lists VALUES (?, ?, ?)", (query, json.dumps(codes), now()))
        self.db.commit()
        return codes

    def school_courses(self, school, refresh=False):
        config = SCHOOLS[school]
        queries = [{"pattern": p} for p in config.get("patterns", [])]
        queries += [{"department[]": d} for d in config.get("departments", [])]
        codes = []
        for params in queries:
            codes += self.course_list(params, refresh)
        return list(dict.fromkeys(codes))

    def page(self, code, refresh=False):
        """Return (http_status, text, links) for a course, from the cache when possible."""
        if not refresh:
            row = self.db.execute("SELECT http_status, text, links FROM pages WHERE course_code = ?", (code,)).fetchone()
            if row:
                return row[0], row[1], related_codes(row[1], json.loads(row[2] or "[]"))

        url = COURSE_URL.format(code=code)
        if not self.robots().can_fetch(USER_AGENT, url):
            print(f"  {code}: blocked by robots.txt, skipping")
            return None, None, []

        response = self._get(url)
        self.fetched += 1

        text, links = (None, [])
        if response.status_code == 200:
            text, links = page_text_and_links(response.text)
        self.db.execute(
            "INSERT OR REPLACE INTO pages VALUES (?, ?, ?, ?, ?, ?)",
            (code, url, response.status_code, text, json.dumps(links), now()),
        )
        self.db.commit()
        return response.status_code, text, related_codes(text, links)


def save_course(db, code, record, errors, model):
    exams = record.examination
    db.execute(
        "INSERT OR REPLACE INTO courses VALUES (" + ", ".join("?" * 24) + ")",
        (
            code, "kth", COURSE_URL.format(code=code), record.course_name, record.credits,
            record.education_cycle, ", ".join(record.periods), ", ".join(record.terms),
            record.language, record.description, record.learning_outcomes, record.prerequisites,
            record.recommended_prerequisites, record.grading_scale,
            "; ".join(f"{m.code} ({m.kind}, {m.credits} cr, {m.grading_scale})" for m in exams),
            json.dumps([m.model_dump() for m in exams]), "; ".join(record.programmes),
            record.main_field, record.offered_by, record.supplementary_info,
            "needs_review" if errors else "ok", "; ".join(errors) or None, model, now(),
        ),
    )
    db.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--schools", nargs="+", default=list(SCHOOLS), choices=list(SCHOOLS))
    parser.add_argument("--max-courses", type=int, default=DEFAULT_MAX_COURSES)
    parser.add_argument("--discover-only", action="store_true", help="list and count courses, fetch no course pages")
    parser.add_argument("--dry-run", action="store_true", help="crawl and cache pages without calling the LLM")
    parser.add_argument("--follow-mentions", action="store_true",
                        help="also crawl second-cycle courses mentioned on pages (may reach other schools)")
    parser.add_argument("--refresh", action="store_true", help="re-fetch lists and pages, re-extract courses")
    parser.add_argument("--delay", type=float, default=CRAWL_DELAY, help="seconds between requests to kth.se")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    crawler = Crawler(db, delay=args.delay)

    spreadsheet = seed_codes()
    school_codes = []
    try:
        for school in args.schools:
            codes = crawler.school_courses(school, refresh=args.refresh)
            print(f"{school}: {len(codes)} second-cycle courses listed (degree projects excluded)")
            school_codes += codes
    except CrawlStopped as e:
        print(f"\nStopping: {e}. Run again later to continue.")
        return
    queue = deque(dict.fromkeys(spreadsheet + school_codes))
    print(f"To crawl: {len(queue)} courses ({len(spreadsheet)} from {os.path.basename(SEED_FILE)}); "
          f"limit {args.max_courses}")
    if args.discover_only:
        cached = db.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        print(f"Already cached: {cached} pages. At {args.delay:.0f}s per page, the rest takes about "
              f"{max(0, len(queue) - cached) * args.delay / 60:.0f} min.")
        return

    extractor = None
    if not args.dry_run:
        from extractor import Extractor
        extractor = Extractor()

    wanted = set(args.schools)
    keep_anyway = set(spreadsheet)  # these carry student ratings, whichever school offers them
    seen = set(queue)
    processed = other_school = extracted = needs_review = 0

    while queue and processed < args.max_courses:
        code = queue.popleft()
        try:
            status, text, links = crawler.page(code, refresh=args.refresh)
        except CrawlStopped as e:
            print(f"\nStopping: {e}. Pages fetched so far are cached; run again later to continue.")
            break
        if status != 200 or not text:
            print(f"  {code}: page unavailable (HTTP {status})")
            continue
        processed += 1
        if code not in keep_anyway and offered_by(text) not in wanted:
            other_school += 1
            continue

        if args.follow_mentions:
            for linked in links:
                if linked not in seen and is_second_cycle(linked):
                    seen.add(linked)
                    queue.append(linked)

        if extractor is None:
            continue
        already = db.execute("SELECT 1 FROM courses WHERE course_code = ?", (code,)).fetchone()
        if already and not args.refresh:
            continue
        try:
            record, errors = extractor.extract(text, code, COURSE_URL.format(code=code))
        except Exception as e:
            print(f"  {code}: extraction failed: {type(e).__name__}: {e}")
            continue
        if record is None:
            print(f"  {code}: no record extracted")
            continue
        save_course(db, code, record, errors, extractor.model)
        extracted += 1
        needs_review += bool(errors)
        flag = f"  NEEDS REVIEW: {'; '.join(errors)}" if errors else ""
        print(f"  {code}: {record.course_name} ({record.credits} cr, {', '.join(record.periods) or 'no period'}){flag}")

    from course_db import update_derived_columns
    update_derived_columns(db)
    total = db.execute("SELECT COUNT(*), SUM(status = 'ok') FROM courses").fetchone()
    print(f"\nPages: {processed} processed ({other_school} from other schools, skipped), "
          f"{crawler.fetched} fetched from kth.se, {len(queue)} still queued")
    if extractor:
        print(f"Extracted this run: {extracted} ({needs_review} need review); "
              f"tokens: {extractor.input_tokens} in / {extractor.output_tokens} out")
    print(f"Database: {total[0]} courses ({total[1] or 0} ok) in {os.path.relpath(DB_PATH, SCRIPT_DIR)}")


if __name__ == "__main__":
    main()
