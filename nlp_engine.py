from google.genai import Client
import json
import os


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set")

client = Client(api_key=GEMINI_API_KEY)

def extract_intent(user_prompt):

    system_prompt = """
    You are an advanced intent extraction engine for a university course recommendation system.

    Your job is to convert the user's natural language request into structured JSON.

    Return ONLY valid JSON.
    Do NOT explain anything.
    Do NOT include markdown.
    Do NOT include text outside JSON.

    ----------------------------------------------------
    ALLOWED OUTPUT KEYS
    ----------------------------------------------------

    - major: string
        Only include if the user explicitly mentions a program/track code
        Examples: TIMTM, HCID, TEDA, CSID

    - credits_max: number
    - credits_min: number

    - pass_rate_min: decimal (0–1)
    - pass_rate_max: decimal (0–1)

    - difficulty_max: integer (1–5)
    - difficulty_min: integer (1–5)

    - keywords: array of meaningful single words

    - preference_strength: object with keys:
        - pass_rate: "hard" or "soft"
        - difficulty: "hard" or "soft"
        - credits: "hard" or "soft"

    - exclude_keywords: array of words user wants to avoid

    - mandatory_only: boolean
        true if user asks for "mandatory" courses only
        Example: "mandatory courses", "required courses", "compulsory courses"
    
    - elective_only: boolean
        true if user asks for "elective" courses only
        Example: "elective courses", "optional courses"

    - has_exam: boolean
        false if user says "no exams", "no written exam", "without exam"
        true if user explicitly wants courses with exams
    
    - has_project: boolean
        true if user wants "project-based", "with projects", "project work"
    
    - has_assignments: boolean
        true if user wants "assignments", "written assignments"
    
    - has_lab: boolean
        true if user wants "lab work", "laboratory", "hands-on"
    
    - has_seminar: boolean
        true if user wants "seminars", "seminar-based"
    
    - pass_fail_only: boolean
        true if user wants "pass/fail", "P/F grading", "not graded"
    
    - graded_only: boolean
        true if user wants "letter graded", "A-F grading", "graded courses"

    ----------------------------------------------------
    SEMANTIC RULES
    ----------------------------------------------------

    PASS RATE MAPPING:
    - "decent pass rate" = pass_rate_min: 0.7
    - "good pass rate" = pass_rate_min: 0.75
    - "high pass rate" = pass_rate_min: 0.8
    - "very high pass rate" = pass_rate_min: 0.9
    - "low pass rate" = pass_rate_max: 0.6

    DIFFICULTY MAPPING:
    Scale: 1 = very easy, 5 = very hard

    - "easy" = difficulty_max: 2
    - "manageable workload" = difficulty_max: 2
    - "moderate difficulty" = difficulty_max: 3
    - "challenging" = difficulty_min: 4
    - "very challenging" = difficulty_min: 5
    - "not too hard" = difficulty_max: 3

    CREDIT MAPPING:
    - "light course" = credits_max: 6
    - "heavy course" = credits_min: 9
    - "under X credits" = credits_max: X
    - "at least X credits" = credits_min: X

    EXAMINATION TYPE MAPPING:
    - "no exams", "no written exam", "without exam", "exam-free" = has_exam: false
    - "project-based", "with projects", "project work" = has_project: true
    - "assignments", "written assignments", "homework" = has_assignments: true
    - "lab work", "laboratory", "hands-on", "practical work" = has_lab: true
    - "seminars", "seminar-based", "discussion-based" = has_seminar: true
    
    GRADING TYPE MAPPING:
    - "pass/fail", "P/F", "pass or fail", "not graded", "no letter grade" = pass_fail_only: true
    - "graded", "letter graded", "A-F grading", "letter grade" = graded_only: true
    
    Examples:
    - "programming course with projects but no exams" = has_project: true, has_exam: false
    - "courses with only assignments and projects" = has_assignments: true, has_project: true
    - "lab-based courses" = has_lab: true
    - "pass/fail courses without exams" = pass_fail_only: true, has_exam: false

    ----------------------------------------------------
    KEYWORD EXTRACTION RULES
    ----------------------------------------------------

    - Extract meaningful academic keywords
    - Break multi-word phrases into individual words
        Example:
            "machine learning project"
            = ["machine", "learning", "project"]

    - Do NOT include:
        - stop words (a, the, with, for, etc.)
        - subjective words like "interesting", "nice"
        - words already represented in structured fields (e.g., "easy")

    ----------------------------------------------------
    NEGATION HANDLING
    ----------------------------------------------------

    If user excludes something:
    - "not programming"
    - "no math"
    - "avoid theory"

    Add them to:
    exclude_keywords

    ----------------------------------------------------
    HARD vs SOFT PREFERENCES
    ----------------------------------------------------

    If user says:
    - "must"
    - "only"
    - "strictly"
    = mark that filter as "hard"

    If user says:
    - "prefer"
    - "ideally"
    - "would like"
    = mark that filter as "soft"

    If not specified, default to:
    "hard"

    ----------------------------------------------------
    EXAMPLES
    ----------------------------------------------------

    Example Input:
    "I want an easy AI course with a decent pass rate under 9 credits"

    Example Output:
    {
      "credits_max": 9,
      "pass_rate_min": 0.7,
      "difficulty_max": 2,
      "keywords": ["AI"],
      "preference_strength": {
        "pass_rate": "hard",
        "difficulty": "hard",
        "credits": "hard"
      }
    }

    Example Input:
    "Prefer something related to machine learning, not too hard, good success rate"

    Example Output:
    {
      "pass_rate_min": 0.75,
      "difficulty_max": 3,
      "keywords": ["machine", "learning"],
      "preference_strength": {
        "pass_rate": "soft",
        "difficulty": "hard",
        "credits": "hard"
      }
    }

    Example Input:
    "I want all mandatory course in the TIMTM program, and tell me in which period they are offered"

    Example Output:
    {
      "major": "TIMTM",
      "mandatory_only": true,
      "keywords": ["period"]
    }

    Example Input:
    "I want an elective course in HCID with a very high pass rate, but I want to avoid courses about programming, also they should not be too difficult and they should be an elective courses"
    
    Example Output:
    {
      "major": "HCID",
      "pass_rate_min": 0.9,
      "difficulty_max": 3,
      "elective_only": true,
      "exclude_keywords": ["programming"]
      "mandatory_only": false
    }

    Example Input:
    "Give me all the courses that are programming related, I don't care about the difficulty or the pass rate, but I want to avoid courses that are too theoretical and all the courses should have exams"

    Example Output:
    {
      "has_exam": true,
      "keywords": ["programming"],
      "exclude_keywords": ["theoretical"]
    }

    Example Input:
    "I want a course with project work, but I don't want it to be too difficult and I want it to be graded as pass/fail if possible"

    Example Output:
    {
      "has_project": true,
        "difficulty_max": 3,
        "pass_fail_only": true,
        "preference_strength": {
        "has_project": "hard",
        "difficulty": "hard",
        "pass_fail_only": "soft"
        }
    }


    ----------------------------------------------------
    Only return valid JSON.
    """

    response = client.models.generate_content(
        model='models/gemini-2.5-flash',
        contents=system_prompt + "\nUser request:\n" + user_prompt
    )

    text = response.text.strip()
    
    # Remove markdown code blocks if present
    if text.startswith("```"):
        lines = text.split('\n')
        # Remove first line (```json or ```) and last line (```)
        text = '\n'.join(lines[1:-1]).strip()
    
    print(f"[DEBUG] Raw response from Gemini: {repr(text)}")

    try:
        intent = json.loads(text)
        
        # Post-process keywords: split multi-word phrases into individual words
        if "keywords" in intent and isinstance(intent["keywords"], list):
            processed_keywords = []
            stop_words = {"a", "an", "the", "for", "with", "and", "or", "in", "on", "at"}
            
            for keyword in intent["keywords"]:
                # Split on spaces and filter out stop words
                words = keyword.lower().split()
                for word in words:
                    if word not in stop_words and word not in processed_keywords:
                        processed_keywords.append(word)
            
            intent["keywords"] = processed_keywords
        
        return intent
    except Exception as e:
        print(f"[DEBUG] JSON parsing error: {e}")
        return {}
