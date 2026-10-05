"""Tests for the project templates BuffStack generates."""

from __future__ import annotations

import ast
import json
import re

import pytest

from buffstack import templates

FIELDS = [
    {"name": "title", "type": "string", "required": True},
    {"name": "amount", "type": "float", "required": True},
]

VALUES = {
    "PROJECT_NAME": "Expense Tracker",
    "TITLE": "Expense Tracker",
    "SUBTITLE": "Track spending",
    "ENTITY_SINGULAR": "expense",
    "ENTITY_PLURAL": "expenses",
    "ENTITY_PLURAL_TITLE": "Expenses",
    "PORT": 12000,
    "STATIC_PREFIX": "",
    "API_ENDPOINT": "/api/expenses",
    "REFRESH_MS": 0,
    "COLUMNS_JSON": "[]",
    "FIELDS_JSON": "[]",
    "REQUIRED_FIELDS_JSON": templates.json_literal(templates.required_fields(FIELDS)),
    "SAMPLE_PAYLOAD_JSON": templates.json_literal(templates.sample_payload(FIELDS)),
}


def test_render_leaves_no_placeholder_behind():
    rendered = templates.render("a {{X}} b {{Y}}", X=1, Y="two")
    assert rendered == "a 1 b two"
    assert "{{" not in rendered


@pytest.mark.parametrize(
    "name",
    ["APP_PY", "DASHBOARD_HTML", "DASHBOARD_JS", "DASHBOARD_CSS", "RUN_SH", "TEST_API_PY"],
)
def test_no_template_ships_an_unfilled_placeholder(name: str):
    """A missing value must fail loudly here, not in the generated project."""
    rendered = templates.render(getattr(templates, name), **VALUES)
    leftovers = re.findall(r"\{\{[A-Z_]+\}\}", rendered)
    assert not leftovers, f"{name} still contains {leftovers}"


def test_app_template_is_valid_python():
    source = templates.render(templates.APP_PY, **VALUES)
    ast.parse(source)
    assert "def create_app(" in source
    assert re.search(r"^app\s*=\s*create_app\(\)", source, re.M)


def test_app_template_keeps_the_route_marker():
    source = templates.render(templates.APP_PY, **VALUES)
    assert "# BUFFSTACK:ROUTES" in source


def test_app_template_has_the_expected_routes():
    source = templates.render(templates.APP_PY, **VALUES)
    for route in ['"/health"', '"/"', '"/api/expenses"']:
        assert route in source


def test_dashboard_template_references_the_script_and_binds_ids():
    html = templates.render(templates.DASHBOARD_HTML, **VALUES)
    assert "dashboard.js" in html
    for element_id in ["status-pill", "create-form", "table-body", "search"]:
        assert f'id="{element_id}"' in html


def test_dashboard_script_is_live():
    js = templates.render(templates.DASHBOARD_JS, **VALUES)
    assert "fetch(" in js
    assert "/api/expenses" in js


def test_dashboard_script_embeds_columns_and_fields():
    js = templates.render(
        templates.DASHBOARD_JS,
        **{
            **VALUES,
            "COLUMNS_JSON": templates.json_literal([{"key": "id", "label": "ID"}]),
            "FIELDS_JSON": templates.json_literal([{"name": "title", "label": "Title"}]),
        },
    )
    assert '{"key": "id", "label": "ID"}' in js
    assert '{"name": "title", "label": "Title"}' in js


def test_dashboard_columns_lead_with_id():
    columns = templates.dashboard_columns([{"name": "amount", "type": "float"}])
    assert columns[0] == {"key": "id", "label": "ID"}
    assert {"key": "amount", "label": "Amount"} in columns


def test_dashboard_fields_carry_type_and_required():
    fields = templates.dashboard_fields(
        [{"name": "amount", "type": "float", "required": True}]
    )
    assert fields == [
        {"name": "amount", "label": "Amount", "type": "float", "required": True}
    ]


def test_required_fields_only_lists_required_ones():
    assert templates.required_fields(FIELDS) == ["title", "amount"]
    assert templates.required_fields([{"name": "note", "type": "string"}]) == []


def test_sample_payload_is_valid_json_and_covers_every_field():
    payload = templates.sample_payload(FIELDS)
    assert set(payload) == {"title", "amount"}
    json.dumps(payload)  # must be embeddable in the generated test file


def test_generated_test_file_posts_a_valid_body():
    source = templates.render(templates.TEST_API_PY, **VALUES)
    assert '"title": "smoke"' in source
    assert '"amount": 1.0' in source


def test_run_sh_exports_the_port_to_the_app():
    script = templates.render(templates.RUN_SH, **VALUES)
    assert "export PORT" in script
    assert script.index("export PORT") < script.index("python app.py")


def test_test_template_compiles():
    source = templates.render(templates.TEST_API_PY, **VALUES)
    ast.parse(source)
