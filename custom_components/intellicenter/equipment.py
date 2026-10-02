"""Follow changes to the IntelliCenter's equipment while Home Assistant runs."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .entity import DEVICE_TYPES, get_device, object_device_identifier
from .pyintellicenter import (
    BODY_ATTR,
    BODY_TYPE,
    CHEM_TYPE,
    CIRCUIT_ATTR,
    CIRCUIT_TYPE,
    FEATR_ATTR,
    FILTER_ATTR,
    HEATER_TYPE,
    OBJTYP_ATTR,
    SNAME_ATTR,
    SUBTYP_ATTR,
    ModelController,
)

_LOGGER = logging.getLogger(__name__)

# how often the list of objects is compared with the IntelliCenter's
CHECK_INTERVAL = timedelta(minutes=15)

# seconds to wait after a change before reloading: changes made at the panel
# or in the Pentair app often come several at a time
SETTLE_DELAY = 60

# settings that decide which entities an object gets
SHAPING_ATTRIBUTES = {
    BODY_TYPE: (FILTER_ATTR, CIRCUIT_ATTR),  # the body's circuit (its egg timer)
    CIRCUIT_TYPE: (FEATR_ATTR,),  # featured circuits are switches
    HEATER_TYPE: (BODY_ATTR,),  # the bodies a heater serves get water heaters
    CHEM_TYPE: (BODY_ATTR,),  # a chlorinator gets an output setting per body
}


class EquipmentWatcher:
    """Reload the integration when the IntelliCenter's equipment changes.

    Equipment added or removed, a circuit made featured (or not), a heater or
    chlorinator assigned to other bodies, a firmware update: the entities are
    made from these at setup, so the integration reloads (after SETTLE_DELAY)
    to pick them up.
    Changes show in the updates the IntelliCenter pushes for settings it
    reports, and in a comparison of its list of objects with the integration's
    every CHECK_INTERVAL and after reconnecting.

    A renamed body, pump, heater or chemistry controller renames its device
    right away (the names of other entities follow their objects already).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        controller: ModelController,
        objectTypes: set[str],
    ):
        """Initialize."""
        self._hass = hass
        self._entry = entry
        self._controller = controller
        self._objectTypes = objectTypes
        self._signature = self._modelSignature()
        self._firmware = self._firmwareVersion()
        self._unsubscribers: list[CALLBACK_TYPE] = []
        self._reloadTimer: CALLBACK_TYPE | None = None
        self.delay = SETTLE_DELAY

    def _modelSignature(self) -> dict[str, tuple]:
        """Return what decides the entities, per object of the model."""
        return {
            obj.objnam: (
                obj.objtype,
                obj.subtype,
                tuple(obj[attr] for attr in SHAPING_ATTRIBUTES.get(obj.objtype, ())),
            )
            for obj in self._controller.model
        }

    def _firmwareVersion(self) -> str | None:
        info = self._controller.systemInfo
        return info.swVersion if info else None

    @callback
    def async_start(self) -> None:
        """Start the periodic comparison."""
        self._unsubscribers.append(
            async_track_time_interval(self._hass, self._async_poll, CHECK_INTERVAL)
        )

    @callback
    def async_stop(self) -> None:
        """Stop watching."""
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        if self._reloadTimer:
            self._reloadTimer()
            self._reloadTimer = None

    @callback
    def async_updated(self, updates: dict[str, dict[str, str]]) -> None:
        """Handle updates pushed by the IntelliCenter."""
        for objnam, changes in updates.items():
            obj = self._controller.model[objnam]
            if obj is None:
                continue
            if SNAME_ATTR in changes and obj.objtype in DEVICE_TYPES and obj.sname:
                self._renameDevice(obj.objnam, obj.sname)
            if changes.keys() & set(SHAPING_ATTRIBUTES.get(obj.objtype, ())) or (
                SUBTYP_ATTR in changes
            ):
                if self._modelSignature() != self._signature:
                    self._scheduleReload("its settings changed")

    @callback
    def _renameDevice(self, objnam: str, name: str) -> None:
        registry = dr.async_get(self._hass)
        device = get_device(
            registry, object_device_identifier(self._entry, objnam), self._entry.entry_id
        )
        if device and device.name != name:
            registry.async_update_device(device.id, name=name)

    async def _async_poll(self, _now=None) -> None:
        await self.async_check()

    async def async_check(self) -> None:
        """Compare the IntelliCenter's objects with the integration's."""
        if not self._controller.connected or self._reloadTimer:
            return
        if self._firmwareVersion() != self._firmware:
            # what the IntelliCenter offers (alerts...) can depend on it, and its
            # device shows the version
            self._scheduleReload(
                f"its firmware changed from {self._firmware} to"
                f" {self._firmwareVersion()}"
            )
            return
        try:
            objects = await self._controller.getAllObjects([OBJTYP_ATTR, SUBTYP_ATTR])
        except Exception as err:  # noqa: BLE001 - try again next time
            _LOGGER.debug(f"could not list the IntelliCenter's objects: {err!r}")
            return
        current = {
            item["objnam"]: (item["params"].get(OBJTYP_ATTR), item["params"].get(SUBTYP_ATTR))
            for item in objects
            if item["params"].get(OBJTYP_ATTR) in self._objectTypes
        }
        known = {objnam: shape[:2] for objnam, shape in self._signature.items()}
        if current != known:
            added = sorted(current.keys() - known.keys())
            removed = sorted(known.keys() - current.keys())
            changed = sorted(
                objnam
                for objnam in current.keys() & known.keys()
                if current[objnam] != known[objnam]
            )
            self._scheduleReload(
                f"added {added}, removed {removed}, changed {changed}"
            )

    @callback
    def _scheduleReload(self, reason: str) -> None:
        if self._reloadTimer:
            return
        _LOGGER.info(
            f"the IntelliCenter's equipment changed ({reason}):"
            f" reloading in {self.delay}s"
        )

        @callback
        def reload(_now) -> None:
            self._reloadTimer = None
            self._hass.config_entries.async_schedule_reload(self._entry.entry_id)

        self._reloadTimer = async_call_later(self._hass, self.delay, reload)
