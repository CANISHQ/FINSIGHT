# FinSight AI

AI-powered financial research and analysis platform.

## Repository structure

- `frontend/`: existing HTML prototype.
- `finsight-engine/`: deterministic financial analysis engine, data models, normalization, metrics, red flags, and tests.
- `docs/`: backend architecture and implementation plan.

## Current status

The financial engine is implemented and its existing test suite contains 104 tests. The FastAPI backend and frontend-to-backend integration are planned, but have not yet been implemented.

## Financial engine

See [finsight-engine/README.md](finsight-engine/README.md) for formulas, input conventions, output format, and limitations.

To run the engine tests from the repository root:

```bash
cd finsight-engine
python -m unittest discover -s tests -t .
```

## Frontend

Open [frontend/index.html](frontend/index.html) in a browser to inspect the current prototype. It is not yet connected to a live backend.

## Planned architecture

```
Frontend (Vercel)
    |
    | HTTPS / JSON
    v
FastAPI backend (Render or Railway)
    |
    v
FinSight financial engine
```

The backend will call the existing engine and must not duplicate or change its financial calculations.

## Important

Do not commit API keys, credentials, local environment files, or private financial data.
