"""Pentair Intellicenter covers."""

import logging

from homeassistant.components.cover import CoverEntity, CoverEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .entity import PoolEntity
from .pyintellicenter import (
    EXTINSTR_TYPE,
    NORMAL_ATTR,
    POSIT_ATTR,
    STATUS_ATTR,
    ModelController,
    PoolObject,
)

_LOGGER = logging.getLogger(__name__)

# values of POSIT and NORMAL
ON, OFF = "ON", "OFF"

# -------------------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Load pool covers based on a config entry.

    The IntelliCenter defines cover objects whether or not a cover is installed.
    Only those that report a position (POSIT) are covers Home Assistant can
    show: older firmware (IC 1.064) reports none at all.
    """
    controller: ModelController = entry.runtime_data.controller

    covers = []

    obj: PoolObject
    for obj in controller.model.objectList:
        if (
            obj.objtype == EXTINSTR_TYPE
            and obj.subtype == "COVER"
            and obj[POSIT_ATTR] in (ON, OFF)
        ):
            covers.append(PoolCover(entry, controller, obj))

    async_add_entities(covers)

# -------------------------------------------------------------------------------------


class PoolCover(PoolEntity, CoverEntity):
    """A pool or spa cover, as the IntelliCenter reports it.

    POSIT is the cover's position, combined with NORMAL (the position the
    cover is in when POSIT is ON). STATUS only says whether the cover is
    enabled in the IntelliCenter's settings, so it is not its position.

    Covers are read-only here: moving a cover without seeing the water is a
    safety risk, and how the IntelliCenter takes a position change isn't
    established.
    """

    _attr_supported_features = CoverEntityFeature(0)

    def __init__(
        self,
        entry: ConfigEntry,
        controller: ModelController,
        poolObject: PoolObject,
    ):
        """Initialize."""
        super().__init__(
            entry,
            controller,
            poolObject,
            extraStateAttributes=[NORMAL_ATTR, POSIT_ATTR],
            icon="mdi:arrow-expand-horizontal",
        )

    @property
    def is_closed(self) -> bool | None:
        """Return true if the cover is closed, None if unknown."""
        position, normal = self._poolObject[POSIT_ATTR], self._poolObject[NORMAL_ATTR]
        if position not in (ON, OFF) or normal not in (ON, OFF):
            return None
        # NORMAL ON: closed when POSIT is ON; NORMAL OFF: closed when POSIT is OFF
        return position == normal

    def isUpdated(self, updates: dict[str, dict[str, str]]) -> bool:
        """Return true if the entity is updated by the updates from Intellicenter."""
        myUpdates = updates.get(self._poolObject.objnam, {})
        return bool({STATUS_ATTR, NORMAL_ATTR, POSIT_ATTR} & myUpdates.keys())
