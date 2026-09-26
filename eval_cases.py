"""Test conversations for evaluate.py (see evaluate.check_results for the checks)."""

CASES = [
    {
        "id": "ml-refine-advise",
        "turns": [
            {"message": "machine learning courses", "route": ["search"],
             "checks": {"topic_any": ["machine learning", "deep learning", "neural", "artificial intelligence"],
                        "must_include": ["DD2421", "DD2434"], "min_results": 3}},
            {"message": "only the ones in P2", "route": ["refine"],
             "checks": {"periods_include": "P2", "topic_any": ["machine learning", "deep learning", "neural", "artificial intelligence"],
                        "min_results": 1}},
            {"message": "which of these is the easiest?", "route": ["advise"]},
        ],
    },
    {
        "id": "sustainability-pass-fail",
        "turns": [
            {"message": "pass/fail courses about sustainability", "route": ["search"],
             "checks": {"grading": "P/F", "topic_any": ["sustainab"], "must_include": ["DM2801", "II2210"]}},
        ],
    },
    {
        "id": "projects-no-exam-p1",
        "turns": [
            {"message": "project-based courses with no written exam in period 1", "route": ["search"],
             "checks": {"periods_include": "P1", "no_written_exam": True, "exam_includes": ["PRO", "project"], "min_results": 3}},
        ],
    },
    {
        "id": "graphics-credits",
        "turns": [
            {"message": "computer graphics or visualization courses, at most 7.5 credits", "route": ["search"],
             "checks": {"max_credits": 7.5, "topic_any": ["graphic", "visuali"], "must_include": ["DD2257", "DH2320"]}},
            {"message": "sort them by student rating", "route": ["refine"],
             "checks": {"max_credits": 7.5, "topic_any": ["graphic", "visuali"], "min_results": 2}},
        ],
    },
    {
        "id": "robotics-english",
        "turns": [
            {"message": "robotics courses taught in English", "route": ["search"],
             "checks": {"language_contains": "English", "topic_any": ["robot"], "must_include": ["DD2410"]}},
        ],
    },
    {
        "id": "quantum-then-details",
        "turns": [
            {"message": "quantum computing courses", "route": ["search"],
             "checks": {"topic_any": ["quantum"], "must_include": ["DD2367"]}},
            {"message": "tell me more about the first one", "route": ["advise"]},
        ],
    },
    {
        "id": "security-p1-or-p2",
        "turns": [
            {"message": "cybersecurity courses in P1 or P2", "route": ["search"],
             "checks": {"periods_any": ["P1", "P2"], "topic_any": ["secur", "cyber", "hack", "crypt", "privacy"],
                        "min_results": 3}},
        ],
    },
    {
        "id": "power-ratings-demo-label",
        "turns": [
            {"message": "electric power systems courses with the best student ratings", "route": ["search"],
             "checks": {"topic_any": ["power", "electric"], "min_results": 3}},
            {"message": "what do students say about the top one?", "route": ["advise"]},
        ],
    },
    {
        "id": "hci-programme",
        "turns": [
            {"message": "human-computer interaction courses in the HCID programme", "route": ["search"],
             "checks": {"programmes_contains": "HCID", "min_results": 3}},
        ],
    },
    {
        "id": "compare-two",
        "turns": [
            {"message": "compare DD2421 and DD2434", "route": ["search"],
             "checks": {"must_include": ["DD2421", "DD2434"]}},
            {"message": "which one is harder according to students?", "route": ["advise"]},
        ],
    },
    {
        "id": "perfect-pass-rate",
        "turns": [
            {"message": "courses where everyone passes, 100% pass rate", "route": ["search"],
             "checks": {"min_pass_rate": 1.0, "min_results": 1}},
        ],
    },
    {
        "id": "space-physics",
        "turns": [
            {"message": "space physics courses", "route": ["search"],
             "checks": {"topic_any": ["space", "plasma"], "must_include": ["EF2240", "EF2245"]}},
            {"message": "any of them without a written exam?", "route": ["refine", "advise"]},
        ],
    },
    {
        "id": "greeting",
        "turns": [{"message": "hi there!", "route": ["reply"]}],
    },
    {
        "id": "too-vague",
        "turns": [{"message": "I want something good", "route": ["reply"]}],
    },
    {
        "id": "off-topic",
        "turns": [{"message": "what's the weather in Stockholm today?", "route": ["reply"]}],
    },
]
