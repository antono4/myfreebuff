"""Assemble the BuffStack agent from the SDK primitives."""

from __future__ import annotations

from datetime import date

from pydantic import SecretStr

from openhands.sdk import LLM, Agent, Tool
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.task_tracker import TaskTrackerTool
from openhands.tools.terminal import TerminalTool

from buffstack import prompts
from buffstack.config import AgentConfig, default_config
from buffstack.tools import FULLSTACK_TOOL_NAMES

# Terminal, file editing, and task tracking come from the SDK. The full-stack
# tools are the ones this package registers on import.
BASE_TOOL_NAMES = [
    TerminalTool.name,
    FileEditorTool.name,
    TaskTrackerTool.name,
]


def build_llm(config: AgentConfig | None = None) -> LLM:
    """Create the LLM from a config, resolving the API key."""
    config = config or default_config()
    return LLM(
        usage_id="agent",
        model=config.model,
        base_url=config.base_url,
        api_key=SecretStr(config.resolved_api_key()),
        temperature=config.temperature,
    )


def build_agent(config: AgentConfig | None = None) -> Agent:
    """Build the BuffStack agent.

    Args:
        config: Runtime settings. Defaults to environment-derived settings.

    Returns:
        An :class:`Agent` wired with the base SDK tools and the full-stack tools.
    """
    config = config or default_config()
    llm = build_llm(config)
    tools = [Tool(name=name) for name in BASE_TOOL_NAMES + FULLSTACK_TOOL_NAMES]
    system_prompt = prompts.SYSTEM_PROMPT.substitute(
        current_date=date.today().isoformat()
    )
    return Agent(llm=llm, tools=tools, system_prompt=system_prompt)
