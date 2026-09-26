# Product Identity API

FastAPI backend for the Product Identity SaaS.

## Local development

```bash
cd backend
python -m venv .venv
# activate the virtualenv for your shell
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

The production database is PostgreSQL. SQLite is supported for local/test execution only.

## Authentication boundary

The API validates externally issued JWTs. It does not own passwords, MFA or password recovery.

A JWT subject maps to an internal `User`; authorization is controlled by internal `Membership` records scoped to an `Organization`.

An authenticated external subject that has not been provisioned is denied rather than silently creating an account.

## Tests

```bash
pytest
```

Coverage currently includes public health, bearer-token enforcement, unknown-subject denial, organization membership projection, cross-tenant denial and fresh-database migration.
