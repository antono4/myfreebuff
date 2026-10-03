"""BuffStack — an OpenHands SDK agent that builds full-stack apps with an HTML dashboard.

The agent is inspired by the architecture of CodebuffAI/freebuff: a single-loop
coding root agent with an explicit tool set and a system prompt that carries the
engineering discipline. It adds a full-stack tool set on top of the standard
OpenHands tools so the agent can scaffold a project, add JSON API endpoints,
generate an HTML dashboard, run the server, and validate the result.
"""

from buffstack.agent import build_agent
from buffstack.config import AgentConfig, default_config

__all__ = ["build_agent", "AgentConfig", "default_config"]
__version__ = "0.1.0"
