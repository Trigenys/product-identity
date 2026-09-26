# ADR 0001 — Service architecture and persistence

- Status: Accepted
- Date: 2026-09-26
- Issue: #6

## Context

Product Identity must support a public verification surface, a merchant application, batch serialization and multiple commerce connectors while keeping the canonical unit identity independent of Shopify.

The product is still pre-MVP. The architecture must therefore be production-capable without introducing a distributed-system tax before there is validated demand.

## Decision

Use a modular monolith for the first production milestone:

- React/TypeScript for merchant and public web surfaces;
- FastAPI/Python for the application API;
- PostgreSQL as the primary system of record;
- SQLAlchemy 2.x for persistence and Alembic for migrations;
- S3-compatible object storage for protected purchase evidence;
- bounded asynchronous jobs only where operations are genuinely long-running;
- channel adapters at the application boundary.

The backend is organized by domain/application/infrastructure boundaries rather than by external platform.

No microservice is introduced until an observed scaling, security-isolation or deployment requirement justifies it.

## Rationale

FastAPI and PostgreSQL match the current Trigenys engineering stack, provide mature ecosystem support, and keep operational overhead low. A modular monolith gives us explicit boundaries without forcing distributed transactions, queues and cross-service observability into the MVP.

## Consequences

Positive:
- one deployable backend;
- transactional integrity for identity/warranty operations;
- low infrastructure cost;
- straightforward local development and testing;
- later extraction of adapters/workers remains possible.

Negative:
- modules must enforce boundaries in code review rather than process isolation;
- CPU-heavy or latency-sensitive workloads may eventually need dedicated workers.

## Invariants

- Shopify/Amazon identifiers never become canonical Unit IDs.
- Public verification data and private merchant/customer data remain separate views.
- Tenant ownership is explicit on merchant-controlled records.
- Idempotency is required at external-event and batch-operation boundaries.
