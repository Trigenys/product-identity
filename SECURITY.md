# Security Policy

Product Identity handles serials, verification tokens, proofs of purchase and customer registration data.

## Reporting

Security findings should be disclosed privately to the Trigenys maintainers. Do not publish exploitable details before a fix is available.

## Baseline controls

- least-privilege platform scopes;
- tenant isolation;
- opaque public verification tokens;
- secrets outside source control;
- signed/expiring access to protected proof files;
- webhook signature verification;
- idempotent replay handling;
- rate limits and abuse controls on public verification;
- no owner/order PII in public authenticity responses;
- auditability for security-sensitive changes.

Unsupported claims such as "counterfeit-proof" or "guaranteed authentic" must not appear in product copy unless technically and legally substantiated.
