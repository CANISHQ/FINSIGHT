# FinSight AI: FastAPI Backend Architecture and Implementation Plan

**Plan for review. No backend code has been written or changed by this architecture plan. The existing FinSight Engine previously passed all 104 tests.**

## A blocker to settle first

The original development environment had no internet and FastAPI, Pydantic, httpx and pytest were not installed. Two options were proposed:

- **Option A:** Enable network access so dependencies can be installed and backend tests can be run in that environment.
- **Option B:** Write the backend and tests, then run them locally with the supplied commands. Nothing should be described as tested until the results are actually reported.

## Architecture in plain terms

There are three layers, each talking only to the layer below it:

1. **API layer (FastAPI):** receives web requests, checks data shape and returns JSON. It contains no financial logic.
2. **Service layer:** translates the request into engine calls: `normalize_record`, then `resolve_restatements`, then `analyse_company`, then `to_dict()`.
3. **Engine (`finsight_engine`):** owns all financial calculations. It stays untouched and does not know the API exists.

The API must not reimplement formulas or modify financial values.

## Proposed folder layout

A separate `finsight-backend/` folder sits alongside the engine:

- `pyproject.toml`: backend dependencies and test tools.
- `README.md`: beginner-friendly install, run and test instructions.
- `app/main.py`: app creation, routers and exception handlers.
- `app/core/config.py`: limits such as maximum request records.
- `app/core/errors.py`: consistent JSON error format.
- `app/schemas/research.py`: Pydantic request and response schemas.
- `app/services/analysis_service.py`: adapter that calls the engine.
- `app/api/health.py`: GET `/health`.
- `app/api/v1/research.py`: analysis and compare endpoints.
- `tests/test_health.py`, `tests/test_analyse.py`, `tests/test_compare.py`: API integration tests.

## Endpoints

### GET /health

Returns `{status: "ok", ...}`. It also confirms the engine imports so a broken installation is visible early.

### POST /api/v1/research/analyse

The request contains a company name, accounting basis (consolidated or standalone), optional `as_of` date, and financial records. Each record has fiscal year, period type and optional quarter, unit, sector type, line items, and a source block (source ID, name, URL, verification status).

The engine normalizes raw labels and stated units, then the API returns the engine's `to_dict()` output without financial recalculation.

### POST /api/v1/research/compare

Returns HTTP 501 Not Implemented with an explanation. The future design is side-by-side engine facts with comparability warnings (for example, a bank compared with an industrial company) and no invented "winner".

## Validation and errors

Pydantic checks request shape. It rejects missing units or basis, quarterly periods without a quarter, unknown fields, empty record lists, and record counts above the configured limit.

Known engine validation failures (for example bad units, conflicting duplicate labels or comparability errors) should become clean HTTP 422 responses. Unexpected errors return a generic HTTP 500 and are logged without leaking stack traces.

All errors use this shape:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable explanation",
    "details": {}
  }
}
```

## Tests

Use FastAPI's test client. Tests should cover:

- Parity: API response equals a direct engine call for the same input.
- Consolidated and standalone input in one request, with only the requested basis analysed.
- Restated and quarterly periods.
- Bank-sector behaviour.
- Red flags and error cases.
- Compare endpoint returning 501.

Re-run the engine's 104 tests after every major implementation stage.

## Build order

1. Scaffold the backend, add `/health` and its test.
2. Add schemas.
3. Add service and analysis endpoint.
4. Add error handling.
5. Add compare stub.
6. Write integration tests.
7. Write README, then run engine and backend tests together.

## Decisions

1. **Network:** use Option A or Option B based on the actual development environment.
2. **Engine packaging:** add a minimal `pyproject.toml` to the engine so the backend can install it cleanly; this must not touch engine logic. A `PYTHONPATH` workaround was the alternative.
3. **No records for requested basis:** return HTTP 200 with the engine's empty analysis and data-quality note, rather than 422.

## Out of scope for this stage

Login, database, rate limiting, data providers and AI chat are deliberately left out.
