"""Standalone host for the No Man's Sky connector: the same plugin code without the 40k Assistant.

The connector (`nms_connector`) runs unchanged under two hosts - the 40k Assistant's plugin system and
this one. See CLAUDE.md, "two hosts, one codebase": this package adapts to the connector, never the
other way round.
"""

HOST_VERSION = "1"
