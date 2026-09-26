# Merchant Product-Unit Registry

Issue: #15

The registry is the operational surface for brands managing issued physical product identities.

## Access boundary

The registry requires:
- a valid OIDC/JWT merchant session;
- membership in the requested organization;
- role `owner`, `admin` or `member`.

A tenant identifier supplied by the browser never grants access by itself.

The frontend intentionally does not implement a temporary password or token-in-URL login. It consumes the existing authentication contract and shows a session-required state until the dedicated auth provider UX is connected.

## Registry list

The registry supports:
- search by serial;
- search by product name;
- search by SKU;
- unit status filters;
- registration filters;
- warranty-state filters;
- summary counts;
- verification counts;
- open authenticity-signal counts.

All database queries are scoped to the authenticated organization.

Warranty filtering is performed before pagination so counts and pages remain correct.

## Unit detail

A unit detail contains:
- canonical unit/product identity;
- customer registration for authorized merchant roles;
- warranty state;
- verification count;
- open authenticity-signal count;
- chronological timeline.

## Timeline provenance

Timeline items are explicitly classified as:

### Fact

Source facts include:
- unit issuance;
- product registration;
- registration correction;
- public verification scans.

### Derived

Derived entries currently include:
- authenticity anomaly signals.

A derived signal is never styled or described as a confirmed counterfeit finding.

## Bulk actions

No destructive bulk action is exposed in this milestone.

This is deliberate. Revocation, deletion or ownership-changing bulk operations require:
- explicit authorization policy;
- preview;
- confirmation;
- idempotency;
- audit evidence;
- partial-failure semantics.

Safe bulk/export workflows can be added separately once those invariants are defined.

## Responsive behavior

Desktop uses a split list/detail workspace.

Tablet and mobile keep the unit list as the primary surface and open unit detail as an overlay. Search, filters and organization switching remain available at reduced widths.

## Frontend session contract

The current merchant shell reads the access token from session storage key:

`product-identity:access-token`

and resolves organizations through `GET /v1/me`.

This is a frontend integration boundary, not a new authentication system. The future OIDC callback flow owns how that session token is established and refreshed.
