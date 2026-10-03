"""``add_api_endpoint`` — add a JSON API route to the generated Flask app."""

from __future__ import annotations

import ast
import re
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

from buffstack.tools import _common as common
from buffstack.tools._common import BuffStackObservation

ROUTE_MARKER = "# BUFFSTACK:ROUTES"
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_SAFE_NAME = re.compile(r"[^0-9a-zA-Z_]")


class EndpointParam(Action):
    name: str = Field(description="Parameter name, snake_case.")
    type: str = Field(default="string", description="string, integer, float, or boolean.")


class AddEndpointAction(Action):
    project_dir: str = Field(description="Project directory, relative to the workspace.")
    path: str = Field(description="Route path, e.g. '/api/expenses/<int:record_id>'.")
    method: str = Field(default="GET", description="GET, POST, PUT, PATCH, or DELETE.")
    summary: str = Field(default="", description="One-line description of the route.")
    handler: str = Field(
        default="",
        description=(
            "Python statements for the route body. Leave empty to generate a "
            "handler that reads and writes the in-memory STORE."
        ),
    )
    params: list[EndpointParam] = Field(
        default_factory=list,
        description="Path or query parameters, for documentation and validation.",
    )


class AddEndpointObservation(BuffStackObservation):
    file: str = Field(default="")
    inserted_code: str = Field(default="")
    endpoint: str = Field(default="")

    @property
    def to_llm_content(self) -> Sequence[TextContent]:
        if self.is_error:
            return [TextContent(text=self.content[0].text if self.content else "Failed to add endpoint.")]
        return [
            TextContent(
                text=(
                    f"Added {self.endpoint} to {self.file}\n\n"
                    f"```python\n{self.inserted_code}\n```"
                )
            )
        ]


ADD_ENDPOINT_DESCRIPTION = """Add a JSON API route to the generated Flask app.

Inserts a route handler into app.py at the route marker, keeping the file valid
Python. Use it for every endpoint you add instead of editing app.py by hand, so
routes stay in one place and the file keeps its structure.

Pass `handler` as Python statements (already unindented) for custom logic. Leave
it empty to get a working handler over the in-memory STORE for the common cases:
listing, fetching one record by <int:record_id>, creating from a JSON body, or
deleting.

Route paths are absolute and start with '/'. Path converters use Flask syntax,
for example '/api/expenses/<int:record_id>'. Order matters: declare literal
routes such as '/api/summary' before '/api/<int:record_id>'."""


