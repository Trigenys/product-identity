# Cloudflare Python Worker deployment

Issue: #38

Product Identity keeps the existing FastAPI application and adds Cloudflare Python Workers as a deployment target. The web UI remains on Cloudflare Pages.

## Runtime topology

```text
Cloudflare Pages (React/Vite)
          |
          | VITE_API_BASE_URL
          v
Cloudflare Python Worker (FastAPI)
          |
          | HYPERDRIVE binding
          v
Cloudflare Hyperdrive
          |
          v
PostgreSQL / Neon
```

Shopify points its application URL, OAuth callback and webhook subscriptions at the Worker.

## Why the Worker adapter is isolated

The normal Python server runtime remains valid. Cloudflare-specific binding access lives in `app/core/runtime.py` and the Worker entry point lives in `worker.py`.

This prevents Cloudflare from leaking into the domain model or API contracts.

## Database safety

Cloudflare Hyperdrive owns connection pooling.

The Worker SQLAlchemy engine therefore uses `NullPool`; SQLAlchemy does not retain database connections between Worker request contexts.

The current ORM is synchronous. The Worker entry point serializes FastAPI request handling with an asyncio lock because Cloudflare currently supports synchronous SQLAlchemy but recommends serializing synchronous DB operations.

This is an MVP correctness tradeoff, not a high-throughput architecture. We can remove the global request lock when the runtime supports an async SQLAlchemy path compatible with Workers.

## Shopify outbound HTTP

The Shopify HTTP adapter uses `httpx.AsyncClient`. Python Workers support async HTTP clients; the previous synchronous `httpx.post` path was removed before deployment.

## CI compatibility gate

Every PR compiles the complete Worker bundle with Pywrangler using `--dry-run`.

This catches:
- unavailable Pyodide/PyEmscripten wheels;
- Python Worker dependency conflicts;
- invalid Worker configuration;
- Worker packaging regressions.

The first gate found that our old `cryptography<47` pin was incompatible with the current Worker runtime. The dependency is now pinned to `cryptography>=47,<48`.

## Production automation

`.github/workflows/deploy-cloudflare-worker.yml` runs after relevant changes reach `main`.

It:
1. checks required deployment credentials;
2. migrates PostgreSQL with Alembic;
3. creates or reuses `product-identity-postgres` Hyperdrive;
4. discovers the account's `workers.dev` subdomain;
5. discovers the Product Identity Pages project;
6. sets Pages `VITE_API_BASE_URL` to the Worker URL;
7. renders `wrangler.production.toml`;
8. bootstraps stable Worker-only signing/encryption secrets if they do not already exist;
9. deploys the Python Worker;
10. checks `/health`;
11. deploys the Shopify app configuration with the real Worker URL.

The workflow refuses to replace an existing Hyperdrive if its visible host/database/user differ from the supplied Neon origin.

## GitHub configuration required once

Repository secrets:
- `CLOUDFLARE_API_TOKEN`
- `NEON_DATABASE_URL` — direct, non-pooled Neon URL
- `SHOPIFY_CLIENT_SECRET`
- `SHOPIFY_APP_AUTOMATION_TOKEN` (already configured)

Repository variables:
- `CLOUDFLARE_ACCOUNT_ID`
- `SHOPIFY_CLIENT_ID` (already configured)

Optional:
- variable `CLOUDFLARE_PAGES_PROJECT` (defaults to `product-identity`)
- variable `PRODUCT_IDENTITY_WEB_URL` to override Pages discovery
- secret `SHOPIFY_PREVIOUS_CLIENT_SECRET` during Shopify secret rotation
- secret `PRODUCT_IDENTITY_AUTH_JWT_KEY` when the production OIDC provider is configured

### Cloudflare API token permissions

Scope the token to the Trigenys Cloudflare account and grant only:
- Workers Scripts: Edit;
- Hyperdrive: Edit;
- Cloudflare Pages: Edit.

Pages Edit is needed because the deploy pipeline writes the non-secret `VITE_API_BASE_URL` build variable.

## Neon connection string

Hyperdrive must receive a direct Neon connection, not Neon's pooled endpoint. The pipeline rejects hosts containing `-pooler.` to avoid stacking PgBouncer in front of Hyperdrive.

The Neon URL is used directly by GitHub Actions only for Alembic migrations. The Worker itself receives database credentials through the Hyperdrive binding.

## Worker-generated secrets

On first deployment the workflow generates:
- `PRODUCT_IDENTITY_SHOPIFY_TOKEN_ENCRYPTION_KEY`;
- `PRODUCT_IDENTITY_VERIFICATION_TOKEN_SECRET`;
- `PRODUCT_IDENTITY_PROOF_UPLOAD_SECRET`.

It checks remote Worker secret names first. Once created, these values are omitted from later deployment secret files, and Wrangler preserves remote secrets that are not included. This prevents accidental key rotation and token loss.

## Current limitation: proof object storage

The existing proof-of-purchase adapter is S3/boto3 based. Boto3 is now a server-only optional dependency and is deliberately not bundled into the Worker.

Therefore proof upload/download remains unavailable in the Worker deployment until an R2-native adapter is implemented. The API fails closed with a 503 when object storage is not configured.

This does not block Shopify OAuth, webhooks, product sync, serialization, registration, warranty state, registry, or public verification.

## From workers.dev to custom domain

The first deployment intentionally uses:

`https://product-identity-api.<account-subdomain>.workers.dev`

After the integration is proven end-to-end, attach a custom domain such as:

`https://api.identity.trigenys.com`

and rerun the same deployment pipeline with the production URL policy updated.
