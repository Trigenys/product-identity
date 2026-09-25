# Architecture

## Principle

The core owns product identity. Commerce platforms are adapters.

## Proposed production shape

- Merchant web UI: React/TypeScript.
- Public verification/registration UI: lightweight web surface optimized for QR entry.
- API: FastAPI/Python unless an ADR establishes a stronger reason to use another runtime.
- Primary database: PostgreSQL.
- Object storage: proof-of-purchase images/documents with signed access.
- Background work: bounded job queue for batch serial generation/import/export and connector sync.
- Shopify: OAuth + Admin GraphQL + webhooks through a dedicated adapter.
- Observability: structured logs, error tracking and business-event metrics.

## Core boundaries

Brand -> Product -> Unit -> Identifier/Token -> Registration -> Warranty -> VerificationEvent.

No Shopify order ID is a primary domain identifier.

## Security

A public QR should resolve through an opaque verification token; raw sequential identifiers are not sufficient authentication. Verification responses expose product/authenticity state only, never owner PII.

High-volume duplicate scan patterns are signals, not automatic proof of counterfeiting.

## Tenancy

Every merchant-owned record carries an organization boundary. Cross-tenant access is forbidden by default and tested.

## Idempotency

Required for:
- Shopify webhooks;
- order/import reconciliation;
- batch serial generation requests;
- product registration retries;
- usage/billing events.

## Expansion boundary

Amazon, WooCommerce, POS, DPP and claims are adapters/modules added after validated demand. They must not change the canonical unit identity model.
