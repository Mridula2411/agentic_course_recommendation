"""Advisor agent: answers questions about the courses currently shown."""
import json
from typing import Optional

from google.genai import types
from pydantic import BaseModel, Field

from llm import MODEL, make_client


TEXT_LIMIT = 600  # characters per long text field sent to the model

INSTRUCTIONS = """
You are a friendly academic advisor for KTH master's students. The student has
searched the course catalogue and is asking about the courses found. Answer using
ONLY the course data provided and the conversation.

- Be concrete: cite periods, credits, examination, prerequisites, pass rates,
  difficulty and student reviews where they matter.
- Student ratings and reviews exist for only some courses. Missing data is not a
  negative; say when it limits your comparison.
- Values marked "(demo data)" are randomly generated, not real student opinions.
  Whenever you use one, keep the "(demo data)" label next to it in your answer. When
  you quote or paraphrase a review marked "(demo data)", call it a demo review.
- If the data cannot answer the question, say so and suggest what the student could
  search for instead.
- In highlighted_courses, list the courses your answer recommends or singles out
  (best first), each with a short reason. Leave it empty if you single out none.
- Keep the answer short: a few sentences or a short list.
"""


class Highlight(BaseModel):
    course_code: str
    reason: str


class Advice(BaseModel):
    answer: str = Field(description="Answer to the student, in Markdown")
    highlighted_courses: list[Highlight]


RATING_FIELDS = ["pass_rate", "difficulty", "rating", "reviews"]

# Sent to the advisor and the judge along with the course data
DATA_NOTES = (
    "pass_rate is a share of students (1.0 = 100%); difficulty is 1 (easy) to 5 (hard); "
    "rating is the student course rating from 1 to 5. Values marked '(demo data)' are "
    "randomly generated placeholders, not real student opinions."
)


def _course_context(course):
    def short(value):
        if isinstance(value, str) and len(value) > TEXT_LIMIT:
            return value[:TEXT_LIMIT] + "..."
        return value
    fields = ["course_code", "course_name", "credits", "periods", "terms", "language", "grading_scale",
              "examination", "prerequisites", "description", "learning_outcomes", "programmes", *RATING_FIELDS]
    context = {field: short(course.get(field)) for field in fields if course.get(field) not in (None, "")}
    if course.get("ratings_source") == "synthetic":
        for field in RATING_FIELDS:
            if field in context:
                context[field] = (f"(demo data) {context[field]}" if field == "reviews"
                                  else f"{context[field]} (demo data)")
    return context


class AdvisorAgent:

    def __init__(self, client=None, model=None, verifier=None):
        self.client = client or make_client()
        self.model = model or MODEL
        self.verifier = verifier
        self.config = types.GenerateContentConfig(
            system_instruction=INSTRUCTIONS,
            response_mime_type="application/json",
            response_schema=Advice,
            temperature=0.3,
        )

    def _generate(self, prompt):
        response = self.client.models.generate_content(model=self.model, contents=prompt, config=self.config)
        advice: Optional[Advice] = response.parsed
        if advice is None:
            raise RuntimeError("Advisor returned no structured answer")
        return advice

    def _verify(self, prompt, question, courses, advice):
        """Fact-check a draft and revise it once if problems are found."""
        highlights = [h.model_dump() for h in advice.highlighted_courses]
        try:
            verdict = self.verifier.check(question, courses, advice.answer, highlights)
        except Exception as e:
            # a failed check never blocks the answer
            return advice, {"model": self.verifier.name, "error": f"{type(e).__name__}: {str(e)[:200]}"}
        verification = {"model": self.verifier.name, "problems": verdict.problems, "revised": False}
        if not verdict.ok and verdict.problems:
            revision = (
                f"{prompt}\n\nYour previous answer was:\n{advice.model_dump_json()}\n\n"
                "A fact-check found these problems:\n- " + "\n- ".join(verdict.problems)
                + "\n\nRewrite the answer fixing them, keeping everything that was correct."
            )
            advice = self._generate(revision)
            verification["revised"] = True
        return advice, verification

    def answer(self, question, courses, conversation=()):
        """Answer a question about `courses`. Returns {answer, highlighted, verification}."""
        transcript = "\n".join(f"{turn['role']}: {turn['text']}" for turn in conversation)
        prompt = (
            f"Conversation so far:\n{transcript or '(none)'}\n\n"
            f"Data notes: {DATA_NOTES}\n"
            f"Courses currently shown ({len(courses)}):\n"
            f"{json.dumps([_course_context(c) for c in courses], ensure_ascii=False)}\n\n"
            f"Student question: {question}"
        )
        advice = self._generate(prompt)
        verification = None
        if self.verifier:
            advice, verification = self._verify(prompt, question, courses, advice)

        # Only courses from the current results can be highlighted
        by_code = {c["course_code"]: c for c in courses}
        highlighted = [
            {**by_code[h.course_code.strip().upper()], "reason": h.reason}
            for h in advice.highlighted_courses
            if h.course_code.strip().upper() in by_code
        ]
        return {"answer": advice.answer, "highlighted": highlighted, "verification": verification}
