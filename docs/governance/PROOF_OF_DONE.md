# Proof of Done

Every issue must satisfy its acceptance criteria and the applicable checks below.

## Universal
- [ ] Scope matches the issue; unrelated work is split.
- [ ] Tests cover new behavior and regressions where relevant.
- [ ] Documentation/contracts are updated.
- [ ] Security/privacy implications are reviewed.
- [ ] Observability is added for production-relevant failure modes.
- [ ] PR links the issue and includes evidence.
- [ ] RAIDER impact is assessed: reuse, idempotency, durability and retroactive lessons.
- [ ] A repeated or novel failure mode is added to Failure Memory.

## Product / UX
- [ ] Empty, loading, error and success states are defined.
- [ ] Keyboard and basic accessibility are checked.
- [ ] No private customer/order data leaks to public verification.
- [ ] Copy does not make unsupported legal, anti-counterfeit or compliance claims.

## Data / API
- [ ] Schema/migration is versioned.
- [ ] State-changing operations are idempotent or have explicit retry semantics.
- [ ] Tenant boundaries are tested.
- [ ] Audit-relevant events have stable timestamps/identifiers.
- [ ] Secrets/tokens are never logged.

## Market / Growth
- [ ] Target segment and hypothesis are explicit.
- [ ] Contact data is business-public or permissioned; no prohibited scraping.
- [ ] Outcomes are measured, including negative evidence.
- [ ] Ads have a defined budget cap, conversion event and stop condition.
- [ ] Learning is written back into ICP, pricing or product decisions.

## Release
- [ ] CI passes.
- [ ] Rollback/forward-fix path is known.
- [ ] Production config is documented without exposing secrets.
- [ ] Smoke test covers the primary user journey.
