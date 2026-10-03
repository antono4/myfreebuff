"""Tests for the project templates BuffStack generates."""

from __future__ import annotations

import ast
import re

from buffstack import templates

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
}


def test_render_replaces_every_placeholder():
    rendered = templates.render("a {{X}} b {{Y}}", X=1, Y="two")
    assert rendered == "a 1 b two"


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


def test_test_template_compiles():
    source = templates.render(templates.TEST_API_PY, **VALUES)
    ast.parse(source)
