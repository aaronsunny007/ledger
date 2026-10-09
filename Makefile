.PHONY: install test lint eval eval-test smoke golden data run ui

install:
	pip install -e ".[dev,models]"

lint:
	ruff check . && ruff format --check . && mypy

test:
	pytest --cov

golden:
	python scripts/financebench.py && python scripts/make_xbrl_questions.py

data:
	ledger download && ledger ingest

smoke:
	python eval/run_eval.py --smoke --gate --sleep 4

eval:
	python eval/run_eval.py --split dev --sleep 4

eval-test:
	python eval/run_eval.py --split test --judge --sleep 4

run:
	uvicorn ledger.api.main:app --reload

ui:
	streamlit run ui/streamlit_app.py
