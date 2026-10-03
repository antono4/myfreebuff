"""``validate_fullstack_app`` — prove the generated app actually works."""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Sequence
from typing import ClassVar

from pydantic import Field

from openhands.sdk import Action, TextContent
from openhands.sdk.tool import (
    ToolAnnotations,
    ToolDefinition,
    ToolExecutor,
    register_tool,
)

from buffstack.tools import _common as common
from buffstack.tools._common import BuffStackObservation

REQUIRED_FILES = [
    "app.py",
    "requirements.txt",
    "templates/dashboard.html",
    "static/dashboard.js",
    "static/dashboard.css",
    "tests/test_api.py",
]

# Element ids the generated dashboard.js binds to.
REQUIRED_ELEMENT_IDS = [
    "status-pill",
    "refresh",
    "error",
    "kpi-count",
    "create-form",
    "table-head",
    "table-body",
    "search",
]

_ROUTE = re.compile(r'@app\.(?:route|get|post|put|patch|delete)\(\s*"([^"]+)"')


class ValidateAction(Action):
    project_dir: str = Field(description="Project directory, relative to the workspace.")
    port: int = Field(default=12000, description="Port the running server uses.")
    run_tests: bool = Field(default=True, description="Run pytest in the project venv.")
    probe_http: bool = Field(
        default=True,
        description="Probe the running server's /health, /, and collection endpoint.",
    )


class Check(Action):
    name: str = Field(description="Check name.")
    passed: bool = Field(description="Whether the check passed.")
    detail: str = Field(default="", description="Evidence or failure reason.")


class ValidateObservation(BuffStackObservation):
    passed: bool = Field(default=False)
    checks: list[Check] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)

    @property
    def to_llm_content(self) -> Sequence[TextContent]:
        if not self.checks:
            return [TextContent(text=self.content[0].text if self.content else "Validation failed to run.")]
        lines = ["Validation " + ("PASSED" if self.passed else "FAILED")]
        for check in self.checks:
            mark = "PASS" if check.passed else "FAIL"
            lines.append(f"[{mark}] {check.name}: {check.detail}")
        if self.failures:
            lines += ["", "Fix these before reporting the app as working:"]
            lines += [f"- {f}" for f in self.failures]
        return [TextContent(text="\n".join(lines))]


VALIDATE_DESCRIPTION = """Verify the generated full-stack app against its contract.

Checks, in order:

1. Every required file exists.
2. app.py parses as Python and exposes create_app and a module-level app.
3. The routes registered in app.py include /health, /, and the collection
   endpoint recorded in the manifest.
4. The dashboard HTML references dashboard.js and contains the element ids the
   script binds to.
5. dashboard.js calls fetch() against the API endpoint, so the dashboard is a
   live interface rather than a static mock-up.
6. pytest passes in the project venv (unless run_tests is false).
7. If a server is running, /health returns {"status": "ok"}, / returns HTML, and
   the collection endpoint returns a JSON object.

Run this after starting the server, and rerun it after every fix. A build that
merely imports is not evidence that the requested behavior works."""


class ValidateTool(ToolDefinition[ValidateAction, ValidateObservation]):
    """Validate the generated app end to end."""

    name: ClassVar[str] = "validate_fullstack_app"

    @classmethod
    def create(cls, conv_state, **params) -> Sequence[ValidateTool]:
        executor = ValidateExecutor(conv_state.workspace.working_dir)
        return [
            cls(
                description=VALIDATE_DESCRIPTION,
                action_type=ValidateAction,
                observation_type=ValidateObservation,
                annotations=ToolAnnotations(
                    title="validate_fullstack_app",
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=True,
                ),
                executor=executor,
            )
        ]


