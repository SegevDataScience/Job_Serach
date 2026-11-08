#!/usr/bin/env python3
"""
cover_letter.py — a short cover letter for one posting, from the master CV.

Same rule as tailor_resume.py: facts come from the CV only. The prompt says so,
and check_grounding() then lists every number in the letter that the CV does not
contain (a prompt is a request, not a guarantee). The letter is saved under
engine/cover_letters/ (git-ignored) and returned to the page.

Costs one Claude API call (~15 agorot) per letter; nothing runs unless the
button is clicked.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
OUT_DIR = ENGINE_DIR / "cover_letters"
MODEL = "claude-opus-5-5"

SYSTEM = """You write short cover letters for a job candidate, using only facts from the candidate's CV.

Rules:
- Every fact (employers, roles, years, tools, numbers, achievements) must come from the CV. Never add a tool, number, \
title or achievement the CV does not state. If the posting asks for something the CV does not show, do not claim it; \
you may mention a closely related skill the CV does show.
- Write in the posting's language: Hebrew if the posting is mainly Hebrew, otherwise English.
- 150-230 words, three or four short paragraphs, plain text, no headings, no bullet lists, no placeholders like [Company].
- Open with the role and why this candidate fits it, connect two or three CV achievements to the posting's main \
requirements, close with one sentence asking for a conversation. Sign with the candidate's name from the CV.
- Do not mention salary, notice period, or how long the candidate has been in the current role.
Output only the letter."""


def _client():
    import anthropic
    from dotenv import load_dotenv

    load_dotenv(ENGINE_DIR.parent / ".env")
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY") or None)


def generate(job: dict, description: str) -> dict:
    """{"text", "unsupported": [numbers not in the CV], "path"}"""
    import anthropic

    import skill_match
    from tailor_resume import check_grounding

    cv = skill_match.cv_text()
    prompt = (f"<cv>\n{cv}\n</cv>\n\n<posting>\nCompany: {job.get('company', '')}\nRole: {job.get('title', '')}\n"
              f"Location: {job.get('location', '')}\n\n{description[:15000]}\n</posting>\n\n"
              "Write the cover letter for this posting.")
    try:
        response = _client().beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            output_config={"effort": "medium"},
            # On a safety decline the API re-runs the request on a fallback model inside the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError:
        raise RuntimeError("מפתח ה-API לא תקין (ANTHROPIC_API_KEY ב-.env).") from None
    except anthropic.RateLimitError:
        raise RuntimeError("יותר מדי בקשות ל-API כרגע. נסה שוב בעוד דקה.") from None
    except anthropic.APIConnectionError:
        raise RuntimeError("אין חיבור ל-API של Anthropic.") from None
    except anthropic.APIStatusError as exc:
        if "credit balance" in str(exc.message).lower():
            raise RuntimeError("אין יתרה בחשבון ה-API של Anthropic. טען קרדיט ב-console.anthropic.com ← Plans & Billing ונסה שוב.") from None
        raise RuntimeError(f"שגיאת API ({exc.status_code}): {exc.message}") from None
    if response.stop_reason == "refusal":
        raise RuntimeError("המודל סירב לכתוב את המכתב הזה.")
    text = "\n".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise RuntimeError("לא התקבל טקסט מהמודל.")

    OUT_DIR.mkdir(exist_ok=True)
    name = re.sub(r"[^\w֐-׿]+", "_", f"{job.get('company', '')}__{job.get('title', '')}")[:90].strip("_")
    path = OUT_DIR / f"{date.today().isoformat()}__{name}.txt"
    path.write_text(text, encoding="utf-8")
    return {"text": text, "unsupported": check_grounding(text, cv), "path": str(path)}
