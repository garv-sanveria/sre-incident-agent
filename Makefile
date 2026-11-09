.PHONY: install run test seed demo eval
install:
	python3 -m venv .venv
	.venv/bin/pip install -e '.[test,live]'
run:
	.venv/bin/uvicorn incident_agent.main:app --host 127.0.0.1 --port 8000
test:
	.venv/bin/pytest -q
seed:
	curl -fsS -X POST http://127.0.0.1:8000/api/demo/seed
demo:
	curl -fsS -X POST http://127.0.0.1:8000/api/demo/cold
	curl -fsS -X POST http://127.0.0.1:8000/api/demo/seed
	curl -fsS -X POST http://127.0.0.1:8000/api/demo/warm
eval:
	curl -fsS -X POST http://127.0.0.1:8000/api/demo/eval
