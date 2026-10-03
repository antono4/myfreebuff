"""Command-line entry point for the BuffStack agent."""

from __future__ import annotations

import argparse
import os
import sys
import urllib.request
from pathlib import Path

from openhands.sdk import Conversation

from buffstack.agent import build_agent
from buffstack.config import AgentConfig, default_config


def fetch_managed_key() -> str | None:
    """Fetch the runtime's managed LLM key when running inside OpenHands.

    Returns None when the refresh endpoint is not configured or does not answer,
    so an explicitly supplied key always wins.
    """
    url = os.getenv("OH_LLM_API_KEY_REFRESH_URL")
    session_key = os.getenv("SESSION_API_KEY")
    if not url or not session_key:
        return None
    request = urllib.request.Request(
        url, headers={"X-Session-API-Key": session_key, "Accept": "text/plain"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            key = response.read().decode().strip()
        return key or None
    except Exception:  # noqa: BLE001 - a missing managed key is not fatal here
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="buffstack",
        description=(
            "Build a full-stack app with an HTML dashboard from a short description."
        ),
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="What to build. Omit to start an interactive session.",
    )
    parser.add_argument(
        "--workspace",
        default=".",
        help="Directory the agent works in (default: current directory).",
    )
    parser.add_argument("--port", type=int, default=None, help="Port for the app.")
    parser.add_argument("--model", default=None, help="LLM model id.")
    parser.add_argument("--base-url", default=None, help="LLM API base URL.")
    parser.add_argument("--api-key", default=None, help="LLM API key.")
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Maximum agent steps for one request.",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Do not stream agent events to stdout."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    api_key = args.api_key or os.getenv("LLM_API_KEY")
    if not api_key:
        api_key = fetch_managed_key()

    config = default_config(
        model=args.model,
        base_url=args.base_url,
        port=args.port,
        max_iterations=args.max_iterations,
    )
    if api_key:
        config.api_key = api_key

    try:
        config.resolved_api_key()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    workspace = str(Path(args.workspace).expanduser().resolve())
    Path(workspace).mkdir(parents=True, exist_ok=True)

    agent = build_agent(config)
    conversation = Conversation(agent=agent, workspace=workspace)

    print(f"BuffStack • model={config.model} • workspace={workspace}")
    print(f"Tools: {', '.join(t.name for t in agent.tools)}\n")

    prompts_to_send = [" ".join(args.prompt)] if args.prompt else []
    if not prompts_to_send:
        try:
            while True:
                text = input("you › ").strip()
                if not text:
                    continue
                if text in {"exit", "quit", ":q"}:
                    break
                prompts_to_send.append(text)
        except (EOFError, KeyboardInterrupt):
            print()

    for prompt in prompts_to_send:
        print(f"\n--- {prompt} ---")
        conversation.send_message(prompt)
        conversation.run()
        print("\nDone.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
