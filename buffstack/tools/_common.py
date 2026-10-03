"""Shared helpers for the BuffStack full-stack tools."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from openhands.sdk import Observation, TextContent

MANIFEST_DIR = ".buffstack"
MANIFEST_FILE = "manifest.json"
LOG_FILE = "server.log"
PID_FILE = "server.pid"

MAX_OUTPUT_CHARS = 4000


class BuffStackObservation(Observation):  # type: ignore[misc]
    """Base observation that takes a plain-text ``message``.

    ``Observation.content`` is a list of content blocks, which is awkward for
    tools whose result is one line of text. Subclasses build their own
    ``to_llm_content`` from the typed fields instead.
    """

    def __init__(self, message: str = "", **data: Any) -> None:
        # Models are frozen, so the content block must be passed through to the
        # validator rather than assigned afterwards.
        if message and "content" not in data:
            data["content"] = [TextContent(text=message)]
        super().__init__(**data)


def resolve_project(working_dir: str, project_dir: str) -> Path:
    """Resolve ``project_dir`` against the conversation workspace.

    Absolute paths are kept; relative paths are rooted at the workspace so a
    bare project name cannot escape the sandbox by accident.
    """
    candidate = Path(project_dir)
    if candidate.is_absolute():
        return candidate.resolve()
    return (Path(working_dir) / candidate).resolve()


def manifest_path(project: Path) -> Path:
    return project / MANIFEST_DIR / MANIFEST_FILE


def read_manifest(project: Path) -> dict[str, Any]:
    path = manifest_path(project)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def write_manifest(project: Path, updates: dict[str, Any]) -> dict[str, Any]:
    """Merge ``updates`` into the project manifest and return the result."""
    manifest = read_manifest(project)
    manifest.update(updates)
    path = manifest_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def write_file(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if executable:
        path.chmod(0o755)


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [{len(text) - limit} more characters]"


def run(
    command: str,
    cwd: Path,
    *,
    timeout: int = 120,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run a shell command and return (exit_code, stdout, stderr)."""
    merged_env = {**os.environ, **(env or {})}
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=merged_env,
        )
        return completed.returncode, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return 124, stdout, (stderr + f"\n[timed out after {timeout}s]").strip()


def venv_python(project: Path) -> Path:
    return project / ".venv" / "bin" / "python"


def ensure_venv(project: Path, *, timeout: int = 300) -> tuple[bool, str]:
    """Create the project venv and install requirements. Returns (ok, log)."""
    python = venv_python(project)
    log: list[str] = []

    if not python.exists():
        code, out, err = run("python3 -m venv .venv", project, timeout=timeout)
        log.append(f"$ python3 -m venv .venv\n{truncate(out + err, 1000)}")
        if code != 0:
            return False, "\n".join(log)

    code, out, err = run(
        f"{shlex.quote(str(python))} -m pip install --quiet --upgrade pip",
        project,
        timeout=timeout,
    )
    log.append(f"$ pip install --upgrade pip -> exit {code}")

    requirements = project / "requirements.txt"
    if requirements.exists():
        code, out, err = run(
            f"{shlex.quote(str(python))} -m pip install --quiet -r requirements.txt",
            project,
            timeout=timeout,
        )
        log.append(f"$ pip install -r requirements.txt -> exit {code}\n{truncate(out + err, 1500)}")
        if code != 0:
            return False, "\n".join(log)

    return True, "\n".join(log)


def http_get(url: str, *, timeout: float = 5.0) -> tuple[int, str]:
    """GET a URL and return (status_code, body). Status 0 means unreachable."""
    request = urllib.request.Request(url, headers={"Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - any network failure means unreachable
        return 0, f"{type(exc).__name__}: {exc}"


def wait_for_health(base_url: str, *, attempts: int = 30, delay: float = 1.0) -> tuple[bool, str]:
    """Poll ``/health`` until it answers or the attempts run out."""
    last = "no response"
    for _ in range(attempts):
        status, body = http_get(f"{base_url.rstrip('/')}/health", timeout=3.0)
        if status == 200:
            return True, body.strip()
        last = f"status={status} body={body.strip()[:200]}"
        time.sleep(delay)
    return False, last


def is_server_running(project: Path) -> tuple[bool, str]:
    """Check the recorded server pid and whether it is alive."""
    pid_file = project / MANIFEST_DIR / PID_FILE
    if not pid_file.exists():
        return False, "no pid file"
    pid_text = pid_file.read_text().strip()
    if not pid_text.isdigit():
        return False, "invalid pid file"
    pid = int(pid_text)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False, f"pid {pid} is not running"
    except PermissionError:
        return True, f"pid {pid} is running (owned by another user)"
    return True, f"pid {pid} is running"


def start_server(project: Path, *, port: int, host: str = "0.0.0.0") -> tuple[int, Path, Path]:
    """Start ``app.py`` detached and return (pid, log_path, pid_path).

    The process is started in its own session so it survives the terminal tool's
    cleanup between agent steps.
    """
    python = venv_python(project)
    interpreter = str(python) if python.exists() else "python3"
    runtime_dir = project / MANIFEST_DIR
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_path = runtime_dir / LOG_FILE
    pid_path = runtime_dir / PID_FILE

    log_handle = open(log_path, "ab")
    process = subprocess.Popen(
        [interpreter, "app.py"],
        cwd=str(project),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env={**os.environ, "PORT": str(port), "FLASK_RUN_HOST": host},
    )
    pid_path.write_text(str(process.pid))
    return process.pid, log_path, pid_path


def tail(path: Path, lines: int = 40) -> str:
    if not path.exists():
        return ""
    content = path.read_text(errors="replace").splitlines()
    return "\n".join(content[-lines:])
