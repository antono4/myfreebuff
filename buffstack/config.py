"""Configuration for the BuffStack agent.

Resolution order for every field: explicit argument, then environment variable,
then a sensible default. The defaults match the managed LLM endpoint available
inside an OpenHands runtime, so the agent works out of the box there.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MODEL = "openai/deepseek-v4.1-flash"
DEFAULT_BASE_URL = "https://llm-proxy.app.all-hands.dev/v1"
DEFAULT_PORT = 12000


@dataclass(slots=True)
class AgentConfig:
    """Runtime settings for a BuffStack conversation."""

    model: str = DEFAULT_MODEL
    base_url: str | None = DEFAULT_BASE_URL
    api_key: str | None = None
    port: int = DEFAULT_PORT
    max_iterations: int = 120
    temperature: float = 0.0
    verbose: bool = True

    def resolved_api_key(self) -> str:
        """Return the API key, falling back to environment variables.

        Raises:
            ValueError: when no key can be found.
        """
        key = self.api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENHANDS_API_KEY")
        if not key:
            raise ValueError(
                "No LLM API key found. Pass --api-key, set LLM_API_KEY, or run "
                "inside an OpenHands runtime."
            )
        return key


def default_config(**overrides: object) -> AgentConfig:
    """Build a config from environment variables with optional overrides."""
    env_port = os.getenv("BUFFSTACK_PORT")
    config = AgentConfig(
        model=os.getenv("LLM_MODEL", DEFAULT_MODEL),
        base_url=os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL),
        port=int(env_port) if env_port else DEFAULT_PORT,
    )
    for key, value in overrides.items():
        if value is not None and hasattr(config, key):
            setattr(config, key, value)
    return config
