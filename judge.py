"""LLM judge for the retrieval and advisor steps.

    openai (default): OPENAI_JUDGE_MODEL or JUDGE_MODEL (default gpt-6-sol), OPENAI_API_KEY
    gemini:           GEMINI_JUDGE_MODEL (default gemini-3.1-pro-preview), GEMINI_API_KEY
"""
import json
import os

from google.genai import types
from pydantic import BaseModel, Field

from advisor_agent import DATA_NOTES, _course_context
from llm import make_client


JUDGE_PROVIDER = os.getenv("JUDGE_PROVIDER", "openai")
DEFAULT_OPENAI_JUDGE = "gpt-6-sol"
DEFAULT_GEMINI_JUDGE = "gemini-3.1-pro-preview"


def judge_model(provider):
    if provider == "openai":
        return os.getenv("OPENAI_JUDGE_MODEL") or os.getenv("JUDGE_MODEL") or DEFAULT_OPENAI_JUDGE
    return os.getenv("GEMINI_JUDGE_MODEL", DEFAULT_GEMINI_JUDGE)
TOP_RESULTS = 10  # results the judge rates for relevance


class ResultRelevance(BaseModel):
    course_code: str
    relevant: bool


class RetrievalGrade(BaseModel):
    sql_faithfulness: int = Field(description="1-5: the SQL captures every stated constraint and adds none")
    results: list[ResultRelevance] = Field(description="Relevance of each listed result to the request")
    summary_honest: bool = Field(description="The summary correctly describes what was found and anything relaxed")
    issues: list[str] = Field(description="Concrete problems, empty if none")


class AdviceGrade(BaseModel):
    groundedness: int = Field(description="1-5: every factual claim is supported by the course data")
    answers_question: int = Field(description="1-5: the answer addresses what the student asked")
    completeness: int = Field(description="1-5: every part of the question is covered, no important point missed")
    clarity: int = Field(description="1-5: easy for a student to understand, well structured, concise")
    demo_labels_ok: bool = Field(description="Synthetic ratings/reviews used in the answer are marked as demo data (true if none are used)")
    issues: list[str] = Field(description="Concrete problems, empty if none")


RETRIEVAL_RUBRIC = """
You grade the retrieval step of a course recommendation system. A student request was
turned into SQL over a course database; you see the request, the SQL, the agent's
summary, and the top results.

- sql_faithfulness (1-5): 5 = every constraint the student stated is in the SQL and
  nothing unrequested restricts the results; 3 = a minor constraint missing or a
  mild extra restriction; 1 = the SQL answers a different question.
  Topic matching via several related LIKE terms is expected, not a fault. The filter
  status = 'ok' is a required data-quality rule (it excludes records whose extraction
  failed checks), not a restriction.
- results: for each listed course, is it relevant to what the student asked for?
- summary_honest: does the summary match the SQL and results, including anything relaxed?
- issues: short, specific problems.
"""

ADVICE_RUBRIC = """
You grade the advisor step of a course recommendation system. The advisor answered a
student's question using only the course data shown below.

- groundedness (1-5): 5 = every factual claim (periods, credits, exams, pass rates,
  difficulty, reviews, prerequisites) is supported by the course data; 1 = key claims
  are invented or contradict the data.
- answers_question (1-5): does it address what the student asked, helpfully?
- completeness (1-5): 5 = every part of the question is answered and no point that
  matters for the student's decision (e.g. a key prerequisite, an exam, a missing
  rating) is left out; 1 = most of the question is ignored.
- clarity (1-5): 5 = a student can understand it at a glance: plain language, well
  structured, no unnecessary length; 1 = confusing or rambling. Judge clarity only;
  do not let style affect the other scores.
- demo_labels_ok: values marked "(demo data)" in the course data are randomly generated.
  If the answer uses any of them, it must mark them as demo data. True if it does, or
  if it uses none.
- issues: short, specific problems.
"""


class Judge:

    def __init__(self, provider=None, model=None, client=None):
        self.provider = provider or JUDGE_PROVIDER
        if self.provider == "openai":
            self.model = model or judge_model("openai")
            if client is None:
                from openai import OpenAI
                client = OpenAI()  # reads OPENAI_API_KEY
        elif self.provider == "gemini":
            self.model = model or judge_model("gemini")
            client = client or make_client()
        else:
            raise RuntimeError(f"Unknown JUDGE_PROVIDER {self.provider!r} (use openai or gemini)")
        self.client = client

    @property
    def name(self):
        return f"{self.provider}:{self.model}"

    def _grade(self, rubric, schema, prompt):
        if self.provider == "openai":
            response = self.client.responses.parse(
                model=self.model, instructions=rubric, input=prompt, text_format=schema,
            )
            grade = response.output_parsed
        else:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=rubric, response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
            grade = response.parsed
        if grade is None:
            raise RuntimeError("Judge returned no structured grade")
        return grade

    def retrieval(self, message, request, previous_sql, search):
        top = [
            {k: c.get(k) for k in ("course_code", "course_name", "credits", "periods", "language",
                                   "grading_scale", "examination")}
            | {"description": (c.get("description") or "")[:300]}
            for c in search["courses"][:TOP_RESULTS]
        ]
        prompt = (
            f"Student message: {message}\n"
            f"Request passed to the retrieval agent: {request}\n"
            + (f"Previous SQL being refined:\n{previous_sql}\n" if previous_sql else "")
            + f"\nSQL:\n{search['sql']}\n\nSummary: {search['summary']}\n"
            f"Total results: {search['total']}\nTop results:\n{json.dumps(top, ensure_ascii=False)}"
        )
        grade = self._grade(RETRIEVAL_RUBRIC, RetrievalGrade, prompt)
        rated = [r for r in grade.results if r.course_code in {c["course_code"] for c in top}]
        return {
            "sql_faithfulness": grade.sql_faithfulness,
            "precision_at_10": sum(r.relevant for r in rated) / len(rated) if rated else None,
            "summary_honest": grade.summary_honest,
            "relevant": {r.course_code: r.relevant for r in rated},
            "issues": grade.issues,
        }

    def advice(self, question, courses, answer, highlighted):
        prompt = (
            f"Data notes: {DATA_NOTES}\n"
            f"Course data shown to the advisor:\n"
            f"{json.dumps([_course_context(c) for c in courses], ensure_ascii=False)}\n\n"
            f"Student question: {question}\n\nAdvisor answer:\n{answer}\n\n"
            f"Courses the advisor highlighted: "
            f"{json.dumps([{'course_code': h['course_code'], 'reason': h['reason']} for h in highlighted], ensure_ascii=False)}"
        )
        grade = self._grade(ADVICE_RUBRIC, AdviceGrade, prompt)
        return grade.model_dump()
