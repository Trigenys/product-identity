from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_migrations_create_fresh_database(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv("PRODUCT_IDENTITY_DATABASE_URL", database_url)

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    inspector = inspect(create_engine(database_url))
    expected_tables = {
        "users",
        "organizations",
        "memberships",
        "products",
        "serialization_batches",
        "units",
        "unit_imports",
        "verification_events",
        "warranty_policies",
        "product_registrations",
        "registration_audits",
        "proofs_of_purchase",
        "authenticity_signals",
        "shopify_installations",
        "shopify_oauth_states",
        "shopify_product_maps",
        "shopify_order_maps",
        "shopify_order_line_maps",
        "shopify_webhook_deliveries",
    }
    assert expected_tables.issubset(set(inspector.get_table_names()))
