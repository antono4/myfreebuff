"""``create_dashboard`` — generate the HTML dashboard and its data bindings."""

from __future__ import annotations

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

from buffstack import templates
from buffstack.tools import _common as common
from buffstack.tools._common import BuffStackObservation


class DashboardColumn(Action):
    key: str = Field(description="JSON field to show, e.g. 'amount'.")
    label: str = Field(default="", description="Column header. Defaults to the key.")


class DashboardField(Action):
    name: str = Field(description="JSON field to collect, e.g. 'amount'.")
    label: str = Field(default="", description="Input label. Defaults to the name.")
    type: str = Field(default="string", description="string, integer, float, or boolean.")
    required: bool = Field(default=False, description="Whether the input is required.")


class CreateDashboardAction(Action):
    project_dir: str = Field(description="Project directory, relative to the workspace.")
    title: str | None = Field(default=None, description="Dashboard title.")
    subtitle: str | None = Field(default=None, description="One-line subtitle.")
    api_endpoint: str | None = Field(
        default=None,
        description="Collection endpoint the dashboard reads, e.g. '/api/expenses'.",
    )
    columns: list[DashboardColumn] = Field(
        default_factory=list,
        description="Table columns. Defaults to the manifest fields plus 'id'.",
    )
    form_fields: list[DashboardField] = Field(
        default_factory=list,
        description="Create-form inputs. Defaults to the manifest fields.",
    )
    refresh_ms: int = Field(
        default=0,
        description="Auto-refresh interval in milliseconds. 0 disables it.",
    )
    html: str = Field(
        default="",
        description=(
            "Full replacement for templates/dashboard.html. Leave empty to "
            "regenerate the standard dashboard from the columns and fields."
        ),
    )


class CreateDashboardObservation(BuffStackObservation):
    files: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    api_endpoint: str = Field(default="")

    @property
    def to_llm_content(self) -> Sequence[TextContent]:
        if self.is_error:
            return [TextContent(text=self.content[0].text if self.content else "Failed to create the dashboard.")]
        return [
            TextContent(
                text=(
                    "Dashboard written.\n"
                    f"- Files: {', '.join(self.files)}\n"
                    f"- Endpoint: {self.api_endpoint}\n"
                    f"- Columns: {', '.join(self.columns)}\n"
                    "\nServe it, then fetch / and confirm the HTML references "
                    "dashboard.js and the API endpoint."
                )
            )
        ]


CREATE_DASHBOARD_DESCRIPTION = """Write the HTML dashboard and its data bindings.

Regenerates templates/dashboard.html and static/dashboard.js from the columns
and form fields you pass, so the table and the create form always match the API
payload. The generated JavaScript fetches the collection endpoint on load and
renders it into the DOM, and shows a connection status and error banner.

Pass `html` only when you need markup the standard dashboard cannot express; it
replaces templates/dashboard.html verbatim. The JavaScript is still regenerated,
so keep the element ids it expects (`status-pill`, `refresh`, `error`,
`kpi-count`, `kpi-updated`, `create-form`, `table-head`, `table-body`, `search`,
`empty`) or provide your own script."""


class CreateDashboardTool(ToolDefinition[CreateDashboardAction, CreateDashboardObservation]):
    """Write the dashboard HTML and bindings."""

    name: ClassVar[str] = "create_dashboard"

    @classmethod
    def create(cls, conv_state, **params) -> Sequence[CreateDashboardTool]:
        executor = CreateDashboardExecutor(conv_state.workspace.working_dir)
        return [
            cls(
                description=CREATE_DASHBOARD_DESCRIPTION,
                action_type=CreateDashboardAction,
                observation_type=CreateDashboardObservation,
                annotations=ToolAnnotations(
                    title="create_dashboard",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
                executor=executor,
            )
        ]


class CreateDashboardExecutor(ToolExecutor[CreateDashboardAction, CreateDashboardObservation]):
    def __init__(self, working_dir: str) -> None:
        self.working_dir = working_dir

    def __call__(self, action: CreateDashboardAction, conversation=None) -> CreateDashboardObservation:  # noqa: ARG002
        project = common.resolve_project(self.working_dir, action.project_dir)
        if not (project / "app.py").exists():
            return CreateDashboardObservation(
                message=f"No app.py in {project}. Scaffold the project first.",
                is_error=True,
            )

        manifest = common.read_manifest(project)
        entity_plural = manifest.get("entity_plural", "items")
        title = action.title or manifest.get("name") or project.name
        subtitle = action.subtitle or f"Dashboard for {title}"
        api_endpoint = action.api_endpoint or f"/api/{entity_plural}"

        columns = (
            [{"key": c.key, "label": c.label or c.key.replace("_", " ").title()} for c in action.columns]
            if action.columns
            else templates.dashboard_columns(manifest.get("fields", []))
        )
        form_fields = (
            [
                {
                    "name": f.name,
                    "label": f.label or f.name.replace("_", " ").title(),
                    "type": f.type,
                    "required": f.required,
                }
                for f in action.form_fields
            ]
            if action.form_fields
            else templates.dashboard_fields(manifest.get("fields", []))
        )

        values = {
            "TITLE": title,
            "SUBTITLE": subtitle,
            "API_ENDPOINT": api_endpoint,
            "STATIC_PREFIX": "",
            "REFRESH_MS": max(0, action.refresh_ms),
            "COLUMNS_JSON": templates.json_literal(columns),
            "FIELDS_JSON": templates.json_literal(form_fields),
        }

        html = action.html or templates.render(templates.DASHBOARD_HTML, **values)
        written = []
        common.write_file(project / "templates" / "dashboard.html", html)
        written.append("templates/dashboard.html")

        common.write_file(
            project / "static" / "dashboard.js",
            templates.render(templates.DASHBOARD_JS, **values),
        )
        written.append("static/dashboard.js")

        if not (project / "static" / "dashboard.css").exists():
            common.write_file(
                project / "static" / "dashboard.css",
                templates.render(templates.DASHBOARD_CSS, **values),
            )
            written.append("static/dashboard.css")

        common.write_manifest(
            project,
            {
                "dashboard": {
                    "title": title,
                    "subtitle": subtitle,
                    "api_endpoint": api_endpoint,
                    "columns": columns,
                    "form_fields": form_fields,
                    "refresh_ms": max(0, action.refresh_ms),
                }
            },
        )

        return CreateDashboardObservation(
            message=f"Dashboard written to {project}",
            files=written,
            columns=[c["key"] for c in columns],
            api_endpoint=api_endpoint,
        )


register_tool(CreateDashboardTool.name, CreateDashboardTool)
