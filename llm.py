"""Gemini client shared by the scraper and the agents."""
import os

from google.genai import Client, types


MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def make_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return Client(
        api_key=api_key,
        http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(
            attempts=5, http_status_codes=[429, 500, 503, 504],
        )),
    )
