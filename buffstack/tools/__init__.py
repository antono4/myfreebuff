"""Full-stack tools for the BuffStack agent.

Importing this package registers every tool with the OpenHands tool registry.
"""

from buffstack.tools.add_endpoint import AddEndpointTool
from buffstack.tools.dashboard import CreateDashboardTool
from buffstack.tools.scaffold import ScaffoldTool
from buffstack.tools.server import RunServerTool
from buffstack.tools.validate import ValidateTool

FULLSTACK_TOOL_NAMES = [
    ScaffoldTool.name,
    AddEndpointTool.name,
    CreateDashboardTool.name,
    RunServerTool.name,
    ValidateTool.name,
]

__all__ = [
    "AddEndpointTool",
    "CreateDashboardTool",
    "ScaffoldTool",
    "RunServerTool",
    "ValidateTool",
    "FULLSTACK_TOOL_NAMES",
]
