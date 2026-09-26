"""Routes each message to the retrieval agent, the advisor, or a direct reply.

    python orchestrator.py
"""
import uuid
from typing import Optional

from google.genai import types
from pydantic import BaseModel, Field

from advisor_agent import AdvisorAgent
from llm import MODEL, make_client
from retrieval_agent import RetrievalAgent
from verifier import make_verifier


ROUTES = {"search", "refine", "advise", "reply"}
HISTORY_TURNS = 10  # recent messages the router sees

ROUTER_INSTRUCTIONS = """
You route messages in a KTH master's course recommendation chat. Choose one route:

- "search": the student wants courses matching new criteria. Put a complete,
  standalone description of what to find in `request`.
- "refine": the student wants to narrow, widen or re-sort the courses currently
  shown (e.g. "only the ones in P2", "without exams", "sort by rating"). Put the
  change in `request`; the previous search is reused.
- "advise": the student asks about, compares, or wants a recommendation among the
  courses currently shown (e.g. "which is easiest?", "tell me about the second one").
  Put the question in `request`.
- "reply": greetings, thanks, off-topic messages, or requests too vague to search
  (then ask one clarifying question). Put your short reply in `reply`.

Use "refine" or "advise" only when courses are currently shown.
"""


class Route(BaseModel):
    route: str = Field(description='One of "search", "refine", "advise", "reply"')
    request: Optional[str] = Field(description="For search/refine/advise: what to do")
    reply: Optional[str] = Field(description="For reply: the message to the student")


class Session:
    def __init__(self):
        self.id = uuid.uuid4().hex
        self.history = []          # [{"role": "student" | "advisor", "text": ...}]
        self.search = None         # last retrieval result: {sql, summary, total, courses}


class Orchestrator:

    def __init__(self, client=None, model=None, verify=True):
        client = client or make_client()
        self.client = client
        self.model = model or MODEL
        self.retrieval = RetrievalAgent(client=client, model=model)
        self.advisor = AdvisorAgent(client=client, model=model, verifier=make_verifier() if verify else None)
        self.router_config = types.GenerateContentConfig(
            system_instruction=ROUTER_INSTRUCTIONS,
            response_mime_type="application/json",
            response_schema=Route,
            temperature=0,
        )

    def route(self, session, message):
        transcript = "\n".join(f"{t['role']}: {t['text']}" for t in session.history[-HISTORY_TURNS:])
        shown = (f"{session.search['total']} courses shown, from: {session.search['summary']}"
                 if session.search else "No courses shown yet.")
        prompt = f"Conversation:\n{transcript or '(none)'}\n\nCurrent results: {shown}\n\nNew message: {message}"
        response = self.client.models.generate_content(model=self.model, contents=prompt, config=self.router_config)
        decision = response.parsed
        if decision is None or decision.route not in ROUTES:
            return Route(route="search", request=message, reply=None)
        if decision.route in ("refine", "advise") and not session.search:
            decision.route = "search"  # nothing shown yet to refine or advise on
        decision.request = decision.request or message
        return decision

    def handle(self, session, message):
        """Process one student message. Returns what the UI should display."""
        decision = self.route(session, message)
        result = {"route": decision.route, "request": decision.request, "message": "", "courses": None,
                  "highlighted": [], "search": None, "verification": None}

        if decision.route == "reply":
            result["message"] = decision.reply or "Could you tell me a bit more about what you are looking for?"
        elif decision.route in ("search", "refine"):
            previous_sql = session.search["sql"] if decision.route == "refine" else None
            session.search = self.retrieval.run(decision.request, previous_sql=previous_sql)
            result["message"] = f"{session.search['summary']} ({session.search['total']} courses)"
            result["courses"] = session.search["courses"]
            result["search"] = {k: session.search[k] for k in ("sql", "summary", "total", "steps")}
        else:  # advise
            advice = self.advisor.answer(decision.request, session.search["courses"], session.history)
            result["message"] = advice["answer"]
            result["highlighted"] = advice["highlighted"]
            result["verification"] = advice["verification"]

        session.history += [{"role": "student", "text": message}, {"role": "advisor", "text": result["message"]}]
        return result


def main():
    orchestrator, session = Orchestrator(), Session()
    print("\n KTH course advisor. Type 'exit' to quit, 'new' to start over.\n")
    while True:
        message = input("You: ").strip()
        if message.lower() == "exit":
            break
        if message.lower() == "new":
            session = Session()
            continue
        if not message:
            continue
        result = orchestrator.handle(session, message)
        print(f"\n[{result['route']}] {result['message']}")
        if result["search"]:
            print(f"  SQL: {' '.join(result['search']['sql'].split())}")
        for course in result["courses"] or []:
            print(f"  {course['course_code']} {course['course_name']} ({course['credits']} cr, "
                  f"{course['periods'] or 'no period'})")
        for course in result["highlighted"]:
            print(f"  * {course['course_code']} {course['course_name']}: {course['reason']}")
        print()


if __name__ == "__main__":
    main()