class ValidateExecutor(ToolExecutor[ValidateAction, ValidateObservation]):
    def __init__(self, working_dir: str) -> None:
        self.working_dir = working_dir

    def __call__(self, action: ValidateAction, conversation=None) -> ValidateObservation:  # noqa: ARG002
        project = common.resolve_project(self.working_dir, action.project_dir)
        manifest = common.read_manifest(project)
        entity_plural = manifest.get("entity_plural", "items")
        collection = f"/api/{entity_plural}"

        checks: list[Check] = []
        failures: list[str] = []

        def record(name: str, passed: bool, detail: str) -> None:
            checks.append(Check(name=name, passed=passed, detail=detail))
            if not passed:
                failures.append(f"{name}: {detail}")

        missing = [f for f in REQUIRED_FILES if not (project / f).exists()]
        record(
            "required files",
            not missing,
            "all present" if not missing else f"missing {', '.join(missing)}",
        )

        app_file = project / "app.py"
        source = app_file.read_text() if app_file.exists() else ""
        syntax_ok = False
        if source:
            try:
                ast.parse(source)
                syntax_ok = True
            except SyntaxError as exc:
                record("app.py syntax", False, f"{exc.msg} at line {exc.lineno}")
        if source and syntax_ok:
            has_factory = "def create_app(" in source
            has_module_app = re.search(r"^app\s*=\s*create_app\(\)", source, re.M) is not None
            record(
                "app.py structure",
                has_factory and has_module_app,
                f"create_app={'yes' if has_factory else 'no'}, "
                f"module-level app={'yes' if has_module_app else 'no'}",
            )

            routes = _ROUTE.findall(source)
            needed = ["/health", "/", collection]
            absent = [r for r in needed if r not in routes]
            record(
                "routes",
                not absent,
                f"{len(routes)} routes: {', '.join(sorted(set(routes)))}"
                + (f" | missing {', '.join(absent)}" if absent else ""),
            )

        html_file = project / "templates" / "dashboard.html"
        html = html_file.read_text() if html_file.exists() else ""
        if html:
            refs_js = "dashboard.js" in html
            absent_ids = [i for i in REQUIRED_ELEMENT_IDS if f'id="{i}"' not in html]
            record(
                "dashboard html",
                refs_js and not absent_ids,
                f"references dashboard.js={'yes' if refs_js else 'no'}"
                + (f", missing ids {', '.join(absent_ids)}" if absent_ids else ""),
            )

        js_file = project / "static" / "dashboard.js"
        js = js_file.read_text() if js_file.exists() else ""
        if js:
            uses_fetch = "fetch(" in js
            hits_api = collection in js
            record(
                "dashboard is live",
                uses_fetch and hits_api,
                f"fetch()={'yes' if uses_fetch else 'no'}, calls {collection}="
                f"{'yes' if hits_api else 'no'}",
            )

        if action.run_tests:
            python = common.venv_python(project)
            if not python.exists():
                ok, log = common.ensure_venv(project)
                if not ok:
                    record("pytest", False, f"could not prepare venv: {log[-300:]}")
                else:
                    self._run_pytest(project, record)
            else:
                self._run_pytest(project, record)

        if action.probe_http:
            base_url = f"http://127.0.0.1:{action.port}"
            healthy, body = common.wait_for_health(base_url, attempts=3, delay=1.0)
            record("GET /health", healthy, body[:160] or "no response")

            status, page = common.http_get(f"{base_url}/")
            is_html = status == 200 and "<html" in page.lower()
            record(
                "GET /",
                is_html,
                f"status={status}, html={'yes' if is_html else 'no'}"
                + ("" if is_html else " (start the server with run_dev_server)"),
            )

            status, payload = common.http_get(f"{base_url}{collection}")
            object_ok = False
            detail = f"status={status}"
            if status == 200:
                try:
                    parsed = json.loads(payload)
                    object_ok = isinstance(parsed, dict)
                    detail += f", body={json.dumps(parsed)[:160]}"
                except json.JSONDecodeError:
                    detail += f", invalid JSON: {payload[:120]}"
            record(f"GET {collection}", object_ok, detail)

        passed = all(c.passed for c in checks)
        return ValidateObservation(
            message="Validation " + ("passed" if passed else "failed"),
            passed=passed,
            checks=checks,
            failures=failures,
        )

    def _run_pytest(self, project, record) -> None:
        python = common.venv_python(project)
        code, out, err = common.run(
            f"{python} -m pytest -q", project, timeout=180
        )
        record(
            "pytest",
            code == 0,
            common.truncate((out + err).strip(), 800) or f"exit {code}",
        )


register_tool(ValidateTool.name, ValidateTool)
