#!/usr/bin/env python3
"""
tailor_resume.py — tailor a resume to a specific job description using the
Claude API, and keep a persistent learning profile that improves every run.

Pipeline
--------
    my master CV (.pdf/.docx) ┐
    candidate_memory.json    ─┼──►  Claude  ──►  { markdown, match report, new memory }
    job_description.txt      ─┘                        │
                                                       ├──►  tailored_resume.docx
                                                       ├──►  tailored_resume.pdf
                                                       └──►  candidate_memory.json  (updated)

Run `python tailor_resume.py --help` for options.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

# --------------------------------------------------------------------------
# Third-party imports, with a friendly message if the venv isn't set up yet.
# --------------------------------------------------------------------------
try:
    import anthropic
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.opc.constants import RELATIONSHIP_TYPE as DOCX_REL
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor
    from dotenv import load_dotenv
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
    sys.stderr.write(
        f"Missing dependency: {exc.name}\n"
        "Install the requirements first:\n"
        "    python -m venv .venv\n"
        "    .venv\\Scripts\\activate      (Windows)\n"
        "    source .venv/bin/activate     (macOS/Linux)\n"
        "    pip install -r requirements.txt\n"
    )
    raise SystemExit(1)


from master_cv import master_files, resolve_master_path  # noqa: E402,F401  (re-exported)

# engine/ holds the code and its state; the folder above it is what the user sees.
ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENGINE_DIR.parent

# `claude-3-5-sonnet` was retired in Feb 2026. claude-sonnet-5 is its
# successor; claude-opus-5 is the higher-quality (and pricier) option.
DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_EFFORT = "high"
MAX_TOKENS = 32_000

log = logging.getLogger("tailor")


# ==========================================================================
# 1. Persistent learning memory
# ==========================================================================

MEMORY_SCHEMA_VERSION = 1


def _str_array(description: str) -> dict[str, Any]:
    return {"type": "array", "description": description, "items": {"type": "string"}}


def _obj(properties: dict[str, Any], description: str = "") -> dict[str, Any]:
    """Build a strict-mode-compatible JSON Schema object."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
    if description:
        schema["description"] = description
    return schema


CANDIDATE_PROFILE_SCHEMA = _obj(
    {
        "full_name": {"type": "string"},
        "headline": {
            "type": "string",
            "description": "Short professional title, e.g. 'Data Analyst | SQL, Python, BI'.",
        },
        "location": {"type": "string"},
        "email": {"type": "string"},
        "phone": {"type": "string"},
        "links": _str_array("LinkedIn / GitHub / portfolio URLs."),
        "core_skills": _str_array("Analytical and business skills the resume can support."),
        "tools_and_tech": _str_array("Concrete tools: SQL, Python, dbt, Tableau, Snowflake, ..."),
        "domains": _str_array("Industries / problem domains worked in."),
        "education": _str_array("Degrees, one per entry."),
        "certifications": _str_array("Certifications, one per entry."),
    },
    "Stable facts about the candidate. Only ever add facts present in the original resume.",
)

ACHIEVEMENT_SCHEMA = _obj(
    {
        "statement": {"type": "string", "description": "A polished, reusable bullet."},
        "metric": {"type": "string", "description": "The quantified result, or '' if none exists."},
        "source_role": {"type": "string", "description": "Which job on the resume it came from."},
        "skills": _str_array("Skills this achievement demonstrates."),
    }
)

METRIC_SCHEMA = _obj(
    {
        "label": {"type": "string"},
        "value": {"type": "string"},
        "context": {"type": "string", "description": "One sentence on what the number means."},
    }
)

KEYWORD_SCHEMA = _obj(
    {
        "keyword": {"type": "string"},
        "count": {"type": "integer", "description": "How many job descriptions have asked for it."},
        "last_seen": {"type": "string", "description": "ISO date, YYYY-MM-DD."},
    }
)

STRATEGY_SCHEMA = _obj(
    {
        "pattern": {"type": "string", "description": "A phrasing pattern that worked well."},
        "rationale": {"type": "string"},
        "example": {"type": "string"},
    }
)

APPLICATION_SCHEMA = _obj(
    {
        "date": {"type": "string", "description": "ISO date, YYYY-MM-DD."},
        "company": {"type": "string"},
        "role": {"type": "string"},
        "top_keywords": _str_array("The most important keywords from that posting."),
        "tailoring_notes": {"type": "string", "description": "What was emphasised and why."},
    }
)

MEMORY_SCHEMA = _obj(
    {
        "schema_version": {"type": "integer"},
        "candidate_profile": CANDIDATE_PROFILE_SCHEMA,
        "verified_achievements": {
            "type": "array",
            "description": "Reusable bullets grounded in the original resume. Max 30, best first.",
            "items": ACHIEVEMENT_SCHEMA,
        },
        "key_metrics": {
            "type": "array",
            "description": "Headline numbers worth reusing. Max 20.",
            "items": METRIC_SCHEMA,
        },
        "keyword_frequency": {
            "type": "array",
            "description": "Recurring keywords across all job descriptions seen. Max 60, highest count first.",
            "items": KEYWORD_SCHEMA,
        },
        "phrasing_strategies": {
            "type": "array",
            "description": "Writing patterns that consistently produce strong bullets. Max 15.",
            "items": STRATEGY_SCHEMA,
        },
        "job_application_history": {
            "type": "array",
            "description": "One entry per run, oldest first. Max 40 — drop the oldest when full.",
            "items": APPLICATION_SCHEMA,
        },
        "open_questions": _str_array(
            "Gaps worth asking the candidate about, e.g. 'No metric for the churn project'. Max 10."
        ),
        "run_count": {"type": "integer"},
        "last_updated": {"type": "string", "description": "ISO-8601 timestamp."},
    }
)

RESPONSE_SCHEMA = _obj(
    {
        "tailored_resume_markdown": {
            "type": "string",
            "description": (
                "The complete tailored resume in Markdown. Use '# Name' once, a plain "
                "line for contact details, '## SECTION' for sections, '### Title — Company | Dates' "
                "for roles, and '- ' bullets. No code fences, no commentary."
            ),
        },
        "match_report": _obj(
            {
                "overall_fit": {"type": "string", "description": "2-3 sentences on fit."},
                "strengths": _str_array("Where the candidate maps strongly onto the posting."),
                "gaps": _str_array("Requirements the resume cannot honestly support."),
                "keywords_injected": _str_array("Job-description keywords now present in the resume."),
            }
        ),
        "updated_memory": MEMORY_SCHEMA,
    }
)


