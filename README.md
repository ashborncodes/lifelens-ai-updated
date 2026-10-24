# LifeLens AI

**From information overload to action.**

LifeLens AI is a hackathon MVP concept that converts long notices, assignment sheets, and other text-based documents into a simple, source-linked action plan.

## MVP goals

- Accept pasted text or a text-based PDF
- Summarize the source in plain language
- Extract tasks, dates, and requirements
- Show source evidence for extracted tasks
- Flag missing or ambiguous dates instead of guessing

## Tech stack

- Python
- Streamlit
- PyMuPDF
- LLM API (Gemini or another provider you configure)

## Quick start

1. Install Python 3.10+.
2. Create and activate a virtual environment.
3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Copy `.env.example` to `.env` and add your API key if you enable live AI calls.
5. Run:

   ```bash
   streamlit run app.py
   ```

Without an API key the app runs an offline extractor on the sample notice. With `GEMINI_API_KEY` set, the app calls the Gemini API (model configurable via `GEMINI_MODEL`) and then **re-validates every result in code**. Check the provider's current model names and quota before the demo.

Run the tests (no API key or network needed):

```bash
python -m unittest discover -s tests -v
```

## How it avoids made-up deadlines

1. The model only *proposes* tasks, with `deadline_text` and `evidence` copied from the document.
2. `core.validate()` checks each evidence quote exists verbatim in the source.
3. Each deadline text must appear in the source; the date is then re-parsed by our own code.
4. Relative ("next Friday"), ambiguous (`05/06/2026`), missing-year and missing dates are flagged **needs review**, never guessed.
5. If the AI call fails, the app falls back to the offline extractor and says so.

## Project structure

```text
lifelens-ai/
├── app.py            # Streamlit UI
├── core.py           # extraction, validation, date logic, exports
├── tests/test_core.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
└── samples/
    └── sample_notice.txt
```

## Demo workflow

1. Paste the sample notice or upload a text-based PDF.
2. Click **Create action plan**.
3. Review the summary and extracted tasks.
4. Check each task's source evidence.
5. Mark tasks complete.

## Important limitations

- The offline extractor is a heuristic; the AI path has not been load-tested. Neither is production-grade.
- Text-based PDFs are supported; scanned PDFs require OCR and are not supported in this starter.
- Always verify deadlines against the original document.
- Never commit API keys or private documents.
- Do not claim the app is production-ready based on the prototype.

## Suggested hackathon build order

1. Make text input and sample mode work.
2. Add PDF text extraction.
3. Add provider-backed structured extraction.
4. Add date validation and evidence checks.
5. Polish the UI and rehearse the demo.

## License

MIT — see `LICENSE`.