class AddEndpointTool(ToolDefinition[AddEndpointAction, AddEndpointObservation]):
    """Add a JSON API route to app.py."""

    name: ClassVar[str] = "add_api_endpoint"

    @classmethod
    def create(cls, conv_state, **params) -> Sequence[AddEndpointTool]:
        executor = AddEndpointExecutor(conv_state.workspace.working_dir)
        return [
            cls(
                description=ADD_ENDPOINT_DESCRIPTION,
                action_type=AddEndpointAction,
                observation_type=AddEndpointObservation,
                annotations=ToolAnnotations(
                    title="add_api_endpoint",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
                executor=executor,
            )
        ]


class AddEndpointExecutor(ToolExecutor[AddEndpointAction, AddEndpointObservation]):
    def __init__(self, working_dir: str) -> None:
        self.working_dir = working_dir

    def __call__(self, action: AddEndpointAction, conversation=None) -> AddEndpointObservation:  # noqa: ARG002
        project = common.resolve_project(self.working_dir, action.project_dir)
        app_file = project / "app.py"

        if not app_file.exists():
            return AddEndpointObservation(
                message=f"No app.py in {project}. Scaffold the project first.",
                is_error=True,
            )

        method = action.method.strip().upper()
        if method not in METHODS:
            return AddEndpointObservation(
                message=f"Unsupported method '{action.method}'. Use one of {sorted(METHODS)}.",
                is_error=True,
            )
        if not action.path.startswith("/"):
            return AddEndpointObservation(
                message=f"Route path must start with '/', got '{action.path}'.",
                is_error=True,
            )

        source = app_file.read_text()
        lines = source.splitlines(keepends=True)
        marker_index = next((i for i, line in enumerate(lines) if ROUTE_MARKER in line), None)
        if marker_index is None:
            return AddEndpointObservation(
                message=(
                    f"Route marker '{ROUTE_MARKER}' is missing from {app_file}. "
                    "Restore it, or add the route with the file editor."
                ),
                is_error=True,
            )

        function_name = self._function_name(method, action.path)
        if f"def {function_name}(" in source:
            return AddEndpointObservation(
                message=(
                    f"A route named {function_name} already exists in app.py. "
                    "Change the path, or edit the existing handler."
                ),
                is_error=True,
            )

        block = self._build_block(action, method, function_name)
        # Insert the whole block as its own line, keeping the marker line intact.
        updated = "".join(lines[:marker_index] + [block] + lines[marker_index:])

        try:
            ast.parse(updated)
        except SyntaxError as exc:
            return AddEndpointObservation(
                message=(
                    f"The handler would make app.py invalid Python: {exc.msg} "
                    f"(line {exc.lineno}). Check the indentation and syntax of `handler`."
                ),
                is_error=True,
            )

        common.write_file(app_file, updated)

        manifest = common.read_manifest(project)
        endpoints = manifest.get("endpoints", [])
        endpoints.append(f"{method} {action.path}")
        common.write_manifest(project, {"endpoints": sorted(set(endpoints))})

        return AddEndpointObservation(
            message=f"Added {method} {action.path}",
            file=str(app_file),
            inserted_code=block,
            endpoint=f"{method} {action.path}",
        )

    @staticmethod
    def _function_name(method: str, path: str) -> str:
        cleaned = _SAFE_NAME.sub("_", path.strip("/")).strip("_")
        cleaned = re.sub(r"_+", "_", cleaned) or "root"
        return f"{method.lower()}_{cleaned}"

    @staticmethod
    def _build_block(action: AddEndpointAction, method: str, function_name: str) -> str:
        body = action.handler.strip("\n") if action.handler.strip() else _default_handler(action, method)
        body = "\n".join(
            ("        " + line) if line.strip() else "" for line in body.splitlines()
        )
        docstring = f'        """{action.summary}"""\n' if action.summary else ""
        return (
            f'    @app.route("{action.path}", methods=["{method}"])\n'
            f"    def {function_name}():\n"
            f"{docstring}"
            f"{body}\n"
        )


def _default_handler(action: AddEndpointAction, method: str) -> str:
    path = action.path
    has_id = "<int:" in path
    has_float = "<float:" in path
    param_name = ""
    if has_id or has_float:
        param_name = path.split("<", 1)[1].split(">", 1)[0].split(":", 1)[1]

    if method == "GET" and not param_name:
        return 'return jsonify({"items": list(STORE.values()), "count": len(STORE)})'
    if method == "GET" and param_name:
        return (
            f"record = STORE.get({param_name})\n"
            'if record is None:\n'
            f'    return jsonify({{"error": "not found", "id": {param_name}}}), 404\n'
            "return jsonify(record)"
        )
    if method == "POST":
        return (
            'payload = request.get_json(silent=True) or {}\n'
            'record = {"id": _next_id(), **payload}\n'
            "STORE[record[\"id\"]] = record\n"
            "return jsonify(record), 201"
        )
    if method in {"PUT", "PATCH"} and param_name:
        return (
            f"record = STORE.get({param_name})\n"
            "if record is None:\n"
            f'    return jsonify({{"error": "not found", "id": {param_name}}}), 404\n'
            "payload = request.get_json(silent=True) or {}\n"
            "record.update(payload)\n"
            "return jsonify(record)"
        )
    if method == "DELETE" and param_name:
        return (
            f"removed = STORE.pop({param_name}, None)\n"
            "if removed is None:\n"
            f'    return jsonify({{"error": "not found", "id": {param_name}}}), 404\n'
            f'return jsonify({{"deleted": {param_name}}})'
        )
    return 'return jsonify({"message": "ok"})'


register_tool(AddEndpointTool.name, AddEndpointTool)