def default_memory() -> dict[str, Any]:
    """The baseline learning profile written on the very first run."""
    return {
        "schema_version": MEMORY_SCHEMA_VERSION,
        "candidate_profile": {
            "full_name": "",
            "headline": "",
            "location": "",
            "email": "",
            "phone": "",
            "links": [],
            "core_skills": [],
            "tools_and_tech": [],
            "domains": [],
            "education": [],
            "certifications": [],
        },
        "verified_achievements": [],
        "key_metrics": [],
        "keyword_frequency": [],
        "phrasing_strategies": [],
        "job_application_history": [],
        "open_questions": [],
        "run_count": 0,
        "last_updated": "",
    }


def load_memory(path: Path) -> dict[str, Any]:
    """Load the learning profile, creating a baseline file if none exists."""
    if not path.exists():
        memory = default_memory()
        save_memory(path, memory, backup=False)
        log.info("No memory file found — created a baseline at %s", path.name)
        return memory

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"ERROR: {path} is not valid JSON ({exc}).\n"
            f"       Fix it, or delete it to start from a fresh baseline."
        ) from exc

    if not isinstance(raw, dict):
        raise SystemExit(f"ERROR: {path} must contain a JSON object.")

    # Forward-compatible merge: unknown keys are dropped, missing keys get defaults.
    memory = default_memory()
    memory.update({k: v for k, v in raw.items() if k in memory})

    profile = default_memory()["candidate_profile"]
    if isinstance(raw.get("candidate_profile"), dict):
        profile.update({k: v for k, v in raw["candidate_profile"].items() if k in profile})
    memory["candidate_profile"] = profile

    log.info(
        "Loaded memory: run #%s, %s achievements, %s tracked keywords, %s past applications",
        memory.get("run_count", 0),
        len(memory.get("verified_achievements", [])),
        len(memory.get("keyword_frequency", [])),
        len(memory.get("job_application_history", [])),
    )
    return memory


