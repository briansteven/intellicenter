"""Constants for the Pentair IntelliCenter integration."""

DOMAIN = "intellicenter"

# seconds the IntelliCenter may stay silent while the integration is set up
# (Home Assistant retries the setup later if it does)
SETUP_TIMEOUT = 30

# seconds the IntelliCenter may stay silent while a config flow checks it
FLOW_TIMEOUT = 15


def update_signal(entry_id: str) -> str:
    """Return the dispatcher signal for changes to a system's objects."""
    return f"{DOMAIN}_UPDATE_{entry_id}"


def connection_signal(entry_id: str) -> str:
    """Return the dispatcher signal for a system's connection state."""
    return f"{DOMAIN}_CONNECTION_{entry_id}"
