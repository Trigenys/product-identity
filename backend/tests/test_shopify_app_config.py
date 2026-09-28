from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2] / "shopify.app.production.toml.template"


def _template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_production_shopify_config_avoids_unapproved_protected_order_webhooks() -> None:
    text = _template()

    assert '"products/create"' in text
    assert '"products/update"' in text
    assert '"products/delete"' in text

    assert '"orders/create"' not in text
    assert '"orders/updated"' not in text
    assert '"orders/cancelled"' not in text

    assert '"customers/data_request"' in text
    assert '"customers/redact"' in text
    assert '"shop/redact"' in text


def test_production_shopify_config_avoids_removed_cli_field() -> None:
    assert "include_config_on_deploy" not in _template()
