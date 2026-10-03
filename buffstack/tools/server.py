"""``run_dev_server`` — install dependencies and start the generated app."""

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

from buffstack.tools import _common as common
from buffstack.tools._common import BuffStackObservation


class RunServerAction(Action):
    project_dir: str = Field(description="Project directory, relative to the workspace.")
    port: int | None = Field(
        default=None,
        description=(
            "Port to bind. Defaults to the port recorded when the project was "
            "scaffolded."
        ),
    )
    action: str = Field(
        default="start",
        description="start, stop, restart, or status.",
    )
    install: bool = Field(
        default=True,
        description="Create the venv and install requirements.txt before starting.",
    )


class RunServerObservation(BuffStackObservation):
    status: str = Field(default="")
    url: str = Field(default="")
    pid: int | None = Field(default=None)
    log_tail: str = Field(default="")

    @property
    def to_llm_content(self) -> Sequence[TextContent]:
        lines = [f"Server {self.status}."]
        if self.url:
            lines.append(f"URL: {self.url}")
        if self.pid:
            lines.append(f"PID: {self.pid}")
        if self.log_tail:
            lines += ["", "Recent server log:", "```", self.log_tail, "```"]
        return [TextContent(text="\n".join(lines))]


RUN_SERVER_DESCRIPTION = """Start, stop, restart, or check the generated app's server.

The server runs detached, so it keeps serving between your steps. `start` creates
the project virtualenv, installs requirements.txt, launches app.py, and waits
until /health answers. If the server is already running it reports the current
state instead of starting a second copy.

`stop` terminates the recorded pid. `status` reports whether the process is alive
and whether /health responds. Always use this tool to manage the server rather
than backgrounding app.py in the terminal yourself."""


class RunServerTool(ToolDefinition[RunServerAction, RunServerObservation]):
    """Manage the generated app's development server."""

    name: ClassVar[str] = "run_dev_server"

    @classmethod
    def create(cls, conv_state, **params) -> Sequence[RunServerTool]:
        executor = RunServerExecutor(conv_state.workspace.working_dir)
        return [
            cls(
                description=RUN_SERVER_DESCRIPTION,
                action_type=RunServerAction,
                observation_type=RunServerObservation,
                annotations=ToolAnnotations(
                    title="run_dev_server",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=True,
                ),
                executor=executor,
            )
        ]


class RunServerExecutor(ToolExecutor[RunServerAction, RunServerObservation]):
    def __init__(self, working_dir: str) -> None:
        self.working_dir = working_dir

    def __call__(self, action: RunServerAction, conversation=None) -> RunServerObservation:  # noqa: ARG002
        project = common.resolve_project(self.working_dir, action.project_dir)
        if not (project / "app.py").exists():
            return RunServerObservation(
                message=f"No app.py in {project}. Scaffold the project first.",
                is_error=True,
            )

        operation = action.action.strip().lower()
        port = common.resolve_port(project, action.port)
        base_url = f"http://127.0.0.1:{port}"

        if operation == "status":
            return self._status(project, base_url)
        if operation == "stop":
            return self._stop(project)
        if operation == "restart":
            self._stop(project)
            return self._start(project, action, base_url, port)
        if operation != "start":
            return RunServerObservation(
                message=f"Unknown action '{action.action}'. Use start, stop, restart, or status.",
                is_error=True,
            )
        return self._start(project, action, base_url, port)

    def _start(
        self, project, action: RunServerAction, base_url: str, port: int
    ) -> RunServerObservation:
        running, detail = common.is_server_running(project)
        if running:
            healthy, _ = common.wait_for_health(base_url, attempts=1, delay=0)
            if healthy:
                return RunServerObservation(
                    message=f"Server already running ({detail}); /health responded on {base_url}.",
                    status="already running",
                    url=base_url,
                )
            self._stop(project)

        if action.install:
            ok, log = common.ensure_venv(project)
            if not ok:
                return RunServerObservation(
                    message=f"Dependency install failed.\n{log}",
                    is_error=True,
                    status="failed to install dependencies",
                )

        pid, log_path, _ = common.start_server(project, port=port)
        healthy, detail = common.wait_for_health(base_url, attempts=25, delay=1.0)

        if not healthy:
            return RunServerObservation(
                message=(
                    f"Server started (pid {pid}) but /health never answered: {detail}. "
                    "Read the log below and fix app.py."
                ),
                is_error=True,
                status="started but unhealthy",
                url=base_url,
                pid=pid,
                log_tail=common.tail(log_path, 60),
            )

        return RunServerObservation(
            message=f"Server healthy on {base_url}",
            status="running",
            url=base_url,
            pid=pid,
            log_tail=common.tail(log_path, 15),
        )

    def _stop(self, project) -> RunServerObservation:
        running, detail = common.is_server_running(project)
        if not running:
            return RunServerObservation(
                message=f"Nothing to stop: {detail}.",
                status="not running",
            )
        pid_file = project / common.MANIFEST_DIR / common.PID_FILE
        pid = int(pid_file.read_text().strip())
        try:
            import os
            import signal

            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        pid_file.unlink(missing_ok=True)
        return RunServerObservation(message=f"Stopped pid {pid}.", status="stopped")

    def _status(self, project, base_url: str) -> RunServerObservation:
        running, detail = common.is_server_running(project)
        healthy, body = common.wait_for_health(base_url, attempts=1, delay=0)
        return RunServerObservation(
            message=(
                f"Process: {'running' if running else 'not running'} ({detail}). "
                f"Health: {'ok' if healthy else 'no response'} ({body[:120]})."
            ),
            status="running" if running else "not running",
            url=base_url,
        )


register_tool(RunServerTool.name, RunServerTool)
