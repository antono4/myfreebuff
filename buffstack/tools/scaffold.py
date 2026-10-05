"""``scaffold_fullstack_app`` — create a runnable full-stack project skeleton."""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar
from pathlib import Path

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


class EntityField(Action):
    """One field on the scaffolded entity."""

    name: str = Field(description="Field name, snake_case (e.g. 'amount').")
    type: str = Field(
        default="string",
        description="One of: string, integer, float, boolean, datetime.",
    )
    required: bool = Field(default=False, description="Whether the field is required.")


class ScaffoldAction(Action):
    project_dir: str = Field(description="Project directory, relative to the workspace.")
    name: str = Field(description="Human-readable project name, e.g. 'Expense Tracker'.")
    entity_singular: str = Field(description="Entity singular, snake_case, e.g. 'expense'.")
    entity_plural: str = Field(description="Entity plural, snake_case, e.g. 'expenses'.")
    fields: list[EntityField] = Field(
        default_factory=list,
        description="Fields on the entity. 'id' is added automatically.",
    )
    port: int = Field(default=12000, description="Default port written into run.sh.")
    subtitle: str = Field(
        default="",
        description="One-line subtitle shown under the dashboard title.",
    )
    force: bool = Field(
        default=False,
        description="Overwrite an existing project in project_dir.",
    )


class ScaffoldObservation(BuffStackObservation):
    project_dir: str = Field(default="")
    files: list[str] = Field(default_factory=list)
    endpoints: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)

    @property
    def to_llm_content(self) -> Sequence[TextContent]:
        if not self.project_dir:
            return [TextContent(text=self.content[0].text if self.content else "Scaffold failed.")]
        lines = [
            f"Scaffolded project at {self.project_dir}",
            "",
            "Files:",
            *[f"- {f}" for f in self.files],
            "",
            "Endpoints:",
            *[f"- {e}" for e in self.endpoints],
        ]
        if self.next_steps:
            lines += ["", "Next steps:", *[f"- {s}" for s in self.next_steps]]
        return [TextContent(text="\n".join(lines))]


SCAFFOLD_DESCRIPTION = """Create a runnable full-stack project skeleton.

Writes a Flask app with a JSON API and an HTML dashboard that fetches from it,
plus requirements.txt, tests, and a run.sh. The skeleton runs as-is for the
entity you describe, so you can start the server before customizing it.

The dashboard is generated from `fields`: each field becomes a table column and
a create-form input. `id` is always present and does not need to be listed.

Call this once per project. Use the other tools to change the generated code
afterwards."""


class ScaffoldTool(ToolDefinition[ScaffoldAction, ScaffoldObservation]):
    """Create the full-stack project skeleton."""

    name: ClassVar[str] = "scaffold_fullstack_app"

    @classmethod
    def create(cls, conv_state, **params) -> Sequence[ScaffoldTool]:
        working_dir = conv_state.workspace.working_dir
        executor = ScaffoldExecutor(working_dir)
        return [
            cls(
                description=SCAFFOLD_DESCRIPTION,
                action_type=ScaffoldAction,
                observation_type=ScaffoldObservation,
                annotations=ToolAnnotations(
                    title="scaffold_fullstack_app",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
                executor=executor,
            )
        ]


class ScaffoldExecutor(ToolExecutor[ScaffoldAction, ScaffoldObservation]):
    def __init__(self, working_dir: str) -> None:
        self.working_dir = working_dir

    def __call__(self, action: ScaffoldAction, conversation=None) -> ScaffoldObservation:  # noqa: ARG002
        project = common.resolve_project(self.working_dir, action.project_dir)
        app_file = project / "app.py"

        if app_file.exists() and not action.force:
            return ScaffoldObservation(
                message=(
                    f"{project} already contains an app.py. Pass force=true to "
                    "overwrite, or edit the existing project with the file editor."
                ),
                is_error=True,
            )

        fields = [f.model_dump() for f in action.fields]
        values = {
            "PROJECT_NAME": action.name,
            "TITLE": action.name,
            "SUBTITLE": action.subtitle or f"Dashboard for {action.name}",
            "ENTITY_SINGULAR": action.entity_singular,
            "ENTITY_PLURAL": action.entity_plural,
            "ENTITY_PLURAL_TITLE": action.entity_plural.replace("_", " ").title(),
            "PORT": action.port,
            "STATIC_PREFIX": "",
            "API_ENDPOINT": f"/api/{action.entity_plural}",
            "REFRESH_MS": 0,
            "COLUMNS_JSON": templates.json_literal(templates.dashboard_columns(fields)),
            "FIELDS_JSON": templates.json_literal(templates.dashboard_fields(fields)),
            "REQUIRED_FIELDS_JSON": templates.json_literal(templates.required_fields(fields)),
            "SAMPLE_PAYLOAD_JSON": templates.json_literal(templates.sample_payload(fields)),
        }

        written: list[str] = []
        targets = {
            "app.py": templates.render(templates.APP_PY, **values),
            "requirements.txt": templates.REQUIREMENTS_TXT,
            "run.sh": templates.render(templates.RUN_SH, **values),
            "templates/dashboard.html": templates.render(templates.DASHBOARD_HTML, **values),
            "static/dashboard.js": templates.render(templates.DASHBOARD_JS, **values),
            "static/dashboard.css": templates.render(templates.DASHBOARD_CSS, **values),
            "tests/test_api.py": templates.render(templates.TEST_API_PY, **values),
        }
        for relative, content in targets.items():
            common.write_file(project / relative, content, executable=relative == "run.sh")
            written.append(relative)

        common.write_manifest(
            project,
            {
                "name": action.name,
                "project_dir": str(project),
                "entity_singular": action.entity_singular,
                "entity_plural": action.entity_plural,
                "fields": fields,
                "port": action.port,
                "endpoints": [
                    "GET /health",
                    "GET /",
                    f"GET /api/{action.entity_plural}",
                    f"POST /api/{action.entity_plural}",
                    f"DELETE /api/{action.entity_plural}/<id>",
                ],
            },
        )
        written.append(f"{common.MANIFEST_DIR}/{common.MANIFEST_FILE}")

        return ScaffoldObservation(
            message=f"Scaffolded {action.name} at {project}",
            project_dir=str(project),
            files=sorted(written),
            endpoints=[
                "GET /health",
                "GET / (dashboard)",
                f"GET /api/{action.entity_plural}",
                f"POST /api/{action.entity_plural}",
                f"DELETE /api/{action.entity_plural}/<id>",
            ],
            next_steps=[
                f"Add or refine endpoints with add_api_endpoint in {project}.",
                "Customize templates/dashboard.html and static/dashboard.js for the real views.",
                f"Start it with run_dev_server(project_dir='{action.project_dir}', port={action.port}).",
                "Verify with validate_fullstack_app, then curl the API and fetch /.",
            ],
        )


register_tool(ScaffoldTool.name, ScaffoldTool)