def save_memory(path: Path, memory: dict[str, Any], *, backup: bool = True) -> None:
    """Write the learning profile atomically, keeping one .bak of the old copy."""
    if backup and path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(memory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def normalise_updated_memory(
    previous: dict[str, Any], updated: dict[str, Any], jd_meta: "JobMeta"
) -> dict[str, Any]:
    """Apply the bookkeeping fields the script owns rather than the model."""
    memory = default_memory()
    memory.update({k: v for k, v in updated.items() if k in memory})

    memory["schema_version"] = MEMORY_SCHEMA_VERSION
    memory["run_count"] = int(previous.get("run_count", 0)) + 1
    memory["last_updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Guarantee this run is recorded even if the model forgot to append it.
    history = memory.get("job_application_history") or []
    today = date.today().isoformat()
    already_logged = any(
        entry.get("date") == today
        and entry.get("company", "").lower() == jd_meta.company.lower()
        and entry.get("role", "").lower() == jd_meta.role.lower()
        for entry in history
        if isinstance(entry, dict)
    )
    if not already_logged:
        history.append(
            {
                "date": today,
                "company": jd_meta.company or "Unknown",
                "role": jd_meta.role or "Unknown",
                "top_keywords": [],
                "tailoring_notes": "Auto-logged by tailor_resume.py.",
            }
        )
    memory["job_application_history"] = history[-40:]

    # Keep the file from growing without bound.
    memory["verified_achievements"] = memory["verified_achievements"][:30]
    memory["key_metrics"] = memory["key_metrics"][:20]
    memory["keyword_frequency"] = sorted(
        memory["keyword_frequency"],
        key=lambda k: k.get("count", 0) if isinstance(k, dict) else 0,
        reverse=True,
    )[:60]
    memory["phrasing_strategies"] = memory["phrasing_strategies"][:15]
    memory["open_questions"] = memory["open_questions"][:10]
    return memory


# ==========================================================================
# 2. Input readers
# ==========================================================================


def read_docx_text(path: Path) -> str:
    """Extract readable text from a .docx, including text inside tables."""
    if not path.exists():
        raise SystemExit(
            f"ERROR: resume not found at {path}\n"
            f"       Put your resume there, or pass --resume <path>."
        )
    if path.suffix.lower() != ".docx":
        raise SystemExit(
            f"ERROR: {path.name} is not a .docx file. Legacy .doc is not supported — "
            f"open it in Word and 'Save As' .docx."
        )

    try:
        document = Document(str(path))
    except Exception as exc:  # python-docx raises a variety of types here
        raise SystemExit(f"ERROR: could not open {path.name}: {exc}") from exc

    lines: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            lines.append(text)

    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            cells = [c for c in cells if c]
            if cells:
                lines.append(" | ".join(dict.fromkeys(cells)))

    text = "\n".join(lines).strip()
    if not text:
        raise SystemExit(
            f"ERROR: no text found in {path.name}. If your resume is a scanned image "
            f"or lives entirely in text boxes, export a text version first."
        )

    log.info("Read resume: %s (%s characters)", path.name, len(text))
    return text


# Finding the master CV lives in master_cv.py; reading it lives here.


def clean_pdf_text(text: str) -> str:
    """Undo what justified PDF layout does to words on extraction."""
    text = text.replace("\u00a0", " ")
    # Justified text leaves a space before the hyphen: "high -performance",
    # and breaks a hyphenated word across two lines: "production -" / "ready".
    text = re.sub(r"(?<=[A-Za-z]) -(?=[A-Za-z])", "-", text)
    text = re.sub(r"(?<=[A-Za-z]) ?-[ \t]*\n[ \t]*(?=[a-z])", "-", text)
    lines = [re.sub(r"[ \t]{2,}", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def read_pdf_text(path: Path) -> str:
    """Extract readable text from a PDF CV."""
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError:
        raise SystemExit(
            "ERROR: reading a PDF CV needs pypdf. Install it with:\n"
            "       python -m pip install -r engine\requirements.txt"
        ) from None

    try:
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise SystemExit(f"ERROR: could not read {path.name}: {exc}") from exc

    text = clean_pdf_text("\n".join(pages))
    if not text:
        raise SystemExit(
            f"ERROR: no text found in {path.name}. A scanned or image-only PDF cannot be "
            f"read — point RESUME_INPUT at the .docx instead."
        )

    log.info("Read master CV: %s (%s characters, %s page(s))", path.name, len(text), len(reader.pages))
    return text


def read_master_text(path: Path) -> str:
    """Read the master CV, whatever format it is kept in."""
    path = resolve_master_path(path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return read_pdf_text(path)
    if suffix == ".docx":
        return read_docx_text(path)
    if suffix in (".md", ".txt"):
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            raise SystemExit(f"ERROR: {path.name} is empty.")
        log.info("Read master CV: %s (%s characters)", path.name, len(text))
        return text

    raise SystemExit(
        f"ERROR: cannot read {path.name} as a CV. Supported: .pdf, .docx, .md, .txt "
        f"(legacy .doc is not — open it in Word and 'Save As')."
    )


@dataclass
class JobMeta:
    company: str
    role: str


def read_job_description(path: Path) -> str:
    if not path.exists():
        raise SystemExit(
            f"ERROR: job description not found at {path}\n"
            f"       Paste the posting into that file, or pass --jd <path>."
        )
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) < 80:
        raise SystemExit(
            f"ERROR: {path.name} looks empty ({len(text)} characters). "
            f"Paste the full job posting into it."
        )
    log.info("Read job description: %s (%s characters)", path.name, len(text))
    return text


def guess_job_meta(job_description: str, company: str | None, role: str | None) -> JobMeta:
    """Best-effort company/role extraction, used only for filenames and logging."""
    if company and role:
        return JobMeta(company.strip(), role.strip())

    head = [line.strip() for line in job_description.splitlines()[:15] if line.strip()]

    def find(patterns: Sequence[str]) -> str:
        for line in head:
            for pattern in patterns:
                match = re.search(pattern, line, flags=re.IGNORECASE)
                if match:
                    return match.group(1).strip(" -–—:•")
        return ""

    guessed_company = company or find([r"^company\s*[:\-]\s*(.+)$", r"\bat\s+([A-Z][\w&.\- ]{2,40})$"])
    guessed_role = role or find(
        [r"^(?:job\s*)?title\s*[:\-]\s*(.+)$", r"^position\s*[:\-]\s*(.+)$"]
    )
    if not guessed_role and head:
        guessed_role = head[0][:80]

    return JobMeta(guessed_company or "Unknown", guessed_role or "Unknown")


# ==========================================================================
# 3. Claude API integration
# ==========================================================================

SYSTEM_PROMPT = """\
You are an expert resume writer and ATS strategist who specialises in Data \
Analytics, Data Science, Analytics Engineering, and adjacent technical roles.

Your job each run has two halves.

## A. Tailor the resume

Rewrite the candidate's resume so it targets the supplied job description as \
closely as the underlying facts allow.

Hard rules — these override everything else:
- The ORIGINAL RESUME supplied in this run is the only source of facts. Never state \
  an employer, job title, date, degree, certification, tool, scale, or metric that is \
  not in it.
- The persistent memory is for wording, keyword coverage and consistency ONLY. It is \
  NOT a source of facts. It accumulates across runs and can therefore describe an \
  older version of the resume: if memory says something the current resume no longer \
  says, LEAVE IT OUT. When memory and the resume disagree, the resume wins.
- Never inflate a number, and never carry a number over from memory that is absent \
  from the current resume. If a bullet has no metric, write it without one rather \
  than guessing.
- You may rewrite, reorder, merge, compress, or drop existing content, and you may \
  surface a skill that is implied by the original resume. You may not add new facts.
- If the posting requires something the candidate genuinely lacks, leave it out of \
  the resume and record it in match_report.gaps.

Craft guidance:
- Mirror the posting's own vocabulary where it is truthful (a posting saying \
  "experimentation" should not be answered with "A/B testing" alone — use both).
- Lead every bullet with a strong past-tense verb, then the action, then the \
  outcome. Prefer "Verb + what + tool + measurable result".
- Order sections and bullets so the most relevant evidence appears first.
- Keep it to one page of content unless the candidate clearly has 10+ years of \
  experience, in which case two pages.
- Plain formatting only — no tables, columns, graphics, or emoji. ATS parsers choke \
  on them.

Markdown contract for `tailored_resume_markdown`:
- Exactly one `# Full Name` at the top.
- The next line is the contact details separated by ` | `.
- PRESERVE EVERY LINK from the original resume, verbatim, in Markdown link form:
  `[LinkedIn](https://www.linkedin.com/in/...)`. Links are how a recruiter reaches
  the candidate's profile and portfolio — dropping one is a real loss. Keep them on
  the contact line, keep their URLs byte-identical, and never invent a URL that was
  not in the original. Links elsewhere in the resume (a project, a publication) must
  survive too.
- `## SECTION NAME` for each section (SUMMARY, SKILLS, EXPERIENCE, PROJECTS, \
  EDUCATION, CERTIFICATIONS...).
- `### Job Title — Company | Location | Start – End` for each role.
- `- ` for bullets. `**bold**` is allowed inline. Nothing else.
- No code fences, no preamble, no closing commentary.

## B. Update the persistent memory

You are given the memory from previous runs. Return the COMPLETE updated memory \
object — it replaces the old file wholesale, so carry forward everything still \
true. Never delete a verified achievement just because it was irrelevant to this \
posting.

Specifically:
- `candidate_profile`: fill in or correct from the original resume. Facts only.
- `verified_achievements`: add any strong, reusable, resume-grounded bullet you \
  produced this run. Deduplicate against what is already there. Keep the best 30.
- `key_metrics`: the candidate's headline numbers, so future runs reuse them \
  consistently instead of re-deriving them.
- `keyword_frequency`: merge this posting's important keywords in. Increment `count` \
  for keywords already present, add new ones with count 1, and set `last_seen` to \
  today's date. Keep the top 60 by count.
- `phrasing_strategies`: record a pattern only when you can say why it worked. \
  Quality over quantity.
- `job_application_history`: append one entry for this run with today's date, the \
  company, the role, the posting's top keywords, and a one-line note on what you \
  emphasised.
- `open_questions`: things you'd need to ask the candidate to make the next resume \
  stronger — a missing metric, an ambiguous date, an unclear scope of ownership.

Consistency matters more than novelty: if memory already contains a polished \
version of a bullet, reuse that wording rather than inventing a new one.
"""


def build_user_prompt(
    *,
    resume_text: str,
    memory: dict[str, Any],
    job_description: str,
    jd_meta: JobMeta,
) -> str:
    memory_json = json.dumps(memory, indent=2, ensure_ascii=False)
    run_number = int(memory.get("run_count", 0)) + 1
    first_run_note = (
        "This is the FIRST run — the memory below is an empty baseline. Populate it "
        "thoroughly from the original resume."
        if run_number == 1
        else f"This is run #{run_number}. Build on the memory rather than restarting from it."
    )

    return f"""\
Today's date: {date.today().isoformat()}
Target: {jd_meta.role} at {jd_meta.company}
{first_run_note}

<original_resume>
{resume_text}
</original_resume>

<persistent_memory>
{memory_json}
</persistent_memory>

<job_description>
{job_description}
</job_description>

Produce the tailored resume, the match report, and the complete updated memory."""


def call_claude(
    *,
    client: "anthropic.Anthropic",
    model: str,
    effort: str,
    user_prompt: str,
) -> tuple[dict[str, Any], Any]:
    """Send the request and return (parsed payload, usage)."""
    log.info("Calling Claude (model=%s, effort=%s) — this usually takes 30-90s...", model, effort)

    try:
        with client.messages.stream(
            model=model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
            },
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            for _ in stream.text_stream:
                pass  # drain the stream; we only need the assembled message
            message = stream.get_final_message()
    except anthropic.AuthenticationError as exc:
        raise SystemExit(
            "ERROR: Anthropic rejected the API key. Check ANTHROPIC_API_KEY in your "
            f".env file.\n       ({exc})"
        ) from exc
    except anthropic.NotFoundError as exc:
        raise SystemExit(
            f"ERROR: model '{model}' was not found or is not available to this key.\n"
            f"       Try --model claude-sonnet-5 or --model claude-opus-5.\n       ({exc})"
        ) from exc
    except anthropic.RateLimitError as exc:
        raise SystemExit(f"ERROR: rate limited by the API. Wait a minute and retry.\n       ({exc})") from exc
    except anthropic.APIConnectionError as exc:
        raise SystemExit(f"ERROR: could not reach the Anthropic API — check your network.\n       ({exc})") from exc
    except anthropic.APIStatusError as exc:
        raise SystemExit(f"ERROR: API returned {exc.status_code}: {exc.message}") from exc

    if message.stop_reason == "refusal":
        raise SystemExit(
            "ERROR: the model declined this request. If your job description contains "
            "unusual content, try trimming it to the role requirements."
        )
    if message.stop_reason == "max_tokens":
        raise SystemExit(
            f"ERROR: response hit the {MAX_TOKENS:,} token ceiling and was cut off. "
            "Shorten the job description or the original resume and retry."
        )

    text = "".join(block.text for block in message.content if block.type == "text")
    if not text.strip():
        raise SystemExit("ERROR: the model returned an empty response. Retry.")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        debug = ENGINE_DIR / "last_response.debug.txt"
        debug.write_text(text, encoding="utf-8")
        raise SystemExit(
            f"ERROR: could not parse the model's JSON response ({exc}).\n"
            f"       Raw output saved to {debug.name} for inspection."
        ) from exc

    for key in ("tailored_resume_markdown", "match_report", "updated_memory"):
        if key not in payload:
            raise SystemExit(f"ERROR: model response is missing the '{key}' field.")

    return payload, message.usage


# ==========================================================================
# 4. Markdown parsing
# ==========================================================================


@dataclass
class Block:
    kind: str  # "h1" | "h2" | "h3" | "bullet" | "text" | "rule"
    text: str


_FENCE_RE = re.compile(r"^\s*```")
_BULLET_RE = re.compile(r"^\s*[-*+•]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.*)$")
_RULE_RE = re.compile(r"^\s*([-*_])\1{2,}\s*$")


def parse_markdown(markdown: str) -> list[Block]:
    """Turn the model's Markdown into a flat list of renderable blocks."""
    blocks: list[Block] = []
    in_fence = False

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()

        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            blocks.append(Block("text", line))
            continue
        if not line.strip():
            continue
        if _RULE_RE.match(line):
            blocks.append(Block("rule", ""))
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = min(len(heading.group(1)), 3)
            blocks.append(Block(f"h{level}", heading.group(2).strip()))
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            blocks.append(Block("bullet", bullet.group(1).strip()))
            continue

        numbered = _NUMBERED_RE.match(line)
        if numbered:
            blocks.append(Block("bullet", numbered.group(1).strip()))
            continue

        blocks.append(Block("text", line.strip().lstrip("> ").strip()))

    return blocks


_MD_LINK = r"\[[^\]\n]+\]\([^)\s]+\)"
_BARE_URL = r"https?://[^\s<>\]|]+"
_WWW_URL = r"www\.[^\s<>\]|]+"
_EMAIL = r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
# A domain with a path, e.g. linkedin.com/in/name — a dotted name alone (Node.js) won't match.
_DOMAIN_PATH = r"(?:[\w-]+\.)+[a-z]{2,}(?:\.[a-z]{2,})?/[^\s<>\]|]*"

_INLINE_RE = re.compile(
    "("
    + "|".join(
        [
            _MD_LINK,
            r"\*\*.+?\*\*",
            r"__.+?__",
            r"(?<!\*)\*(?!\*)[^*\n]+?\*(?!\*)",
            r"(?<!_)_(?!_)[^_\n]+?_(?!_)",
            r"`[^`\n]+?`",
            _BARE_URL,
            _WWW_URL,
            _EMAIL,
            _DOMAIN_PATH,
        ]
    )
    + ")",
    re.IGNORECASE,
)

_MD_LINK_RE = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")


def _as_url(token: str) -> str | None:
    """Turn a recognised token into an href, or None if it is not a link."""
    low = token.lower()
    if low.startswith(("http://", "https://")):
        return token
    if low.startswith("www."):
        return "https://" + token
    if re.fullmatch(_EMAIL, token, re.IGNORECASE):
        return "mailto:" + token
    if re.fullmatch(_DOMAIN_PATH, token, re.IGNORECASE):
        return "https://" + token
    return None


def split_inline(text: str) -> list[tuple[str, bool, bool, str | None]]:
    """Split text into (chunk, bold, italic, url) runs. url is None for plain text."""
    runs: list[tuple[str, bool, bool, str | None]] = []
    for part in _INLINE_RE.split(text):
        if not part:
            continue

        link = _MD_LINK_RE.fullmatch(part)
        if link:
            runs.append((link.group(1), False, False, link.group(2)))
            continue

        if (part.startswith("**") and part.endswith("**")) or (
            part.startswith("__") and part.endswith("__")
        ):
            runs.append((part[2:-2], True, False, None))
        elif part.startswith("`") and part.endswith("`"):
            runs.append((part[1:-1], False, False, None))
        elif len(part) > 2 and part[0] in "*_" and part[-1] == part[0]:
            runs.append((part[1:-1], False, True, None))
        else:
            runs.append((part, False, False, _as_url(part)))
    return runs or [(text, False, False, None)]


def strip_inline(text: str) -> str:
    """Plain text with all markup removed (link text kept, target dropped)."""
    return "".join(chunk for chunk, _, _, _ in split_inline(text))


def to_pdf_markdown(text: str) -> str:
    """Re-emit inline markup in the dialect fpdf2 understands.

    fpdf2 only linkifies an explicit [text](url), so bare emails and URLs have to be
    written out as one. It also reads `__x__` as italic where our parser reads it as
    bold, so normalise emphasis to `**bold**` / `__italic__` to keep the PDF and the
    .docx identical.
    """
    parts = []
    for chunk, bold, italic, url in split_inline(text):
        if url:
            parts.append(f"[{chunk}]({url})")
        elif bold:
            parts.append(f"**{chunk}**")
        elif italic:
            parts.append(f"__{chunk}__")
        else:
            parts.append(chunk)
    return "".join(parts)


# ==========================================================================
# 5. Word (.docx) generation
# ==========================================================================

ACCENT = RGBColor(0x1F, 0x36, 0x4D)
MUTED = RGBColor(0x55, 0x55, 0x55)


def _add_bottom_border(paragraph) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "2")
    bottom.set(qn("w:color"), "BFBFBF")
    borders.append(bottom)
    p_pr.append(borders)


LINK_BLUE = "0563C1"


def _add_hyperlink(paragraph, text: str, url: str, *, size: Pt, bold: bool, italic: bool) -> None:
    """A real, clickable w:hyperlink — python-docx has no public API for this."""
    r_id = paragraph.part.relate_to(url, DOCX_REL.HYPERLINK, is_external=True)

    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)

    run = OxmlElement("w:r")
    props = OxmlElement("w:rPr")

    fonts = OxmlElement("w:rFonts")
    fonts.set(qn("w:ascii"), "Calibri")
    fonts.set(qn("w:hAnsi"), "Calibri")
    props.append(fonts)

    if bold:
        props.append(OxmlElement("w:b"))
    if italic:
        props.append(OxmlElement("w:i"))

    color = OxmlElement("w:color")
    color.set(qn("w:val"), LINK_BLUE)
    props.append(color)

    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    props.append(underline)

    half_points = OxmlElement("w:sz")
    half_points.set(qn("w:val"), str(int(size.pt * 2)))
    props.append(half_points)

    run.append(props)

    node = OxmlElement("w:t")
    node.set(qn("xml:space"), "preserve")
    node.text = text
    run.append(node)

    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def _write_runs(paragraph, text: str, *, size: Pt, bold: bool = False, color=None) -> None:
    for chunk, is_bold, is_italic, url in split_inline(text):
        if url:
            _add_hyperlink(paragraph, chunk, url, size=size, bold=bold or is_bold, italic=is_italic)
            continue
        run = paragraph.add_run(chunk)
        run.bold = bold or is_bold
        run.italic = is_italic
        run.font.size = size
        run.font.name = "Calibri"
        if color is not None:
            run.font.color.rgb = color


def build_docx(blocks: list[Block], output_path: Path) -> None:
    document = Document()

    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)
    style.paragraph_format.space_after = Pt(0)
    style.paragraph_format.line_spacing = 1.06

    for section in document.sections:
        section.top_margin = Inches(0.55)
        section.bottom_margin = Inches(0.55)
        section.left_margin = Inches(0.65)
        section.right_margin = Inches(0.65)

    seen_h1 = False
    contact_pending = False

    for block in blocks:
        if block.kind == "h1":
            paragraph = document.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.space_after = Pt(2)
            _write_runs(paragraph, block.text, size=Pt(20), bold=True, color=ACCENT)
            seen_h1 = True
            contact_pending = True
            continue

        if block.kind == "text" and contact_pending:
            paragraph = document.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.space_after = Pt(8)
            _write_runs(paragraph, block.text, size=Pt(9), color=MUTED)
            contact_pending = False
            continue

        contact_pending = False

        if block.kind == "h2":
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_before = Pt(10)
            paragraph.paragraph_format.space_after = Pt(4)
            _write_runs(paragraph, block.text.upper(), size=Pt(11), bold=True, color=ACCENT)
            _add_bottom_border(paragraph)

        elif block.kind == "h3":
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_before = Pt(6)
            paragraph.paragraph_format.space_after = Pt(1)
            _write_runs(paragraph, block.text, size=Pt(10.5), bold=True)

        elif block.kind == "bullet":
            paragraph = document.add_paragraph(style="List Bullet")
            paragraph.paragraph_format.left_indent = Inches(0.22)
            paragraph.paragraph_format.first_line_indent = Inches(-0.14)
            paragraph.paragraph_format.space_after = Pt(2)
            _write_runs(paragraph, block.text, size=Pt(10))

        elif block.kind == "rule":
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_before = Pt(2)
            paragraph.paragraph_format.space_after = Pt(2)
            _add_bottom_border(paragraph)

        else:  # plain text
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(3)
            _write_runs(paragraph, block.text, size=Pt(10))

    if not seen_h1:
        log.warning("Resume markdown had no '# Name' heading — the header may look plain.")

    document.save(str(output_path))
    log.info("Wrote %s", output_path.name)


# ==========================================================================
# 6. PDF generation
# ==========================================================================

_TRANSLITERATE = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"',
    "\u2013": "-", "\u2014": "-", "\u2212": "-", "\u2010": "-", "\u2011": "-",
    "\u2022": "-", "\u00b7": "-", "\u25cf": "-", "\u25aa": "-",
    "\u2026": "...", "\u00a0": " ", "\u2192": "->", "\u2265": ">=", "\u2264": "<=",
    "\u00d7": "x", "\u2713": "v", "\u2714": "v",
}

