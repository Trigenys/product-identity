# Threat Model — Product Identity MVP

- Status: Baseline accepted for MVP
- Date: 2026-09-26
- Issue: #7

## 1. Scope

This threat model covers the MVP boundaries:

- merchant authentication and tenant access;
- Products and physical Units;
- serial numbers;
- opaque public verification tokens / QR codes;
- public authenticity verification;
- product registration and warranty state;
- protected proof-of-purchase uploads;
- Shopify OAuth/webhooks and future channel adapters;
- operational logs and analytics.

It does not claim to solve physical anti-counterfeiting. A valid Product Identity token proves that a digital identity was issued; it does not prove that a QR label was not copied onto another physical object.

## 2. Assets

Highest-value assets:

1. Organization/tenant data and membership.
2. Canonical Unit identities.
3. Serial-to-Unit mapping.
4. Verification tokens and revocation state.
5. Customer registration PII.
6. Proof-of-purchase files.
7. Warranty decisions/history.
8. Shopify credentials and webhook trust.
9. Audit/event history.
10. Usage/billing events.

## 3. Trust boundaries

```text
Untrusted public browser / QR scanner
          |
          | opaque token
          v
Public Verification API
          |
          | restricted projection
          v
Identity Core / PostgreSQL
          ^
          |
Merchant API <--- OIDC JWT ---> Merchant Browser
          ^
          |
Channel Adapter <--- signed webhook / OAuth ---> Shopify
          |
          v
Protected object storage
```

Public verification, merchant operations and channel ingestion are distinct trust boundaries.

## 4. Threats and required controls

### T1 — Serial enumeration

**Threat:** an attacker guesses sequential/human serial numbers and queries the system to learn inventory or registration data.

**Controls:**
- serial is not a public authorization secret;
- public verification uses an independent high-entropy opaque token;
- public endpoints do not provide search-by-serial unless explicitly protected;
- rate-limit repeated unknown-token requests.

**Tests:** unknown random tokens return a uniform public response and never expose PII.

### T2 — Copied QR label

**Threat:** a genuine QR is copied and attached to a counterfeit unit.

**Controls:**
- communicate verification as digital-identity verification, not physical proof;
- record privacy-minimized verification events;
- flag abnormal scan frequency/patterns;
- support token revocation/rotation;
- preserve merchant-visible scan history.

**Tests:** repeated-scan anomaly logic must not auto-label an item counterfeit.

### T3 — Token database leakage

**Threat:** database/log exposure reveals usable public verification tokens.

**Controls:**
- do not write raw tokens to application logs;
- store a keyed/hashed lookup representation where feasible;
- only show raw token at creation/export boundary;
- redact URLs/tokens in error telemetry.

**Tests:** log snapshots contain no raw verification tokens.

### T4 — Cross-tenant authorization failure

**Threat:** a member of Brand A reads or mutates Brand B data by changing an ID.

**Controls:**
- organization ID is explicit on merchant-owned aggregates;
- membership authorization occurs before repository/service access;
- all repository queries are tenant-scoped;
- never trust tenant IDs supplied by the browser without membership validation.

**Tests:** matrix tests for read/write attempts across organizations.

### T5 — Forged registration

**Threat:** an attacker claims a Unit they do not own.

**Controls:**
- registration starts only from a valid Unit/token;
- registration is auditable and reversible by authorized merchant users;
- proof-of-purchase may be required by policy;
- future purchase-channel matching is evidence, not silent ownership transfer;
- rate limits and idempotency protect registration retries.

**Tests:** duplicate registration attempts follow deterministic policy.

### T6 — PII leakage through verification

**Threat:** scanning a QR reveals owner identity, order number, address or warranty evidence.

**Controls:**
- public response is a dedicated projection;
- no owner/order PII fields in public response schema;
- merchant-only registration endpoint returns protected fields;
- error responses do not reveal whether a named customer exists.

**Tests:** schema tests assert forbidden fields are absent.

### T7 — Malicious proof-of-purchase upload

**Threat:** uploaded files carry active content, oversized payloads or unsafe filenames.

**Controls:**
- strict byte-size and content-type allowlist;
- random object keys;
- private bucket by default;
- signed/short-lived downloads;
- do not render arbitrary HTML/SVG inline;
- future malware scanning gate before broader file types.

