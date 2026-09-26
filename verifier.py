"""Checks advisor answers against the course data before they are shown.

Uses an OpenAI model (VERIFIER_MODEL, default gpt-6-luna), so the check comes
from a different model family than the advisor. Set ADVICE_VERIFIER=off to disable.
"""
import json
import os

from pydantic import BaseModel, Field

from advisor_agent import DATA_NOTES, _course_context


DEFAULT_MODEL = "gpt-6-luna"

INSTRUCTIONS = """
You fact-check a course advisor's answer before a student sees it. You get the
course data the advisor had, the question, the answer and the courses it highlighted.

Report a problem only if:
1. A factual claim (periods, credits, exams, grading, prerequisites, pass rates,
   difficulty, ratings, review content) is not supported by or contradicts the data.
2. The answer uses a value marked "(demo data)" without saying it is demo data.
3. A highlighted course's reason is not supported by the data.

Do not report style, length, tone or missing extra detail. Each problem must be
specific enough to fix, e.g. "Says DD2421 runs in P2, but the data says P1".
Set ok to true when there are no problems.
"""


class Verdict(BaseModel):
    ok: bool
    problems: list[str] = Field(description="Specific, fixable problems; empty if ok")


class Verifier:

    def __init__(self, client=None, model=None):
        self.model = model or os.getenv("VERIFIER_MODEL", DEFAULT_MODEL)
        if client is None:
            from openai import OpenAI
            client = OpenAI()  # reads OPENAI_API_KEY
        self.client = client

    @property
    def name(self):
        return f"openai:{self.model}"

    def check(self, question, courses, answer, highlighted):
        prompt = (
            f"Data notes: {DATA_NOTES}\n"
            f"Course data:\n{json.dumps([_course_context(c) for c in courses], ensure_ascii=False)}\n\n"
            f"Question: {question}\n\nAnswer:\n{answer}\n\n"
            f"Highlighted courses: {json.dumps(highlighted, ensure_ascii=False)}"
        )
        response = self.client.responses.parse(
            model=self.model, instructions=INSTRUCTIONS, input=prompt, text_format=Verdict,
        )
        if response.output_parsed is None:
            raise RuntimeError("Verifier returned no verdict")
        return response.output_parsed


def make_verifier():
    """The verifier configured by the environment, or None if it is turned off."""
    if os.getenv("ADVICE_VERIFIER", "openai").lower() == "off":
        return None
    if not os.getenv("OPENAI_API_KEY"):
        print("[verifier] OPENAI_API_KEY is not set; advice will not be fact-checked")
        return None
    return Verifier()
