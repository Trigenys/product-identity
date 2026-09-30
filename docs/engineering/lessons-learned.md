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
- **Symptom:** The Worker deployed successfully, but production `/health` returned HTTP 500 and AppFactory could only report `health=unknown` / `database_configured=null`.
- **Root cause:** The Worker entrypoint had drifted from Cloudflare's documented Python ASGI contract: it passed the Python request wrapper instead of `request.js_object`, and application bootstrap attempted to discover bindings through an undocumented module-level `workers.env` instead of the explicit `WorkerEntrypoint.env`.
- **Resolution:** Use the runtime `asgi` bridge with `request.js_object`, and bind `self.env` before importing the FastAPI application so cached settings and SQLAlchemy see the managed Hyperdrive binding.
- **Prevention:** Treat the Worker entrypoint boundary as a platform contract and keep it covered by regression tests rather than inferred runtime behavior.
- **Generalized lesson:** When an edge runtime exposes bindings through the request/entrypoint context, pass that context explicitly into application bootstrap; do not rely on process-global discovery semantics from conventional servers.
- **Guardrail/test/pattern added:** Source-level tests now require the documented ASGI request shape and explicit Worker env injection, plus a runtime test that derives the PostgreSQL URL from a fake Hyperdrive binding.
- **RAIDER impact:** Durable/non-regressive, Engineering-grade, Retroactive.
