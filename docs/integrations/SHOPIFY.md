# Shopify Connector

Issue: #16

Shopify is Product Identity's first commerce connector. It is **not** the source of truth for physical unit identity.

## Boundary

Shopify owns commerce records such as products, variants and orders.

Product Identity owns:
- canonical Product records;
- physical Unit identities;
- serials and verification tokens;
- registrations and warranty state;
- authenticity evidence.

A Shopify order line may reference a canonical Product. It does not automatically create or assign a physical Unit because an order does not prove which serialized unit was shipped.

## Least privilege

Requested Admin scopes:

- `read_products`
- `read_orders`

The connector does not request product/order write scopes.

The initial product sync uses Admin GraphQL and only reads:
- product ID/title/handle;
- variant ID/SKU.

Order ingestion is webhook-driven in the MVP and persists no Shopify customer PII.

Because `read_orders` is an order-data scope, public App Store distribution can still require Shopify protected-customer-data review even though Product Identity deliberately does not persist customer names, email, phone or addresses from Shopify.

## OAuth

Product Identity is a standalone app and uses Shopify's authorization-code grant.

Install initiation:
1. authenticated owner/admin chooses a `*.myshopify.com` shop;
2. server validates the domain;
3. server creates a high-entropy one-time OAuth state;
4. only the SHA-256 state digest is persisted;
5. merchant is redirected to Shopify.

Callback:
1. validates callback HMAC with the app client secret;
2. validates and consumes state exactly once;
3. exchanges the code with `expiring=1`;
4. checks that required scopes were granted;
5. encrypts access + refresh tokens before persistence.

Public apps use expiring offline tokens. Product Identity refreshes shortly before expiry and rotates both access and refresh tokens. If the refresh token has expired, the installation becomes `reauth_required`.

## Token storage

Runtime Shopify access/refresh tokens are encrypted with Fernet using:

`PRODUCT_IDENTITY_SHOPIFY_TOKEN_ENCRYPTION_KEY`

The encryption key must be stored outside the database in the runtime secret manager.

The Shopify App Automation Token used by GitHub Actions is unrelated to merchant Admin API tokens and is stored only as the GitHub Actions secret:

`SHOPIFY_APP_AUTOMATION_TOKEN`

## Product mapping

Each Shopify variant with a non-empty SKU maps to exactly one canonical Product.

If the organization already has that SKU, the connector links to it.

If no canonical Product exists, sync creates one using Shopify product title + variant SKU.

A variant without SKU is skipped rather than inventing an unstable identifier.

Deleting a Shopify product marks channel mappings deleted. It does **not** delete the canonical Product.

## Order mapping

Order webhooks persist:
- Shopify order GID;
- order display name;
- cancellation timestamp;
- line-item GID;
- SKU;
- quantity;
- optional canonical Product ID;
- optional Unit ID reserved for a future explicit fulfillment/serial assignment workflow.

The connector intentionally does not persist Shopify customer:
- email;
- phone;
- name;
- billing/shipping addresses.

## Webhooks

HTTPS webhook delivery requires:
- HMAC-SHA256 validation on the raw body;
- `X-Shopify-Webhook-Id` persistence for deduplication.

Supported topics:
- `app/uninstalled`;
- `app/scopes_update`;
- `products/create`;
- `products/update`;
- `products/delete`;
- `orders/create`;
- `orders/updated`;
- `orders/cancelled`;
- mandatory privacy topics.

Only the payload SHA-256 digest is stored. Raw webhook payloads are not persisted.

Client-secret rotation can temporarily validate both current and previous secrets through:
- `PRODUCT_IDENTITY_SHOPIFY_CLIENT_SECRET`;
- `PRODUCT_IDENTITY_SHOPIFY_PREVIOUS_CLIENT_SECRET`.

## Privacy lifecycle

`customers/data_request` and `customers/redact` are verified and acknowledged. The connector stores no Shopify customer record/PII to export or erase.

`app/uninstalled` immediately:
- marks the installation uninstalled;
- removes encrypted merchant access/refresh tokens.

`shop/redact` removes Shopify-specific:
- installation;
- product mappings;
- order mappings;
- webhook delivery metadata.

Canonical Product/Unit identity remains intact because it belongs to Product Identity, not Shopify.

## CI/CD

Tracked source:

`shopify.app.production.toml.template`

GitHub Actions renders the real `shopify.app.production.toml` from:
- repository variable `SHOPIFY_CLIENT_ID`;
- repository variable `SHOPIFY_APP_URL`.

Deployment uses:
- secret `SHOPIFY_APP_AUTOMATION_TOKEN`;
- `shopify app deploy --config production --allow-updates`.

The deploy job is skipped until `SHOPIFY_APP_URL` exists. This prevents CI from publishing a placeholder callback/webhook domain.

Shopify CLI deploys Shopify app configuration/extensions. It does not deploy the FastAPI/React application itself.

## RAIDER / failure memory

Lessons captured during bootstrap:

1. Do not run Shopify project commands from `C:\Windows\System32`; configuration belongs at repository root.
2. Do not scaffold a second Shopify React application when the product already has a deliberate FastAPI + React architecture.
3. App Automation Tokens remove recurring local CLI dependency from release operations.
4. Never convert Shopify orders directly into serialized Units without evidence of the physical unit shipped.
5. Never persist entire webhook payloads when a narrow projection is enough.
