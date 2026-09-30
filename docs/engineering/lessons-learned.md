# Failure Memory / Lessons Learned

Record meaningful incidents and near misses here.

## Template

### YYYY-MM-DD — Short title
- **Symptom:**
- **Root cause:**
- **Resolution:**
- **Prevention:**
- **Generalized lesson:**
- **Guardrail/test/pattern added:**
- **RAIDER impact:**

### 2026-09-30 — Cloudflare Python Worker request/runtime boundary drift
- **Symptom:** The Worker deployment path mixed undocumented environment discovery with a non-canonical ASGI request shape while production health remained opaque.
- **Root cause:** The Worker entrypoint passed the Python request wrapper instead of `request.js_object`, and application bootstrap attempted to discover bindings through an undocumented module-level `workers.env` instead of the explicit `WorkerEntrypoint.env`.
- **Resolution:** Use the runtime `asgi` bridge with `request.js_object`, and bind `self.env` before importing the FastAPI application so cached settings and SQLAlchemy see the managed Hyperdrive binding.
- **Prevention:** Treat the Worker entrypoint boundary as a platform contract and keep it covered by regression tests rather than inferred runtime behavior.
- **Generalized lesson:** When an edge runtime exposes bindings through the request/entrypoint context, pass that context explicitly into application bootstrap; do not rely on process-global discovery semantics from conventional servers.
- **Guardrail/test/pattern added:** Source-level tests require the documented ASGI request shape and explicit Worker env injection, plus a runtime test that derives the PostgreSQL URL from a fake Hyperdrive binding.
- **RAIDER impact:** Durable/non-regressive, Engineering-grade, Retroactive.
- **Correction:** This drift was real, but it was not the root cause of the persistent production HTTP 500. Stage probes later isolated the blocking failure to request CPU exhaustion.

### 2026-09-30 — FastAPI/SQLAlchemy bootstrap exceeds Workers Free CPU budget
- **Symptom:** AppFactory reported `WORKER_DATABASE_NOT_READY` with `health=unknown`, while the deployed Worker returned HTTP 500 before the FastAPI `/health` route could answer.
- **Root cause:** Request-time bootstrap of the full FastAPI application and the database path exceeds the Cloudflare Worker CPU budget. Fail-closed stage probes reached the Worker entrypoint, saw the managed `HYPERDRIVE` binding, resolved production PostgreSQL settings, then returned `introspection.CpuLimitExceeded: Python Worker exceeded CPU time limit` when loading the full app / exercising the DB path.
- **Resolution:** Architecture decision required: either run the Python Worker with a CPU budget suitable for FastAPI/SQLAlchemy or move/rework the backend runtime. Do not misdiagnose this as a Hyperdrive-binding failure.
- **Prevention:** Validate runtime CPU-budget compatibility before committing a framework-heavy backend to an edge free tier; include a production-like bootstrap probe in infrastructure acceptance tests.
- **Generalized lesson:** A deployment that fits the bundle-size and startup gates can still be incompatible with the per-request CPU model. Packaging success is not runtime viability.
- **Guardrail/test/pattern added:** Temporary non-secret fail-closed runtime stage probes distinguish entrypoint, settings, DB bootstrap, DB connection and full app import; issue #38 records the production evidence.
- **RAIDER impact:** Engineering-grade, Durable/non-regressive, Retroactive.
