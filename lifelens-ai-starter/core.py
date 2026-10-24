"""LifeLens AI core engine (no Streamlit imports, so it is unit-testable).

Design rule: the model may *propose* tasks, but deterministic code decides what
is trusted. Every deadline is re-parsed from the source text by us, every
evidence quote must exist verbatim in the source, and anything uncertain is
flagged "needs review" instead of being guessed.
"""
import json
import os
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

# ----------------------------------------------------------------- dates ----
_MON = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)")
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

DMY_TEXT = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MON})\.?(?:,?\s+(\d{{4}}))?\b", re.I)
MDY_TEXT = re.compile(rf"\b({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", re.I)
NUMERIC = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b")
RELATIVE = re.compile(
    r"\b(today|tonight|tomorrow|day after tomorrow|"
    r"(?:next|this) (?:mon|tues|wednes|thurs|fri|satur|sun)day|"
    r"next week|this week|end of (?:the )?(?:day|week|month)|eod|asap|"
    r"immediately|soon|shortly)\b", re.I)

ACTION = re.compile(
    r"\b(submit|register|bring|upload|complete|prepare|attend|apply|send|fill|pay|"
    r"collect|carry|ensure|must|should|required|need to|have to|remember|confirm|"
    r"sign|email|reply|report|deliver|hand in|present)\b", re.I)
DEADLINE_WORDS = re.compile(
    r"\b(before|by|until|till|closes?|closing|deadline|last date|due|no later than|on or before)\b", re.I)
DEADLINE_REF = re.compile(r"\b(the deadline|before it closes|by the deadline|before the deadline)\b", re.I)


def _make_date(day, month, year, ref):
    """Return (iso|None, flags). Assumes the next occurrence if year is missing."""
    flags = []
    assumed = year is None
    if assumed:
        year = ref.year
    try:
        d = date(year, month, day)
    except ValueError:
        return None, ["Invalid calendar date — needs review"]
    if assumed:
        if d < ref:
            try:
                d = date(year + 1, month, day)
            except ValueError:
                return None, ["Invalid calendar date — needs review"]
        flags.append("Year not stated — assumed " + str(d.year))
    return d.isoformat(), flags


def find_dates(text, ref=None):
    """Find date mentions. Returns list of dicts: raw, iso, flags, start, end."""
    ref = ref or date.today()
    hits = []

    def overlaps(s, e):
        return any(s < h["end"] and e > h["start"] for h in hits)

    for m in DMY_TEXT.finditer(text):
        day, mon, yr = int(m.group(1)), MONTHS[m.group(2)[:3].lower()], m.group(3)
        iso, fl = _make_date(day, mon, int(yr) if yr else None, ref)
        hits.append({"raw": m.group(0), "iso": iso, "flags": fl, "start": m.start(), "end": m.end()})
    for m in MDY_TEXT.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        mon, day, yr = MONTHS[m.group(1)[:3].lower()], int(m.group(2)), m.group(3)
        iso, fl = _make_date(day, mon, int(yr) if yr else None, ref)
        hits.append({"raw": m.group(0), "iso": iso, "flags": fl, "start": m.start(), "end": m.end()})
    for m in NUMERIC.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        flags = []
        if a > 12:
            day, mon = a, b
        elif b > 12:
            mon, day = a, b
        else:
            day, mon = a, b  # day-first default
            if a != b:
                flags.append("Ambiguous format (day/month or month/day) — needs review")
        iso, fl = _make_date(day, mon, y, ref)
        hits.append({"raw": m.group(0), "iso": iso, "flags": flags + fl, "start": m.start(), "end": m.end()})
    for m in RELATIVE.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        hits.append({"raw": m.group(0), "iso": None,
                     "flags": ["Relative or vague date — needs review"], "start": m.start(), "end": m.end()})
    return sorted(hits, key=lambda h: h["start"])


def days_left(iso, ref):
    if not iso:
        return None
    return (date.fromisoformat(iso) - ref).days


def priority_for(days):
    if days is None:
        return "Review"
    if days < 0:
        return "Overdue"
    if days <= 3:
        return "High"
    if days <= 10:
        return "Medium"
    return "Low"


