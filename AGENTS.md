# Engineering contract

This repository is provisioned by Trigenys AppFactory and governed by AppFactory Project Automation.

## Product boundary

Product Identity gives individual physical product units a durable digital identity. The validated MVP boundary is:

serial / QR generation -> public authenticity verification -> product registration -> warranty state.

Claims, repair workflows, Amazon, WooCommerce, DPP compliance and supply-chain traceability are expansion tracks, not MVP assumptions.

## Engineering rules

- Apply RAIDER: Reusable, Agnostic, Idempotent, Durable/non-regressive, Engineering-grade, Retroactive.
- Search and evaluate existing standards, libraries and platform primitives before building custom infrastructure.
- Preserve channel independence in the core domain: Shopify is the first connector, not the source of truth.
- Treat serials, QR tokens, proofs of purchase and customer data as security-sensitive.
- Public verification must not expose private owner or order data.
- Every state-changing endpoint must be retry-safe or explicitly idempotent.
- Never commit credentials, customer data, private keys or production exports.
- Add tests for behavior changes and regression fixes.
- Link implementation pull requests to the relevant GitHub Issue.
- Record incidents and reusable lessons in `docs/engineering/lessons-learned.md`.
- Keep Project Automation configuration intact unless the platform contract is intentionally upgraded.
