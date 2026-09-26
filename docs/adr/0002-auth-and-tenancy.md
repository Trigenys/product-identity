# ADR 0002 — Authentication and tenant authorization

- Status: Accepted
- Date: 2026-09-26
- Issues: #6, #8

## Context

The SaaS needs organization-scoped access but should not implement password storage, password reset, MFA and account recovery from scratch.

Shopify OAuth is a channel authorization mechanism and must not become the general Product Identity user identity system.

## Decision

Use standards-based OIDC/JWT authentication behind an internal authentication adapter.

The API accepts bearer access tokens issued by a configured OIDC provider. It validates signature, issuer, audience and temporal claims. The external subject claim maps to an internal User record.

Authorization is internal and database-backed:

User -> Membership -> Organization.

Roles are initially:
- owner;
- admin;
- member;
- viewer.

The provider is intentionally not hard-coded in the domain. Local/test environments may use a deterministic test issuer/keypair.

## Consequences

- We reuse mature identity providers rather than storing passwords.
- Provider migration is possible because organization membership is internal.
- API tests can validate authorization independently of a hosted auth provider.
- Shopify stores can later link to an Organization without conflating store ownership and user identity.

## Security requirements

- issuer and audience are mandatory;
- expired/not-yet-valid tokens fail closed;
- unknown subjects do not gain organization access automatically;
- membership checks occur inside tenant-scoped services;
- public verification endpoints do not require or expose merchant authentication.
