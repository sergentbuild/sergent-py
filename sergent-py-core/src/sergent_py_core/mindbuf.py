"""Define the MindBuf observation channel supplied to each run. @sergent/docs/framework.md"""

from __future__ import annotations


class MindBuf:
    """Render context-ready out-of-Scene observation text. @sergent/docs/framework.md"""

    def export(self) -> str:
        """Return context-ready observation text without mutation. @sergent/docs/framework.md"""
        return ""