# Candidate Unicode font families, in preference order: (regular, bold, italic)
_FONT_CANDIDATES: list[tuple[str, str, str]] = [
    (r"C:\Windows\Fonts\calibri.ttf", r"C:\Windows\Fonts\calibrib.ttf", r"C:\Windows\Fonts\calibrii.ttf"),
    (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\ariali.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf", "/Library/Fonts/Arial Italic.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf",
     "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
     "/System/Library/Fonts/Supplemental/Arial Italic.ttf"),
]


def _sanitise_latin1(text: str) -> str:
    """Make text safe for fpdf2's built-in (latin-1 only) core fonts."""
    text = "".join(_TRANSLITERATE.get(ch, ch) for ch in text)
    text = unicodedata.normalize("NFKD", text)
    return text.encode("latin-1", "ignore").decode("latin-1")


class ResumePDF(FPDF):
    """A4 resume renderer with automatic page breaks and a page footer."""

    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=14)
        self.set_margins(left=16, top=14, right=16)
        self.set_title("Tailored Resume")
        self.family = "helvetica"
        self.unicode_ok = False
        self._register_font()

    def _register_font(self) -> None:
        for regular, bold, italic in _FONT_CANDIDATES:
            if not Path(regular).exists():
                continue
            try:
                self.add_font("Resume", "", regular)
                if Path(bold).exists():
                    self.add_font("Resume", "B", bold)
                if Path(italic).exists():
                    self.add_font("Resume", "I", italic)
            except Exception as exc:  # unreadable/unsupported font file
                log.debug("Could not load font %s: %s", regular, exc)
                continue
            self.family = "Resume"
            self.unicode_ok = True
            log.debug("PDF using Unicode font %s", regular)
            return
        log.warning(
            "No embeddable Unicode font found — falling back to Helvetica. "
            "Special characters will be transliterated to ASCII."
        )

    # -- helpers ----------------------------------------------------------
    def prepare(self, text: str) -> str:
        return text if self.unicode_ok else _sanitise_latin1(text)

    def footer(self) -> None:
        if self.page_no() < 2:  # keep a one-page resume clean
            return
        self.set_y(-12)
        self.set_font(self.family, "", 7.5)
        self.set_text_color(140, 140, 140)
        self.cell(0, 6, f"Page {self.page_no()} of {{nb}}", align="C")

    def para(
        self,
        text: str,
        *,
        size: float,
        style: str = "",
        align: str = "L",
        color: tuple[int, int, int] = (25, 25, 25),
        space_before: float = 0.0,
        space_after: float = 1.2,
        indent: float = 0.0,
        markdown: bool = True,
    ) -> None:
        if space_before:
            self.ln(space_before)
        self.set_font(self.family, style, size)
        self.set_text_color(*color)
        left = self.l_margin + indent
        self.set_x(left)

        # fpdf2's markdown mode renders [text](url) as a real /URI annotation, but only
        # when the link is written out explicitly. With markdown off, flatten instead.
        use_markdown = markdown and self.unicode_ok
        body = to_pdf_markdown(text) if use_markdown else strip_inline(text)

        self.multi_cell(
            w=self.w - self.r_margin - left,
            h=size * 0.52,
            text=self.prepare(body),
            align=align,
            markdown=use_markdown,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        if space_after:
            self.ln(space_after)

    def rule(self, color: tuple[int, int, int] = (191, 191, 191)) -> None:
        self.set_draw_color(*color)
        self.set_line_width(0.25)
        y = self.get_y() + 0.6
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.ln(2.2)


def build_pdf(blocks: list[Block], output_path: Path) -> None:
    pdf = ResumePDF()
    pdf.add_page()

    contact_pending = False
    for block in blocks:
        if block.kind == "h1":
            pdf.para(block.text, size=19, style="B", align="C", color=(31, 54, 77),
                     space_after=0.6, markdown=False)
            contact_pending = True
            continue

        if block.kind == "text" and contact_pending:
            # markdown=True so the contact line's links stay clickable
            pdf.para(block.text, size=8.5, align="C", color=(85, 85, 85), space_after=2.6)
            contact_pending = False
            continue

        contact_pending = False

        if block.kind == "h2":
            pdf.para(block.text.upper(), size=10.5, style="B", color=(31, 54, 77),
                     space_before=2.4, space_after=0.4, markdown=False)
            pdf.rule()

        elif block.kind == "h3":
            pdf.para(block.text, size=10, style="B", space_before=1.4, space_after=0.4)

        elif block.kind == "bullet":
            pdf.para(f"\u2022  {block.text}" if pdf.unicode_ok else f"-  {block.text}",
                     size=9.5, indent=3.5, space_after=0.9)

        elif block.kind == "rule":
            pdf.rule()

        else:
            pdf.para(block.text, size=9.5, space_after=1.4)

    pdf.output(str(output_path))
    log.info("Wrote %s", output_path.name)


# ==========================================================================
# 7. CLI
# ==========================================================================


SCALE_WORDS = ("thousand", "thousands", "million", "millions", "billion", "billions", "trillion", "trillions")


def _strip_contact_lines(text: str) -> str:
    """Drop the contact line. A phone number is not a claim about your career,
    and it is written differently on every version of a CV."""
    kept = []
    for line in text.splitlines():
        if "@" in line or re.search(r"[0-9][0-9 ()+-]{7,}[0-9]", line):
            continue
        kept.append(line)
    return "\n".join(kept)


def _claims_in(text: str) -> set[str]:
    """Every quantified token, normalised so that 1,000 and 1000 compare equal."""
    text = _strip_contact_lines(text)
    found = set()
    for token in re.findall(r"[0-9][0-9,.]*(?:[kKmMbB])?[+%]?", text):
        token = token.rstrip(".").replace(",", "").lower()
        if token:
            found.add(token)
    lowered = text.lower()
    found.update(word for word in SCALE_WORDS if word in lowered)
    return found


def check_grounding(markdown: str, resume_text: str) -> list[str]:
    """Quantified claims in the tailored CV that the master resume does not contain.

    The prompt forbids inventing facts and the memory is no longer allowed to supply
    them — but a prompt is a request, not a guarantee. This is the actual check:
    anything a recruiter could challenge with "where does that number come from?"
    must be traceable to the CV the candidate wrote himself.
    """
    grounded = _claims_in(resume_text)
    unsupported = []
    for claim in sorted(_claims_in(markdown)):
        if claim in grounded:
            continue
        # A single digit inside prose ("three departments", "2 years") is noise;
        # anything longer is a claim worth eyeballing.
        if claim.rstrip("+%").isdigit() and len(claim.rstrip("+%")) <= 1:
            continue
        unsupported.append(claim)
    return unsupported


def print_grounding_report(unsupported: list[str]) -> None:
    if not unsupported:
        print("  Grounding: every number in the tailored CV also appears in your master CV.")
        print()
        return
    print("  [!] NOT IN YOUR MASTER CV — check or delete before you send this:")
    for claim in unsupported:
        print(f"        {claim}")
    print("      This is wording that drifted away from your CV. Either the CV is")
    print("      missing the fact, or the bullet is overstating it.")
    print()


def _entry_text(entry: Any) -> str:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return " ".join(str(v) for v in entry.values() if isinstance(v, (str, int, float)))
    return str(entry)


def memory_for_prompt(memory: dict[str, Any], resume_text: str) -> tuple[dict[str, Any], list[Any], list[Any]]:
    """Memory with every ungrounded claim held back.

    The memory grows across runs and outlives any single version of the CV, so it
    can describe a resume the candidate no longer has. Telling the model "facts come
    from the resume only" is not enough — it treats a verified_achievement as the
    candidate's history and reuses it. So the stale ones never reach the prompt:
    any achievement or metric quantifying something the current CV does not is
    withheld here (it stays in the file, it just is not offered as evidence).
    """
    grounded_claims = _claims_in(resume_text)

    def is_grounded(entry: Any) -> bool:
        return not (_claims_in(_entry_text(entry)) - grounded_claims)

    filtered = dict(memory)
    held_achievements = [e for e in memory.get("verified_achievements", []) or [] if not is_grounded(e)]
    held_metrics = [e for e in memory.get("key_metrics", []) or [] if not is_grounded(e)]
    filtered["verified_achievements"] = [e for e in memory.get("verified_achievements", []) or [] if is_grounded(e)]
    filtered["key_metrics"] = [e for e in memory.get("key_metrics", []) or [] if is_grounded(e)]
    return filtered, held_achievements, held_metrics


def restore_withheld(updated: dict[str, Any], held_achievements: list[Any], held_metrics: list[Any]) -> dict[str, Any]:
    """Put the withheld entries back into the file the model never saw them in."""
    for key, held in (("verified_achievements", held_achievements), ("key_metrics", held_metrics)):
        existing = updated.get(key) or []
        seen = {_entry_text(e).strip().lower() for e in existing}
        for entry in held:
            if _entry_text(entry).strip().lower() not in seen:
                existing.append(entry)
        updated[key] = existing
    return updated


def print_match_report(report: dict[str, Any]) -> None:
    def bullets(items: Iterable[Any]) -> str:
        items = [str(i) for i in items or []]
        return "\n".join(f"    - {i}" for i in items) if items else "    (none)"

    print("\n" + "=" * 72)
    print("MATCH REPORT")
    print("=" * 72)
    print(f"\n  Fit: {report.get('overall_fit', '(not provided)')}\n")
    print("  Strengths:")
    print(bullets(report.get("strengths")))
    print("\n  Gaps to be aware of:")
    print(bullets(report.get("gaps")))
    print("\n  Keywords now covered:")
    keywords = [str(k) for k in report.get("keywords_injected") or []]
    print("    " + (", ".join(keywords) if keywords else "(none)"))
    print()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tailor_resume.py",
        description="Tailor a resume to a job description with Claude, and learn from every run.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python tailor_resume.py\n"
            "  python tailor_resume.py --company Acme --role 'Senior Data Analyst'\n"
            "  python tailor_resume.py --model claude-opus-5 --effort max\n"
            "  python tailor_resume.py --timestamped --out-dir runs\n"
        ),
    )
    parser.add_argument("--resume", type=Path, help="Original resume (.docx).")
    parser.add_argument("--jd", type=Path, help="Job description (.txt).")
    parser.add_argument("--memory", type=Path, help="Persistent learning profile (.json).")
    parser.add_argument("--out-dir", type=Path, help="Where to write the tailored files.")
    parser.add_argument("--model", help=f"Claude model ID (default: {DEFAULT_MODEL}).")
    parser.add_argument(
        "--effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        help=f"Reasoning depth (default: {DEFAULT_EFFORT}).",
    )
    parser.add_argument("--company", help="Company name, if it isn't obvious from the posting.")
    parser.add_argument("--role", help="Role title, if it isn't obvious from the posting.")
    parser.add_argument("--no-pdf", action="store_true", help="Skip PDF generation.")
    parser.add_argument("--keep-markdown", action="store_true", help="Also save tailored_resume.md.")
    parser.add_argument(
        "--timestamped",
        action="store_true",
        help="Name outputs <company>_<role>_<date> instead of overwriting tailored_resume.*",
    )
    parser.add_argument(
        "--no-memory-update",
        action="store_true",
        help="Read memory but do not write it back (useful for experiments).",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging.")
    return parser.parse_args(argv)


def resolve_path(cli_value: Path | None, env_key: str, fallback: str, base: Path = PROJECT_ROOT) -> Path:
    raw = cli_value or os.getenv(env_key) or fallback
    path = Path(raw)
    return path if path.is_absolute() else (base / path)


def slugify(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return (slug[:limit].strip("_") or "untitled").lower()


_ILLEGAL_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def candidate_name(memory: dict[str, Any], blocks: list[Block]) -> str:
    """The candidate's name, for naming the files a recruiter will see."""
    name = (memory.get("candidate_profile") or {}).get("full_name", "").strip()
    if not name:
        name = next((b.text.strip() for b in blocks if b.kind == "h1"), "")
    name = _ILLEGAL_FILENAME.sub("", strip_inline(name)).strip(" .")
    return name or "Resume"


def output_stem(memory: dict[str, Any], blocks: list[Block], *, timestamped: bool) -> str:
    """Recruiters see this filename — make it a person's name, not 'tailored_resume'."""
    stem = f"{candidate_name(memory, blocks)} - CV"
    if timestamped:
        stem += f" - {date.today().isoformat()}"
    return stem


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(levelname)s] %(message)s",
    )
    # fontTools narrates every glyph it subsets, and httpx logs each request.
    # Useful when debugging, deafening otherwise.
    for noisy in ("fontTools", "fontTools.subset", "fontTools.ttLib", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.DEBUG if args.verbose else logging.WARNING)

    load_dotenv(PROJECT_ROOT / ".env")

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "ERROR: ANTHROPIC_API_KEY is not set.\n"
            "       Copy .env.example to .env and paste your key from\n"
            "       https://console.anthropic.com/settings/keys"
        )
    if not api_key.startswith("sk-ant-"):
        log.warning("ANTHROPIC_API_KEY does not look like an Anthropic key (expected sk-ant-...).")

    resume_path = resolve_path(args.resume, "RESUME_INPUT", "my_resume.docx")
    jd_path = resolve_path(args.jd, "JOB_DESCRIPTION", "job_description.txt")
    memory_path = resolve_path(args.memory, "MEMORY_FILE", "candidate_memory.json", base=ENGINE_DIR)
    out_dir = resolve_path(args.out_dir, "OUTPUT_DIR", "applications")
    out_dir.mkdir(parents=True, exist_ok=True)

    model = args.model or os.getenv("ANTHROPIC_MODEL") or DEFAULT_MODEL
    effort = args.effort or os.getenv("RESUME_EFFORT") or DEFAULT_EFFORT

    print("=" * 72)
    print("  RESUME TAILOR")
    print("=" * 72)

    # --- 1. Inputs --------------------------------------------------------
    resume_text = read_master_text(resume_path)
    job_description = read_job_description(jd_path)
    memory = load_memory(memory_path)
    jd_meta = guess_job_meta(job_description, args.company, args.role)
    log.info("Target: %s @ %s", jd_meta.role, jd_meta.company)

    # --- 2. Claude --------------------------------------------------------
    prompt_memory, held_achievements, held_metrics = memory_for_prompt(memory, resume_text)
    if held_achievements or held_metrics:
        log.info(
            "Withheld %s achievement(s) and %s metric(s) from the prompt: they quantify "
            "something your current CV does not say.",
            len(held_achievements),
            len(held_metrics),
        )

    client = anthropic.Anthropic(api_key=api_key)
    payload, usage = call_claude(
        client=client,
        model=model,
        effort=effort,
        user_prompt=build_user_prompt(
            resume_text=resume_text,
            memory=prompt_memory,
            job_description=job_description,
            jd_meta=jd_meta,
        ),
    )
    log.info(
        "Tokens — input: %s, output: %s",
        f"{usage.input_tokens:,}",
        f"{usage.output_tokens:,}",
    )

    markdown = payload["tailored_resume_markdown"].strip()
    blocks = parse_markdown(markdown)
    if not blocks:
        raise SystemExit("ERROR: the tailored resume came back empty. Retry.")
    log.info("Parsed %s content blocks from the tailored resume.", len(blocks))

    # --- 3. Documents -----------------------------------------------------
    stem = output_stem(memory, blocks, timestamped=args.timestamped)

    # A general (untailored) copy may have been dropped here as a placeholder.
    # The tailored version supersedes it, so clear it out to avoid sending the wrong file.
    for stale in out_dir.glob("* - CV (general).*"):
        stale.unlink(missing_ok=True)
        log.info("Removed the general fallback copy %s", stale.name)

    docx_path = out_dir / f"{stem}.docx"
    try:
        build_docx(blocks, docx_path)
    except PermissionError as exc:
        raise SystemExit(
            f"ERROR: cannot write {docx_path.name} — it is probably open in Word. "
            f"Close it and retry.\n       ({exc})"
        ) from exc

    if not args.no_pdf:
        pdf_path = out_dir / f"{stem}.pdf"
        try:
            build_pdf(blocks, pdf_path)
        except PermissionError as exc:
            log.error("Cannot write %s — close it in your PDF viewer and retry. (%s)", pdf_path.name, exc)
        except Exception as exc:  # never let PDF trouble lose the .docx
            log.error("PDF generation failed (%s). The .docx was written successfully.", exc)

    if args.keep_markdown:
        md_path = out_dir / f"{stem}.md"
        md_path.write_text(markdown + "\n", encoding="utf-8")
        log.info("Wrote %s", md_path.name)

    # --- 4. Memory --------------------------------------------------------
    if args.no_memory_update:
        log.info("Skipping memory update (--no-memory-update).")
    else:
        updated = normalise_updated_memory(memory, payload["updated_memory"], jd_meta)
        updated = restore_withheld(updated, held_achievements, held_metrics)
        save_memory(memory_path, updated)
        log.info(
            "Memory updated: run #%s, %s achievements, %s keywords tracked",
            updated["run_count"],
            len(updated["verified_achievements"]),
            len(updated["keyword_frequency"]),
        )
        questions = updated.get("open_questions") or []
        if questions:
            print("\n  Claude would like to know:")
            for question in questions[:5]:
                print(f"    ? {question}")

    # --- 5. Report --------------------------------------------------------
    print_match_report(payload.get("match_report", {}))
    print_grounding_report(check_grounding(markdown, resume_text))
    print(f"Done. Outputs in {out_dir.resolve()}\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.stderr.write("\nInterrupted.\n")
        raise SystemExit(130)
