# BrandOrbit - notes for coding agents

- Python 3.11, virtualenv at `.venv` (Windows: `.venv/Scripts/python`).
- Run app: `streamlit run streamlit_app.py` (demo workspace auto-created; no API key needed).
- Tests: `pytest` (UI smoke tests use Streamlit AppTest and take ~1-2 min). Fast subset: `pytest --ignore=tests/test_ui_smoke.py`.
- Evaluation: `python -m evaluation.run_eval` (add `--llm` only with a live key). Update `EVALUATION.md` and the README table if numbers change.
- Demo fixtures live in `data/demo`; finding IDs referenced in `run_followup.json::implemented_between_runs` must match IDs produced by `analysis/recommendations.py` for the baseline run (checked by `test_before_after_comparison`).
- Never commit `.env` or `*.db`. Never add real brand names to demo fixtures.
