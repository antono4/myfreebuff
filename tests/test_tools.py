"""Tests for the full-stack tools, driven through their real executors.

The tests scaffold a real project in a tmp directory, run the tools against it,
and exercise the generated Flask app through its own test client.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from buffstack.tools.add_endpoint import AddEndpointAction, AddEndpointExecutor
from buffstack.tools.dashboard import (
    CreateDashboardAction,
    CreateDashboardExecutor,
    DashboardColumn,
    DashboardField,
)
from buffstack.tools.scaffold import EntityField, ScaffoldAction, ScaffoldExecutor
from buffstack.tools.validate import ValidateAction, ValidateExecutor


def scaffold(work: Path, **overrides) -> ScaffoldAction:
    defaults = dict(
        project_dir="app",
        name="Expense Tracker",
        entity_singular="expense",
        entity_plural="expenses",
        port=12099,
        fields=[
            EntityField(name="title", type="string", required=True),
            EntityField(name="amount", type="float", required=True),
        ],
    )
    defaults.update(overrides)
    return ScaffoldAction(**defaults)


def load_app(project: Path):
    """Import the generated app.py as a module for the Flask test client."""
    spec = importlib.util.spec_from_file_location(
        f"generated_{project.name}", project / "app.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def project(tmp_path: Path) -> Path:
    result = ScaffoldExecutor(str(tmp_path))(scaffold(tmp_path))
    assert not result.is_error, result.content
    return tmp_path / "app"


def test_scaffold_writes_the_contract_files(project: Path):
    for relative in [
        "app.py",
        "requirements.txt",
        "run.sh",
        "templates/dashboard.html",
        "static/dashboard.js",
        "static/dashboard.css",
        "tests/test_api.py",
        ".buffstack/manifest.json",
    ]:
        assert (project / relative).exists(), relative
    assert (project / "run.sh").stat().st_mode & 0o111


def test_scaffold_refuses_to_overwrite_without_force(project: Path, tmp_path: Path):
    result = ScaffoldExecutor(str(tmp_path))(scaffold(tmp_path))
    assert result.is_error
    assert "force" in result.content[0].text


def test_scaffold_force_overwrites(project: Path, tmp_path: Path):
    result = ScaffoldExecutor(str(tmp_path))(scaffold(tmp_path, force=True))
    assert not result.is_error


def test_generated_api_roundtrip(project: Path):
    module = load_app(project)
    application = module.create_app()
    application.config.update(TESTING=True)
    client = application.test_client()

    assert client.get("/health").get_json() == {"status": "ok"}

    created = client.post("/api/expenses", json={"title": "Coffee", "amount": 4.5})
    assert created.status_code == 201
    record = created.get_json()
    assert record["title"] == "Coffee"

    listed = client.get("/api/expenses").get_json()
    assert listed["count"] == 1
    assert listed["items"][0]["id"] == record["id"]

    deleted = client.delete(f"/api/expenses/{record['id']}")
    assert deleted.status_code == 200
    assert client.get("/api/expenses").get_json()["count"] == 0


def test_generated_dashboard_is_served(project: Path):
    module = load_app(project)
    client = module.create_app().test_client()
    response = client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "dashboard.js" in body
    assert "/api/expenses" in body or "dashboard.js" in body


def test_add_endpoint_inserts_a_working_route(project: Path):
    result = AddEndpointExecutor(str(project.parent))(
        AddEndpointAction(
            project_dir="app",
            path="/api/expenses/count",
            method="GET",
            summary="Number of records",
        )
    )
    assert not result.is_error, result.content

    module = load_app(project)
    client = module.create_app().test_client()
    client.post("/api/expenses", json={"title": "x", "amount": 1})
    assert client.get("/api/expenses/count").status_code == 200


def test_add_endpoint_keeps_app_parseable_with_custom_handler(project: Path):
    result = AddEndpointExecutor(str(project.parent))(
        AddEndpointAction(
            project_dir="app",
            path="/api/total",
            method="GET",
            handler="total = sum(r.get('amount', 0) for r in STORE.values())\n"
            'return jsonify({"total": total})',
        )
    )
    assert not result.is_error, result.content

    module = load_app(project)
    client = module.create_app().test_client()
    client.post("/api/expenses", json={"title": "a", "amount": 2})
    client.post("/api/expenses", json={"title": "b", "amount": 3})
    assert client.get("/api/total").get_json() == {"total": 5}


def test_add_endpoint_rejects_bad_input(project: Path):
    executor = AddEndpointExecutor(str(project.parent))

    bad_method = executor(
        AddEndpointAction(project_dir="app", path="/api/x", method="FETCH")
    )
    assert bad_method.is_error

    bad_path = executor(
        AddEndpointAction(project_dir="app", path="api/x", method="GET")
    )
    assert bad_path.is_error

    broken = executor(
        AddEndpointAction(
            project_dir="app",
            path="/api/broken",
            method="GET",
            handler="return jsonify({",
        )
    )
    assert broken.is_error
    assert "invalid Python" in broken.content[0].text


def test_add_endpoint_rejects_duplicate(project: Path):
    executor = AddEndpointExecutor(str(project.parent))
    first = executor(AddEndpointAction(project_dir="app", path="/api/dup", method="GET"))
    assert not first.is_error
    second = executor(AddEndpointAction(project_dir="app", path="/api/dup", method="GET"))
    assert second.is_error


def test_create_dashboard_uses_explicit_columns_and_fields(project: Path):
    result = CreateDashboardExecutor(str(project.parent))(
        CreateDashboardAction(
            project_dir="app",
            title="Spending",
            columns=[DashboardColumn(key="amount")],
            form_fields=[DashboardField(name="amount", type="float", required=True)],
            refresh_ms=5000,
        )
    )
    assert not result.is_error, result.content
    assert result.columns == ["amount"]
    assert result.api_endpoint == "/api/expenses"

    js = (project / "static" / "dashboard.js").read_text()
    assert "5000" in js
    assert '{"key": "amount", "label": "Amount"}' in js


def test_create_dashboard_can_replace_the_html(project: Path):
    custom = "<!DOCTYPE html><html><body><h1>Custom</h1></body></html>"
    result = CreateDashboardExecutor(str(project.parent))(
        CreateDashboardAction(project_dir="app", html=custom)
    )
    assert not result.is_error
    assert (project / "templates" / "dashboard.html").read_text() == custom


def test_validate_passes_static_checks(project: Path):
    result = ValidateExecutor(str(project.parent))(
        ValidateAction(project_dir="app", run_tests=False, probe_http=False)
    )
    assert result.passed, result.to_llm_content[0].text
    names = [c.name for c in result.checks]
    assert "required files" in names
    assert "dashboard is live" in names


def test_validate_flags_a_broken_dashboard(project: Path):
    (project / "static" / "dashboard.js").write_text("// no fetch here\n")
    result = ValidateExecutor(str(project.parent))(
        ValidateAction(project_dir="app", run_tests=False, probe_http=False)
    )
    assert not result.passed
    assert any("dashboard is live" in failure for failure in result.failures)


def test_resolve_port_prefers_explicit_then_manifest(project: Path, tmp_path: Path):
    """run_dev_server must not fall back to a shared default port.

    The scaffolded port is recorded in the manifest; using it is what keeps two
    generated apps from colliding on 12000.
    """
    from buffstack.tools import _common as common
    from buffstack.tools.server import RunServerAction

    assert common.read_manifest(project)["port"] == 12099
    assert common.resolve_port(project, None) == 12099
    assert common.resolve_port(project, 12345) == 12345

    # A project without a recorded port still gets a usable default.
    bare = tmp_path / "bare"
    bare.mkdir()
    assert common.resolve_port(bare, None) == common.DEFAULT_PORT

    # The action leaves the port unset so the manifest value wins.
    assert RunServerAction(project_dir="app").port is None


def test_run_server_uses_the_scaffolded_port_end_to_end(project: Path):
    """Start the generated app on the scaffolded port and confirm it serves."""
    from buffstack.tools import _common as common
    from buffstack.tools.server import RunServerAction, RunServerExecutor

    executor = RunServerExecutor(str(project.parent))
    started = executor(RunServerAction(project_dir="app", install=True))
    try:
        assert not started.is_error, started.content
        assert started.url == "http://127.0.0.1:12099"
        status, body = common.http_get("http://127.0.0.1:12099/health")
        assert status == 200, body
        assert body.strip() == '{"status":"ok"}'
    finally:
        executor(RunServerAction(project_dir="app", action="stop"))