**Tests:** reject disallowed types, oversized files and path-like names.

### T8 — Shopify webhook forgery/replay

**Threat:** forged or repeated webhooks create/modify records.

**Controls:**
- verify Shopify webhook signature before parsing business payload;
- persist event/topic identity needed for idempotency;
- make handlers replay-safe;
- reject timestamps/events outside documented policy where platform metadata permits;
- use least-privilege Admin API scopes.

**Tests:** invalid signatures fail; repeated valid event produces one state transition.

### T9 — OAuth/token compromise

**Threat:** leaked Shopify or OIDC credentials provide persistent access.

**Controls:**
- secrets are external to source control;
- encryption at rest for channel credentials;
- never expose provider tokens to browser after exchange;
- revoke/delete credentials on uninstall;
- rotate operational secrets with documented procedure.

### T10 — Mass verification abuse / denial of service

**Threat:** automated scans exhaust database/compute or create noisy anomaly data.

**Controls:**
- per-IP/token/global rate-limit layers;
- bounded event metadata;
- cache safe public projections where appropriate;
- separate verification success from analytics persistence if analytics is degraded.

**Tests:** throttling does not corrupt Unit state.

### T11 — IDOR on proof or registration resources

**Threat:** authenticated user swaps a proof/registration ID to retrieve another organization’s data.

**Controls:**
- child-resource lookups include organization ownership;
- signed object URLs are only minted after authorization;
- opaque IDs are defense-in-depth, not authorization.

### T12 — Spreadsheet/CSV injection

**Threat:** exported serials or imported merchant data execute formulas when opened in spreadsheet tools.

**Controls:**
- neutralize formula-leading values in exports where content can be attacker-controlled;
- validate/normalize imports;
- document that serial policy cannot create unsafe spreadsheet formulas.

### T13 — Sensitive analytics collection

**Threat:** verification telemetry becomes a location/device tracking product unintentionally.

**Controls:**
- collect only data tied to an explicit abuse/operations use case;
- coarse or derived location only when lawful and needed;
- retention limits;
- no fingerprinting as an MVP requirement;
- document privacy purpose for every field.

### T14 — Unsupported authenticity/compliance claims

**Threat:** product copy promises "counterfeit-proof", "guaranteed authentic", or regulatory compliance beyond technical evidence.

**Controls:**
- copy review is part of Proof of Done;
- API states are factual: valid token, unknown token, revoked token, anomaly signal;
- DPP/regulatory compliance remains a separate legal/compliance workstream.

## 5. Public response contract

The public verification response may expose only information intended to be public, for example:

- verification state;
- brand display name;
- product display name/model;
- serial display only if brand policy allows it;
- warranty registration CTA/state that does not identify the owner;
- non-conclusive advisory when suspicious scan behavior exists.

It must not expose:

- customer name/email/address;
- merchant internal notes;
- order number unless explicitly designed and justified;
- proof-of-purchase URL;
- channel OAuth data;
- internal Unit UUID;
- raw database identifiers.

## 6. Severity priorities

P0 before beta:
- tenant isolation;
- OIDC validation;
- public PII projection;
- opaque token design;
- Shopify webhook validation;
- private object storage;
- rate limits for public verification.

P1 during MVP:
- duplicate-scan anomaly signals;
- retention/deletion controls;
- credential rotation runbook;
- upload malware scanning if file scope expands.

## 7. Security test map

| Control | Implementation issue |
| --- | --- |
| Tenant isolation / auth | #8, #21 |
| Serial + token invariants | #9, #21 |
| Public projection / rate limits | #11, #21 |
| Registration idempotency | #12, #21 |
| Protected proofs | #13, #21 |
| Scan anomalies | #14 |
| Shopify signature/replay | #16, #21 |
| Observability redaction | #20, #21 |

## 8. Residual risk

The largest unavoidable MVP residual risk is physical QR copying. Product Identity can detect suspicious digital behavior and let brands manage issued identities, but cannot guarantee physical authenticity without stronger physical security controls such as tamper-evident labels, hidden codes, secure NFC or manufacturing-chain attestations.
