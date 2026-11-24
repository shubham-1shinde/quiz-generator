# Fieldnote — Automatic MCQ Quiz Generator

A compact React/Vite + FastAPI + SQLite app for turning text into a saved, playable quiz. Gemini (`gemini-3.8-flash` by default) is the only hosted model call. New chunks are cached by SHA-256. If Gemini is missing or errors (including rate limits), generation tries local Ollama (`qwen2.5:7b`).

## Start

1. Python 3.10+: `cd backend; python -m venv .venv; .venv\Scripts\activate; pip install -r requirements.txt`
2. In the project root, copy `.env.example` to `.env` and paste your Gemini key after `GEMINI_API_KEY=` (or install/start Ollama and `ollama pull qwen2.5:7b`).
3. Start API: from `backend`, run `uvicorn main:app --reload`.
4. Node 18+: `cd frontend; npm install; npm run dev`; open the Vite URL.

SQLite is initialized automatically at `backend/quiz.db`. PDF/TXT extraction, quiz CRUD, score recording, JSON/CSV/PDF downloads, and evaluation are API-backed. PDF export uses ReportLab.

## Local validators

Optional dependencies: `pip install sentence-transformers transformers torch`. Set `ENABLE_LOCAL_VALIDATORS=true` to load `deepset/roberta-base-squad2` and `cross-encoder/nli-deberta-v3-small` on first validation. These downloads are large and require Hugging Face network access. MiniLM screening activates when sentence-transformers is installed. If packages/models are unavailable, startup and generation still work; the UI/API limitations describe which checks did not run. The current repair path keeps the model's three candidates; robust same-type noun phrase replacement is not implemented.

## Evaluation

The Evaluation page reports values available from stored runs and marks unavailable metrics honestly. `python backend/seed_evaluation.py` (with the API running) loads a deterministic labelled example without an LLM call. `/api/evaluation/upload` accepts your own JSON array of `{"passage":"…","question":"…","answer":"…"}` records. Human-label accuracy is computed only for exact question-text matches. SciQ/RACE download, baseline generation, calibrated answer-position statistics, question-level solve rates, and full validity confusion metrics are not implemented in this time-boxed build; they are not presented as measured results. Do not interpret exact-sentence grounding as answer-key verification.

## API

`POST /api/generate`, `POST /api/extract`, `GET /api/quizzes`, `GET /api/quizzes/{id}`, `POST /api/quizzes/{id}/submit`, `GET /api/evaluation`, `POST /api/evaluation/seed`, `GET /api/export/{id}/{pdf|json|csv}`.
