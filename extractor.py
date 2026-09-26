"""Extracts a structured course record from a course page, validates it and
asks the model to fix any problems."""
import re
from typing import Optional

from google.genai import types
from pydantic import BaseModel, Field

from llm import MODEL, make_client


MAX_FIX_ATTEMPTS = 2
VALID_PERIODS = {"P1", "P2", "P3", "P4"}
VALID_GRADING = {"A-F", "P/F"}
EXAM_CODE = re.compile(r"^[A-ZÅÄÖ]{2}[A-ZÅÄÖ0-9]{1,3}$")  # e.g. LABA, TEN1, ÖVN1, PR01

INSTRUCTIONS = """
You extract structured data from a university course web page.

Rules:
- Use only information on the page. If a field is not on the page, use null
  (or an empty list). Never guess or invent.
- course_name: the name only, without the course code or credits.
- credits: the course's total credits as a number (e.g. 7.5).
- periods: every study period (P1, P2, P3, P4) the course is offered in, across
  all offerings listed on the page.
- terms: the offerings listed, e.g. ["Autumn 2026", "Spring 2027"].
- description: the course contents, as written on the page.
- learning_outcomes: the intended learning outcomes, as written on the page.
- grading_scale and each examination module's grading_scale: "A-F" for letter
  grades (A, B, C, D, E, FX, F) or "P/F" for pass/fail (P, F).
- examination: one entry per examination module, e.g. "LABA - Laboratory work,
  3.0 credits, grading scale: P, F" -> code LABA, kind "Laboratory work",
  credits 3.0, grading_scale "P/F".
- programmes: the programmes listed under "Part of programme", as written.
"""


class ExamModule(BaseModel):
    code: str = Field(description="Module code, e.g. LABA, PRO1, TEN1")
    kind: str = Field(description="What the module is, e.g. 'Laboratory work', 'Written exam'")
    credits: Optional[float]
    grading_scale: Optional[str] = Field(description='"A-F" or "P/F"')


class CourseRecord(BaseModel):
    course_code: str
    course_name: str
    credits: Optional[float]
    education_cycle: Optional[str] = Field(description='e.g. "Second cycle"')
    periods: list[str] = Field(description="Subset of P1, P2, P3, P4")
    terms: list[str]
    language: Optional[str]
    description: str
    learning_outcomes: str
    prerequisites: Optional[str] = Field(description="Specific prerequisites")
    recommended_prerequisites: Optional[str]
    grading_scale: Optional[str] = Field(description='"A-F" or "P/F"')
    examination: list[ExamModule]
    programmes: list[str]
    main_field: Optional[str] = Field(description="Main field of study")
    offered_by: Optional[str] = Field(description="Department offering the course")
    supplementary_info: Optional[str]


def mentions_period(page_text, period):
    """Whether a page states a period, as "P2" or in words ("given in period 2")."""
    number = period[1]
    return bool(re.search(rf"\bP{number}\b|\bperiod\s+{number}\b", page_text, re.IGNORECASE))


def validate(record, expected_code, page_text=None):
    """Return a list of problems with an extracted record (empty if valid)."""
    errors = []
    if record.course_code.strip().upper() != expected_code:
        errors.append(f"course_code is {record.course_code!r}, but the page is for {expected_code}")
    if not record.course_name.strip() or expected_code in record.course_name:
        errors.append("course_name must be the name only, without the course code")
    if record.credits is not None and not 0 < record.credits <= 60:
        errors.append(f"credits {record.credits} is not a plausible course size")
    invalid_periods = [p for p in record.periods if p not in VALID_PERIODS]
    if invalid_periods:
        errors.append(f"periods {invalid_periods} are not among P1, P2, P3, P4")
    if page_text is not None:
        unseen = [p for p in record.periods if p in VALID_PERIODS and not mentions_period(page_text, p)]
        if unseen:
            errors.append(f"periods {unseen} do not appear on the page; list only periods the page shows")
    if record.grading_scale is not None and record.grading_scale not in VALID_GRADING:
        errors.append(f'grading_scale {record.grading_scale!r} must be "A-F" or "P/F"')
    for module in record.examination:
        if not EXAM_CODE.match(module.code):
            errors.append(f"examination code {module.code!r} does not look like a module code")
        if module.grading_scale is not None and module.grading_scale not in VALID_GRADING:
            errors.append(f'{module.code} grading_scale {module.grading_scale!r} must be "A-F" or "P/F"')
    module_credits = [m.credits for m in record.examination]
    if record.credits and module_credits and None not in module_credits:
        if abs(sum(module_credits) - record.credits) > 0.1:
            errors.append(
                f"examination module credits add up to {sum(module_credits)}, "
                f"but the course has {record.credits} credits"
            )
    if not record.description.strip():
        errors.append("description is empty")
    if not record.learning_outcomes.strip():
        errors.append("learning_outcomes is empty")
    return errors


class Extractor:

    def __init__(self, model=None, client=None):
        self.model = model or MODEL
        self.client = client or make_client()
        self.config = types.GenerateContentConfig(
            system_instruction=INSTRUCTIONS,
            response_mime_type="application/json",
            response_schema=CourseRecord,
            temperature=0,
        )
        self.input_tokens = 0
        self.output_tokens = 0

    def _parse(self, conversation):
        response = self.client.models.generate_content(
            model=self.model, contents=conversation, config=self.config
        )
        usage = response.usage_metadata
        if usage:
            self.input_tokens += usage.prompt_token_count or 0
            # thinking tokens are billed as output
            self.output_tokens += (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
        return response.parsed, response.text

    def extract(self, page_text, course_code, url):
        """Extract one course. Returns (record, errors); errors are empty when valid."""
        conversation = [types.Content(role="user", parts=[types.Part.from_text(
            text=f"Course page for {course_code} ({url}):\n\n{page_text}"
        )])]
        record, errors = None, ["the model returned no structured output"]
        for _ in range(1 + MAX_FIX_ATTEMPTS):
            record, raw = self._parse(conversation)
            errors = validate(record, course_code, page_text) if record else ["the model returned no structured output"]
            if not errors:
                return record, []
            conversation += [
                types.Content(role="model", parts=[types.Part.from_text(text=raw or "(no output)")]),
                types.Content(role="user", parts=[types.Part.from_text(text=(
                    "These problems were found in your record. Re-read the page and return a "
                    "corrected record; use null where the page has no information:\n- "
                    + "\n- ".join(errors)
                ))]),
            ]
        return record, errors
