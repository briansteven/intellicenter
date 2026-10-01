"""Diagnostics support for Intellicenter."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN
from .pyintellicenter import PROPNAME_ATTR, SNAME_ATTR, SYSTEM_TYPE

# the system object's SNAME is what its unique ID is made from
TO_REDACT_SYSTEM = {SNAME_ATTR, PROPNAME_ATTR}
TO_REDACT = {"PASSWRD"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    handler = entry.runtime_data
    controller = handler.controller
    integration = await async_get_integration(hass, DOMAIN)

    objects = [
        {
            "objnam": obj.objnam,
            "objtype": obj.objtype,
            "subtype": obj.subtype,
            "properties": async_redact_data(
                obj.properties,
                TO_REDACT_SYSTEM | TO_REDACT if obj.objtype == SYSTEM_TYPE else TO_REDACT,
            ),
        }
        for obj in controller.model.objectList
    ]

    lastResponse = controller.lastResponse
    systemInfo = controller.systemInfo

    return {
        "integration_version": str(integration.version),
        "entry": {
            "title": REDACTED,
            "unique_id": REDACTED,
            "version": f"{entry.version}.{entry.minor_version}",
            "data": async_redact_data(dict(entry.data), {CONF_HOST}),
        },
        "system": {
            "firmware": systemInfo.swVersion if systemInfo else None,
            "uses_metric": systemInfo.usesMetric if systemInfo else None,
            "objects": controller.model.numObjects,
        },
        "connection": {
            "connected": controller.connected,
            "seconds_since_last_answer": (
                round(time.monotonic() - lastResponse, 1)
                if lastResponse is not None
                else None
            ),
            "keep_alive_interval": controller.keepAliveInterval,
            "keep_alive_timeout": controller.keepAliveTimeout,
        },
        "objects": objects,
    }
