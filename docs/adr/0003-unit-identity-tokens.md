# ADR 0003 — Canonical identity and public verification tokens

- Status: Accepted
- Date: 2026-09-26
- Issues: #6, #7, #9, #11

## Context

Human-readable serial numbers can be copied, photographed or enumerated. They are useful identifiers but are not secrets and cannot safely be the sole credential behind a public authenticity response.

## Decision

Each physical Unit has:
- an immutable internal UUID;
- a human-readable serial governed by a tenant/product serial policy;
- an independent opaque verification token with high entropy.

QR codes encode a public URL containing the verification token, not the internal Unit UUID and not a sequential database key.

Verification tokens are stored in a representation suitable for lookup without exposing raw secrets in logs. Rotation/revocation is part of the token lifecycle model.

A successful token lookup establishes that the token was issued by Product Identity for a known Unit. It does **not** prove that the physical object carrying a copied QR is genuine.

## Consequences

The public API can distinguish:
- valid/active token;
- revoked token;
- unknown token;

without disclosing customer ownership information.

Repeated scans or geographically implausible patterns may become authenticity signals, never automatic counterfeit verdicts.
