# Product Identity

**Digital identity for every physical product unit.**

Product Identity is a Trigenys product for brands that need to serialize physical products, verify authenticity, register ownership and warranties, and keep one durable identity across commerce channels.

> Status: **pre-MVP / market validation**. The repository intentionally separates validated scope from future expansion.

## Problem

A SKU tells a brand what a product model is. It does not reliably answer:
- Which exact unit was manufactured or sold?
- Is this serial authentic?
- Who registered the unit and when?
- When does its warranty expire?
- Was the same QR/serial scanned suspiciously often?
- Was the unit sold through Shopify, Amazon, retail or a distributor?

Many growing hardware and durable-goods brands still bridge these questions with spreadsheets, forms, email and disconnected commerce systems.

## MVP

The first product loop is deliberately narrow:

1. create/import products;
2. generate unique serials and secure verification tokens;
3. export printable QR/serial assets;
4. let a buyer scan and verify authenticity;
5. let the buyer register the product and proof of purchase;
6. calculate/display warranty state;
7. give the brand a searchable unit registry and basic verification signals.

**Not MVP:** full RMA/helpdesk, repair-center ERP, DPP compliance claims, Amazon/WooCommerce connectors, resale marketplace or supply-chain tracking.

## Initial customer profile

Primary targets are small and mid-size DTC hardware / durable-goods brands selling products where the individual unit matters:

- consumer electronics and audio;
- e-bikes, scooters and mobility products;
- automotive aftermarket equipment;
- tools and professional equipment;
- 3D printers and maker hardware;
- premium beauty devices;
- fitness/sports equipment;
- watches, jewelry and counterfeit-sensitive goods;
- premium furniture/appliances with meaningful warranties.

The strongest buying signal is a brand selling through multiple channels while managing serials, warranty registration or proof-of-purchase manually.

## Product principles

- **Unit-first:** identity belongs to the physical unit, not to an order or sales channel.
- **Channel-agnostic core:** Shopify is the first distribution wedge, never the system of record.
- **Self-service first:** avoid consulting-heavy custom workflows.
- **Privacy by design:** public verification never reveals private owner/order data.
- **Secure by default:** a visible serial alone is not considered sufficient proof of authenticity.
- **Evidence over assumptions:** expansion is gated by customer discovery and usage.

## Planned architecture

```text
Shopify / CSV / API / future channels
               |
        Channel adapters
               |
        Product Identity API
               |
  --------------------------------
  | Brand / Product / Unit       |
  | Serial / Verification Token  |
  | Registration / Warranty      |
  | Verification Event           |
  --------------------------------
               |
        PostgreSQL + object storage
               |
     Merchant UI / Public Verify
```

The current AppFactory landing seed is retained for market validation while the application architecture is implemented behind explicit issues and ADRs.

## Delivery

This repository uses:
- Trigenys AppFactory for provisioning;
- AppFactory Project Automation for GitHub Projects v2 lifecycle;
- workflow: **Backlog -> Ready -> In Progress -> Review -> Validation -> Done**;
- priorities P0-P3, sizes XS-XL and explicit phases;
- PERT dependencies in issue bodies;
- RAIDER engineering governance and Failure Memory.

See:
- `RAIDER.md`
- `docs/planning/PERT.md`
- `docs/governance/PROOF_OF_DONE.md`
- `docs/market/VALIDATION_AND_GTM.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/DOMAIN_MODEL.md`

## Validation gates

Development is not the primary success metric.

Before broadening beyond the identity MVP, the project must obtain:
- repeated evidence of the same workflow pain from target brands;
- at least two credible design/pilot partners;
- measurable activation from serial creation to successful public verification/registration;
- willingness to pay at a price compatible with a self-service SaaS.

## Commercial hypothesis

Initial pricing hypothesis, to validate rather than assume:
- Starter: **$19/month**
- Growth: **$49/month**
- Scale: **$99/month**

Plans should ultimately be driven by serialized unit volume, registrations and team/automation needs rather than arbitrary feature withholding.

## Repository

Private during validation and product formation. Public-facing marketing, App Store listing and documentation are separate deliverables governed by the Growth backlog.

---

**Trigenys Group** — Designing the systems behind decisions.
