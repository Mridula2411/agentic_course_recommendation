import sqlite3
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_DB = os.path.join(SCRIPT_DIR, "courses.db")

def build_safe_query(filters):
    base_query = "SELECT * FROM courses WHERE 1=1"
    params = []
    # Handle period keywords like 'P1', 'P2', etc. and 'any study period'
    period_keywords = [k.strip().upper() for k in filters.get('keywords', []) if k.strip().upper() in ['P1', 'P2', 'P3', 'P4']]
    any_period_keywords = [k for k in filters.get('keywords', []) if 'any study period' in k.lower() or 'any period' in k.lower()]
    if period_keywords:
        # Filter for specific periods
        period_clauses = []
        for period in period_keywords:
            period_clauses.append("offered_in_period LIKE ?")
            params.append(f"%{period}%")
        if period_clauses:
            base_query += " AND (" + " OR ".join(period_clauses) + ")"
    elif any_period_keywords:
        # 'Any study period' means any of P1, P2, P3, P4
        base_query += " AND (offered_in_period LIKE ? OR offered_in_period LIKE ? OR offered_in_period LIKE ? OR offered_in_period LIKE ?)"
        params.extend(['%P1%', '%P2%', '%P3%', '%P4%'])

    base_query = "SELECT * FROM courses WHERE 1=1"
    params = []

    if "major" in filters:
        # If searching for mandatory courses, use exact match for cleaner results
        if filters.get("mandatory_only") or filters.get("elective_only"):
            base_query += " AND major = ?"
            params.append(filters['major'])
        else:
            base_query += " AND major LIKE ?"
            params.append(f"%{filters['major']}%")

    if "credits_max" in filters:
        base_query += " AND credits <= ?"
        params.append(filters["credits_max"])

    if "credits_min" in filters:
        base_query += " AND credits >= ?"
        params.append(filters["credits_min"])

    if "pass_rate_min" in filters:
        base_query += " AND pass_rate >= ?"
        params.append(filters["pass_rate_min"])

    if "difficulty_max" in filters:
        base_query += " AND difficulty <= ?"
        params.append(filters["difficulty_max"])
    
    if "mandatory_only" in filters and filters["mandatory_only"]:
        base_query += " AND mandatory_elective = ?"
        params.append('M')
    
    if "elective_only" in filters and filters["elective_only"]:
        base_query += " AND mandatory_elective = ?"
        params.append('E')
    
    # Examination type filters
    if "has_exam" in filters and not filters["has_exam"]:
        # Exclude courses with written exams (TEN)
        base_query += " AND (examination NOT LIKE ? OR examination IS NULL)"
        params.append('%TEN%')
    
    if "has_project" in filters and filters["has_project"]:
        # Must have project (PRO)
        base_query += " AND examination LIKE ?"
        params.append('%PRO%')
    
    if "has_assignments" in filters and filters["has_assignments"]:
        # Must have assignments (INL)
        base_query += " AND examination LIKE ?"
        params.append('%INL%')
    
    if "has_lab" in filters and filters["has_lab"]:
        # Must have lab work (LAB or OVN)
        base_query += " AND (examination LIKE ? OR examination LIKE ?)"
        params.extend(['%LAB%', '%OVN%'])
    
    if "has_seminar" in filters and filters["has_seminar"]:
        # Must have seminars (SEM)
        base_query += " AND examination LIKE ?"
        params.append('%SEM%')
    
    # Grading criteria filters
    if "pass_fail_only" in filters and filters["pass_fail_only"]:
        # Pass/Fail grading only (P/F, P,F, P, F)
        base_query += " AND (grading_criteria LIKE ? OR grading_criteria LIKE ? OR grading_criteria LIKE ?)"
        params.extend(['%P/F%', '%P,F%', '%P, F%'])
    
    if "graded_only" in filters and filters["graded_only"]:
        # Letter graded courses (A, B, C, D, E, FX, F)
        base_query += " AND grading_criteria LIKE ?"
        params.append('%A, B, C%')
    
    # Custom logic for advanced filtering
    # Programming: check for 'skills in programming' in prerequisites
    # List of valid topic tags (should match those in data_setup.py)
    valid_topics = [
        "AI", "Programming", "Data Science", "Sustainability", "Ethics", "Design", "HCI", "XR", "Game Development", "Project", "Seminar", "Lab", "Visualization"
    ]
    if "keywords" in filters and any(k.lower() in ["programming", "programing"] for k in filters["keywords"]):
        base_query += " AND ((prerequisite LIKE ?) OR (prerequisite LIKE ?))"
        params.append("%programming%")
        params.append("%computer graphics%")
    elif "keywords" in filters and filters["keywords"]:
        # Normalize valid_topics and keywords to lowercase for robust matching
        valid_topics_lower = [t.lower() for t in valid_topics]
        topic_conditions = []
        for keyword in filters["keywords"]:
            keyword_lower = keyword.lower()
            if keyword_lower in valid_topics_lower:
                topic_conditions.append("LOWER(topics) LIKE ?")
                params.append(f"%{keyword_lower}%")
        if topic_conditions:
            # If any valid topic is present, filter ONLY by those topics (ignore all other keywords)
            base_query += " AND (" + " OR ".join(topic_conditions) + ")"
        else:
            # Only fallback to keyword search if NO valid topics are present in keywords
            keyword_conditions = []
            for keyword in filters["keywords"]:
                keyword_conditions.append("(course_name LIKE ? OR description LIKE ? OR learning_outcomes LIKE ?)")
                keyword_param = f"%{keyword}%"
                params.extend([keyword_param, keyword_param, keyword_param])
            base_query += " AND (" + " OR ".join(keyword_conditions) + ")"

    # No exam: examination does not contain TEN1 or TENA
    if "has_exam" in filters and filters["has_exam"] is False:
        base_query += " AND (examination NOT LIKE ? AND examination NOT LIKE ? OR examination IS NULL)"
        params.append("%TEN1%")
        params.append("%TENA%")

    # Force exact credits if only credits_min is set and credits_max is not, and credits_min is a float/int
    if "credits_min" in filters and ("credits_max" not in filters or filters["credits_max"] is None):
        base_query += " AND credits = ?"
        params.append(filters["credits_min"])
    elif "credits_min" in filters and "credits_max" in filters and filters["credits_min"] == filters["credits_max"]:
        base_query += " AND credits = ?"
        params.append(filters["credits_min"])
    else:
        if "credits_min" in filters:
            base_query += " AND credits >= ?"
            params.append(filters["credits_min"])
        if "credits_max" in filters:
            base_query += " AND credits <= ?"
            params.append(filters["credits_max"])

    return base_query, params

def execute_query(query, params):
    conn = sqlite3.connect(SQLITE_DB)
    cursor = conn.cursor()
    cursor.execute(query, params)

    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    conn.close()

    results = [dict(zip(columns, row)) for row in rows]
    return results
