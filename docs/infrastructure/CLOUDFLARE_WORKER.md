# Cloudflare Python Worker deployment

Issue: #38

Product Identity keeps the existing FastAPI application and adds Cloudflare Python Workers as a deployment target. The React/Vite UI remains on Cloudflare Pages.

## Runtime topology

```text
Trigenys/product-identity
        |
        | GitHub Actions OIDC
        v
AppFactory API
        |
        | existing Cloudflare account credentials
        v
Cloudflare Workers Builds
        |
        v
product-identity-api Worker
        |
        | HYPERDRIVE (next database step)
        v
PostgreSQL / Neon
```

Shopify uses the Worker URL for OAuth callbacks and webhooks.

## Credential ownership

Product Identity does **not** receive or store:
- `CLOUDFLARE_API_TOKEN`;
- `CLOUDFLARE_ACCOUNT_ID`;
- a Cloudflare Workers Builds token.

Those credentials remain owned by the existing `appfactory-api` Worker.

Product Identity keeps only its product-specific credentials in GitHub:
- repository variable `SHOPIFY_CLIENT_ID`;
- repository secret `SHOPIFY_CLIENT_SECRET`;
- repository secret `SHOPIFY_APP_AUTOMATION_TOKEN`;
- optional `SHOPIFY_PREVIOUS_CLIENT_SECRET` during rotation;
- optional production auth key.

## OIDC boundary

The only production infrastructure workflow is:

`.github/workflows/appfactory-infrastructure.yml`

It requests a short-lived GitHub Actions OIDC token with audience `appfactory-api` and calls:

`POST https://appfactory-api.lawrynnjennifer.workers.dev/infrastructure/worker`

AppFactory validates:
- GitHub's token signature;
- organization ownership;
- `refs/heads/main`;
- the exact workflow identity;
- that the caller can provision only its own repository.

The repository never receives the Cloudflare token.

## Worker ownership and brownfield safety

AppFactory derives the Worker name from the repository:

`product-identity -> product-identity-api`

The first successful claim writes:

`.appfactory/worker-infrastructure.json`

If a Worker with that name already exists without the AppFactory marker, provisioning fails instead of silently adopting or replacing it.

## Workers Builds

AppFactory creates/reuses:
- the Cloudflare Worker;
- the GitHub repository connection;
- the existing Workers Builds deployment token;
- a production trigger rooted at `/backend`.

The reviewed Python Worker recipe performs a Pywrangler dry run before deployment and deploys with `--keep-vars`.

The repository's normal CI also performs a Pywrangler dry-run, so Worker package compatibility is checked independently of Cloudflare deployment.

## Runtime secrets

The OIDC request sends product-specific values directly to AppFactory over HTTPS. AppFactory writes them to the Product Identity Worker through the Cloudflare secret API and never returns the values.

Stable secrets generated only when absent:
- `PRODUCT_IDENTITY_SHOPIFY_TOKEN_ENCRYPTION_KEY`;
- `PRODUCT_IDENTITY_VERIFICATION_TOKEN_SECRET`;
- `PRODUCT_IDENTITY_PROOF_UPLOAD_SECRET`.

Existing generated values are preserved on future reconciliations.

## Frontend API wiring

AppFactory resolves the existing `product-identity` Cloudflare Pages project and writes its non-secret build variable:

`VITE_API_BASE_URL=https://product-identity-api.<account>.workers.dev`

This keeps the frontend and backend deployment relationship reproducible without putting Cloudflare credentials in GitHub.

## Database fail-closed rule

The Worker is allowed to exist before the PostgreSQL binding is ready, but production database routes are not allowed to fall back to ephemeral SQLite.

When a production Cloudflare Worker has no Hyperdrive/PostgreSQL URL:
- `/health` reports `status=degraded`;
- `database_configured=false`;
- any endpoint that requests a database session returns HTTP 503.

Once Hyperdrive is bound, `app/core/runtime.py` builds the PostgreSQL SQLAlchemy URL from the binding and the same application becomes database-ready.

Hyperdrive owns pooling; SQLAlchemy uses `NullPool` in Worker runtime to prevent stale connections from crossing Worker request contexts.

## Shopify deployment

After AppFactory returns the real Worker URL and the Worker is reachable, the same workflow renders the existing Shopify production template and runs:

```text
shopify app deploy --config production --allow-updates
```

using `SHOPIFY_APP_AUTOMATION_TOKEN`.

Shopify CLI deploys Shopify app configuration. It does not deploy FastAPI.

## Current database step

Cloudflare deployment no longer waits for a repository-level Cloudflare token.

The remaining infrastructure dependency is a Product Identity PostgreSQL origin for Hyperdrive. This must be a Product Identity database/role, not a reused application database from another Trigenys product.

Until that binding exists, the Worker stays explicitly degraded rather than using SQLite.

## Current proof-storage limitation

The existing proof-of-purchase adapter is S3/boto3 based. Boto3 remains a server-only optional dependency and is deliberately not bundled into the Worker.

Proof upload/download therefore stays unavailable on the Worker until an R2-native adapter is implemented. The rest of the Product Identity domain can still be deployed and exercised as its dependencies become available.

## Custom domain later

The first deployment uses the account's `workers.dev` hostname. After end-to-end validation, the Worker can be attached to:

`https://api.identity.trigenys.com`

without changing the application boundary.
