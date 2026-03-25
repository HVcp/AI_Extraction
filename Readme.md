# POC — AI Daily Report Extraction

Azure Document Intelligence (prebuilt-layout) → GPT-4o → structured JSON → SQLite → Streamlit UI

## Repo structure

```
POC_AI_EXTRACTION/
├── .env                    ← credentials (never commit)
├── .gitignore
├── pyproject.toml
├── uv.lock
├── backend/
│   ├── main.py             ← FastAPI app + all endpoints
│   ├── extractor.py        ← Azure DI → GPT-4o pipeline
│   ├── database.py         ← SQLAlchemy + SQLite
│   └── models.py           ← Pydantic schemas (canonical daily report shape)
├── frontend/
│   └── app.py              ← Streamlit UI (upload, browse, detail)
└── sample_files/           ← drop test PDFs here (gitignored)
```

## Setup

```bash
# 1. Fill in .env with your Azure credentials

# 2. Install dependencies
uv sync

# ─── IMPORTANT: run ALL commands from the PROJECT ROOT (where pyproject.toml is) ───
# Do NOT cd into backend/ first — the module imports (database, extractor, models)
# resolve relative to the working directory uvicorn is launched from.

# 3. Start backend  ← run from POC_AI_EXTRACTION/
uv run uvicorn backend.main:app --reload --port 8000

# 4. Start frontend  ← new terminal, also from POC_AI_EXTRACTION/
uv run streamlit run frontend/app.py
```

Open http://localhost:8501

## What each file does

| File | Responsibility |
|------|----------------|
| `models.py` | Canonical schema for all vendor form variations. Single source of truth. |
| `database.py` | SQLite storage via SQLAlchemy. Swap `DATABASE_URL` to Azure SQL for prod. |
| `extractor.py` | **Core pipeline**: DI → confidence scoring → GPT-4o → Pydantic validation |
| `main.py` | FastAPI endpoints: `/extract`, `/records`, `/records/{id}`, `/health` |
| `frontend/app.py` | Streamlit: upload, status badges, flagged field highlighting, raw DI debug |

## Production swap points

- `DATABASE_URL` → `mssql+pyodbc://...` (Azure SQL)
- File storage → Azure Blob Storage (currently in-memory only)
- Auth → Azure AD middleware on FastAPI
- Hosting → Azure App Service (backend) + Static Web App or App Service (frontend)