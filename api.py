from collections import OrderedDict
from typing import Optional
from fastapi import FastAPI
from pydantic import BaseModel
from data_setup import setup_database
from orchestrator import Orchestrator, Session
from nlp_engine import extract_intent
from query_engine import build_safe_query, execute_query
import os
import json
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

class CourseRequest(BaseModel):
    user_input: str

@app.post("/recommend")
def recommend_course(request: CourseRequest):
    print(f"[FastAPI] Received request body: {request}")
    print("[FastAPI] /recommend endpoint triggered.")
    setup_database()
    user_input = request.user_input
    print(f"[FastAPI] Received user_input: {user_input}")
    intent = extract_intent(user_input)
    print(f"[FastAPI] Extracted intent: {intent}")
    if not intent:
        print("[FastAPI] Could not understand request.")
        return {"error": "Could not understand request."}
    query, params = build_safe_query(intent)
    print(f"[FastAPI] Generated SQL: {query}")
    print(f"[FastAPI] SQL params: {params}")
    results = execute_query(query, params)
    print(f"[FastAPI] Query results: {results}")
    output_data = {
        "query": user_input,
        "intent": intent,
        "sql": query,
        "params": params,
        "results": results,
        "timestamp": datetime.now().isoformat()
    }
    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)
    filepath = os.path.join(RESULTS_DIR, "course_results.json")
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=4, ensure_ascii=False)
    print(f"[FastAPI] Results written to {filepath}")
    return output_data


MAX_SESSIONS = 200
sessions = OrderedDict()
orchestrator = None


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


@app.post("/chat")
def chat(request: ChatRequest):
    global orchestrator
    if orchestrator is None:
        orchestrator = Orchestrator()
    session = sessions.get(request.session_id) or Session()
    sessions[session.id] = session
    sessions.move_to_end(session.id)
    while len(sessions) > MAX_SESSIONS:
        sessions.popitem(last=False)
    try:
        result = orchestrator.handle(session, request.message)
    except Exception as e:
        print(f"[chat] {type(e).__name__}: {e}")
        return {"session_id": session.id, "error": "Something went wrong. Please try again."}
    return {"session_id": session.id, **result}