# ------------------------------------------------------------ text utils ----
def _norm(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()


def split_units(text):
    """Split into line/sentence units, stripping bullets."""
    units = []
    for line in text.splitlines():
        line = line.strip(" •-*\t")
        if not line:
            continue
        for piece in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", line):
            piece = piece.strip()
            if piece:
                units.append(piece)
    return units


def simple_summary(text):
    cleaned = re.sub(r"\s+", " ", text).strip()
    pieces = [p.strip() for p in re.split(r"(?<=[.!?])\s+|(?<=\n)", text) if p.strip()]
    return " ".join(pieces[:3])[:700] if pieces else cleaned[:700]


# ----------------------------------------------------- offline extraction ----
def heuristic_extract(text, ref):
    """Offline fallback: returns (summary, raw_tasks). raw task = task/deadline_text/evidence/notes."""
    units = split_units(text)
    last_deadline_unit = None
    raw = []
    for u in units:
        dates = find_dates(u, ref)
        is_deadline_line = bool(dates) and bool(DEADLINE_WORDS.search(u))
        is_task = bool(ACTION.search(u))
        if is_task:
            deadline_text, evidence, notes = (dates[0]["raw"] if dates else ""), u, []
            if not dates and DEADLINE_REF.search(u) and last_deadline_unit:
                ld = find_dates(last_deadline_unit, ref)
                deadline_text = ld[0]["raw"]
                evidence = u + " … " + last_deadline_unit
                notes.append("Deadline linked from another line: “" + last_deadline_unit + "”")
            raw.append({"task": u[:180], "deadline_text": deadline_text,
                        "evidence": evidence, "notes": notes})
        if is_deadline_line:
            last_deadline_unit = u
    return simple_summary(text), raw[:20]


# --------------------------------------------------------- LLM extraction ----
PROMPT = """You extract action items from a document for a student.
Return ONLY JSON of the form:
{"summary": "2-3 plain-language sentences",
 "tasks": [{"task": "short imperative action",
            "deadline_text": "the date text copied EXACTLY from the document, or empty string if none",
            "evidence": "the sentence copied EXACTLY from the document that supports this task"}]}
Rules: never invent or infer a date; copy deadline_text and evidence verbatim; if a date is vague
(e.g. "next Friday") copy it as written; if there is no date use an empty string.

DOCUMENT:
"""


def llm_extract(text, api_key, model=None, timeout=30):
    """Call Gemini REST API. Returns (summary, raw_tasks). Raises on any failure."""
    model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = json.dumps({
        "contents": [{"parts": [{"text": PROMPT + text[:30000]}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "x-goog-api-key": api_key})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    return parse_llm_json(payload["candidates"][0]["content"]["parts"][0]["text"])


def parse_llm_json(s):
    s = re.sub(r"^```(?:json)?|```$", "", s.strip(), flags=re.M).strip()
    data = json.loads(s)
    tasks = []
    for t in data.get("tasks", []):
        if isinstance(t, dict) and t.get("task"):
            tasks.append({"task": str(t["task"])[:180],
                          "deadline_text": str(t.get("deadline_text") or ""),
                          "evidence": str(t.get("evidence") or ""), "notes": []})
    return str(data.get("summary", "")), tasks[:20]


# ------------------------------------------------ validation (the moat) ----
def validate(raw_tasks, source, ref):
    """Trust nothing from extraction: re-verify evidence + deadline against the source."""
    src = _norm(source)
    out = []
    for r in raw_tasks:
        flags, notes = [], list(r.get("notes", []))
        evidence = r.get("evidence", "")
        parts = [p for p in re.split(r"\s…\s", evidence) if p.strip()]
        verified = bool(parts) and all(_norm(p) in src for p in parts)
        if not verified:
            flags.append("Evidence not found verbatim in source — needs review")

        iso, dtext = None, r.get("deadline_text", "").strip()
        if dtext:
            if _norm(dtext) not in src:
                flags.append("Deadline “" + dtext + "” is not in the source — removed")
                dtext = ""
            else:
                hits = find_dates(dtext, ref)
                if hits:
                    iso = hits[0]["iso"]
                    flags += hits[0]["flags"]
                else:
                    flags.append("Could not read this date — needs review")
        else:
            flags.append("No deadline found — verify source")

        d = days_left(iso, ref)
        out.append({"task": r["task"], "deadline_text": dtext, "deadline_iso": iso,
                    "days_left": d, "priority": priority_for(d), "evidence": evidence,
                    "evidence_verified": verified, "flags": flags, "notes": notes,
                    "needs_review": bool(flags)})
    out.sort(key=lambda t: (t["deadline_iso"] is None, t["deadline_iso"] or ""))
    return out


def key_dates(source, tasks, ref):
    """Dates in the source that are not already covered by a task (e.g. the event day)."""
    covered = " ".join(_norm(t["evidence"]) for t in tasks)
    found = []
    for u in split_units(source):
        if _norm(u) in covered:
            continue
        for h in find_dates(u, ref):
            found.append({"date_text": h["raw"], "iso": h["iso"], "context": u, "flags": h["flags"]})
    return found


# -------------------------------------------------------------- pipeline ----
def analyze(text, ref=None, api_key=None, use_llm=True):
    ref = ref or date.today()
    mode, warning = "Offline heuristic", None
    if use_llm and api_key:
        try:
            summary, raw = llm_extract(text, api_key)
            mode = "AI extraction + validation"
        except Exception as exc:  # network, quota, bad JSON ...
            warning = f"AI call failed ({type(exc).__name__}); showing offline results instead."
            summary, raw = heuristic_extract(text, ref)
    else:
        summary, raw = heuristic_extract(text, ref)
    tasks = validate(raw, text, ref)
    return {"summary": summary or simple_summary(text), "tasks": tasks,
            "key_dates": key_dates(text, tasks, ref), "mode": mode, "warning": warning}


# ---------------------------------------------------------------- exports ----
def to_markdown(result):
    md = "# LifeLens AI action plan\n\n## Summary\n" + result["summary"] + "\n\n## Tasks\n"
    for t in result["tasks"]:
        dl = t["deadline_iso"] or t["deadline_text"] or "no deadline found"
        md += f"- [ ] {t['task']} — Deadline: {dl} ({t['priority']})\n  - Source: {t['evidence']}\n"
        for f in t["flags"]:
            md += f"  - ⚠ {f}\n"
    return md


def to_ics(result):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//LifeLens AI//EN"]
    for i, t in enumerate(result["tasks"]):
        if not t["deadline_iso"]:
            continue
        d = t["deadline_iso"].replace("-", "")
        end = (date.fromisoformat(t["deadline_iso"]) + timedelta(days=1)).strftime("%Y%m%d")
        summ = t["task"].replace(",", "\\,").replace(";", "\\;")
        lines += ["BEGIN:VEVENT", f"UID:lifelens-{i}-{d}@lifelens.local",
                  f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
                  f"DTSTART;VALUE=DATE:{d}", f"DTEND;VALUE=DATE:{end}", f"SUMMARY:{summ}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
