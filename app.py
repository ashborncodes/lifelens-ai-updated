import os
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF
import streamlit as st
from dotenv import load_dotenv

import core

load_dotenv()
st.set_page_config(page_title="LifeLens AI", page_icon="🔎", layout="wide")

st.markdown("""
<style>
.block-container {max-width: 1100px; padding-top: 2rem;}
.hero {padding: 1.4rem 1.6rem; border-radius: 18px; background: linear-gradient(120deg,#191c3a,#33256b); color: white;}
.hero h1 {margin-bottom: .25rem;}
.small-muted {color: #c4c9d8;}
</style>
""", unsafe_allow_html=True)
st.markdown('<div class="hero"><h1>🔎 LifeLens AI</h1><p>From information overload to action.</p>'
            '<p class="small-muted">Every task is linked to its source. Every uncertain date is flagged, never guessed.</p></div>',
            unsafe_allow_html=True)
st.write("")

SAMPLE = (Path(__file__).parent / "samples" / "sample_notice.txt").read_text(encoding="utf-8")
API_KEY = os.getenv("GEMINI_API_KEY", "").strip()


def read_pdf(uploaded_file):
    """Extract text from a text-based PDF. Scanned PDFs need OCR (not included)."""
    doc = fitz.open(stream=uploaded_file.getvalue(), filetype="pdf")
    return "\n".join(page.get_text("text") for page in doc).strip()


with st.sidebar:
    st.header("Input")
    st.caption("Use fictional or non-sensitive documents for the demo.")
    uploaded = st.file_uploader("Upload a text-based PDF", type=["pdf"])
    use_sample = st.checkbox("Use sample college notice", value=True)
    st.caption("Scanned PDFs are not supported (no OCR).")
    st.divider()
    ref_date = st.date_input("Today's date (for countdowns)", value=date.today())
    use_ai = st.toggle("Use AI extraction", value=bool(API_KEY), disabled=not API_KEY)
    if API_KEY:
        st.caption("AI output is always re-checked against the source text.")
    else:
        st.caption("No GEMINI_API_KEY found, so the offline extractor is used. Add a key in `.env` to enable AI.")

pasted = st.text_area("Or paste a notice / assignment text", height=180, placeholder="Paste the instructions here…")

source_text = ""
if uploaded is not None:
    try:
        source_text = read_pdf(uploaded)
        if not source_text:
            st.warning("No selectable text found. This may be a scanned PDF; OCR is not included.")
    except Exception as exc:
        st.error(f"Could not read this PDF: {exc}")
elif pasted.strip():
    source_text = pasted.strip()
elif use_sample:
    source_text = SAMPLE

if st.button("Create action plan", type="primary", use_container_width=True):
    if not source_text.strip():
        st.error("Add text, upload a PDF, or select the sample notice.")
    else:
        with st.spinner("Reading the document…"):
            st.session_state["result"] = core.analyze(
                source_text, ref=ref_date, api_key=API_KEY, use_llm=use_ai)

result = st.session_state.get("result")
if result:
    tasks = result["tasks"]
    st.subheader("Your action plan")
    if result["warning"]:
        st.warning(result["warning"])
    st.caption(f"Mode: **{result['mode']}**. Verify important dates against the original document.")

    dated = [t for t in tasks if t["deadline_iso"]]
    c1, c2, c3 = st.columns(3)
    c1.metric("Tasks found", len(tasks))
    c2.metric("Need review", sum(t["needs_review"] for t in tasks))
    c3.metric("Next deadline", dated[0]["deadline_iso"] if dated else "None found")

    st.markdown("#### Summary")
    st.write(result["summary"])

    st.markdown("#### Tasks")
    completed = 0
    for idx, task in enumerate(tasks):
        with st.container(border=True):
            cols = st.columns([0.07, 0.53, 0.22, 0.18])
            done = cols[0].checkbox("Done", key=f"done_{idx}", label_visibility="collapsed")
            completed += int(done)
            cols[1].markdown(f"**{task['task']}**")
            cols[2].caption("Deadline")
            if task["deadline_iso"]:
                d = task["days_left"]
                when = "today" if d == 0 else (f"in {d} days" if d > 0 else f"{-d} days ago")
                cols[2].write(f"{task['deadline_iso']} ({when})")
            else:
                cols[2].write(task["deadline_text"] or "Not found")
            cols[3].caption("Priority")
            cols[3].write("Complete" if done else task["priority"])
            for note in task["notes"]:
                st.caption("ℹ️ " + note)
            for flag in task["flags"]:
                st.warning(flag, icon="⚠️")
            with st.expander("View source evidence"):
                st.write(task["evidence"])
                if task["evidence_verified"]:
                    st.caption("✅ Quote found verbatim in the source document.")
                else:
                    st.caption("⚠️ Quote could not be matched to the source — check manually.")
    st.progress(completed / max(len(tasks), 1), text=f"{completed} of {len(tasks)} tasks completed")

    if result["key_dates"]:
        st.markdown("#### Other dates in the document")
        for k in result["key_dates"]:
            st.write(f"**{k['iso'] or k['date_text']}** — {k['context']}")
            for f in k["flags"]:
                st.caption("⚠️ " + f)

    d1, d2 = st.columns(2)
    d1.download_button("Download checklist (.md)", core.to_markdown(result),
                       file_name="lifelens_action_plan.md", use_container_width=True)
    d2.download_button("Download calendar file (.ics)", core.to_ics(result),
                       file_name="lifelens_deadlines.ics", mime="text/calendar", use_container_width=True)

with st.expander("How does LifeLens avoid made-up deadlines?"):
    st.write("The AI only *proposes* tasks. Our own code then (1) checks that each evidence quote exists verbatim in your "
             "document, (2) checks that each deadline text appears in the document and re-parses the date itself, and "
             "(3) flags relative, ambiguous or missing dates as “needs review” instead of guessing.")
