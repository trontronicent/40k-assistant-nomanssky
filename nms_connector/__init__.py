"""No Man's Sky connector for the 40k Assistant (plugin API 2 backend)."""

from .plugin import NmsConnector


def create_plugin(ctx):
    """Entry point named in strategicum-plugin.json."""
    return NmsConnector(ctx)
