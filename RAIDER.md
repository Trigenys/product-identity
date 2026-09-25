# RAIDER

Product Identity follows the Trigenys RAIDER engineering standard.

## R — Reusable
Capabilities should be reusable across channels and products. The identity core must work without Shopify-specific assumptions.

## A — Agnostic
Core contracts model Brand, Product, Unit, Serial, Registration, Warranty and Verification Event. Channel adapters translate Shopify, Amazon, POS, CSV or API data into those contracts.

## I — Idempotent
Imports, webhook processing, serial generation requests, registration operations and deployment/reconciliation jobs must be safe to retry.

## D — Durable / non-regressive
Behavior changes require regression coverage. Backward compatibility of identifiers, public verification URLs and imported unit records is treated as a product invariant.

## E — Engineering-grade
Explicit contracts, least privilege, observability, migrations, tests, privacy boundaries, threat modelling and rollback/forward-fix paths are required for production work.

## R — Retroactive
A newly discovered failure mode is not fixed only locally. The lesson must be generalized into a test, guardrail, reusable pattern, documentation rule or AppFactory improvement where appropriate.

## Reuse-first loop
Observe -> select -> internalize -> standardize -> automate -> reuse.

For new capabilities, evaluate: Adopt / Adapt / Learn / Build. Building from scratch is the last option.

## Failure memory
Every meaningful incident or near miss should capture:
1. symptom;
2. root cause;
3. resolution;
4. prevention;
5. generalized lesson;
6. new test/guardrail/sub-principle.
