"""Base entity and devices of the Pentair IntelliCenter integration."""

from __future__ import annotations

import asyncio
from functools import partial
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, UnitOfTemperature
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, dispatcher
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from yarl import URL

from .const import COMMAND_TIMEOUT, DOMAIN, connection_signal, update_signal
from .pyintellicenter import (
    BODY_TYPE,
    CHEM_TYPE,
    CIRCUIT_ATTR,
    CIRCUIT_TYPE,
    FILTER_ATTR,
    HEATER_TYPE,
    PUMP_TYPE,
    SCHED_TYPE,
    SNAME_ATTR,
    STATUS_ATTR,
    TIME_ATTR,
    CommandError,
    ModelController,
    PoolModel,
    PoolObject,
)

_LOGGER = logging.getLogger(__name__)

# object types that get a device of their own; every other object's entities
# belong to the IntelliCenter's device
DEVICE_TYPES = {BODY_TYPE, CHEM_TYPE, HEATER_TYPE, PUMP_TYPE, SCHED_TYPE}

MODELS = {
    BODY_TYPE: {"POOL": "Pool", "SPA": "Spa"},
    CHEM_TYPE: {"ICHLOR": "IntelliChlor", "ICHEM": "IntelliChem"},
    HEATER_TYPE: {
        "GENERIC": "Gas heater",
        "SOLAR": "Solar heater",
        "HTPMP": "Heat pump",
        "ULTRA": "UltraTemp heat pump",
        "HCOMBO": "Hybrid heater",
        "MASTER": "MasterTemp heater",
        "MAX": "Max-E-Therm heater",
    },
    PUMP_TYPE: {
        "SS": "Single speed pump",
        "DS": "Two speed pump",
        "SPEED": "Variable speed pump",
        "FLOW": "Variable flow pump",
        "VSF": "Variable speed and flow pump",
    },
}
DEFAULT_MODELS = {
    BODY_TYPE: "Body of water",
    CHEM_TYPE: "Chemistry controller",
    HEATER_TYPE: "Heater",
    PUMP_TYPE: "Pump",
    SCHED_TYPE: "Schedule",
}


# Home Assistant 2026.9 links a device to the one it is connected through by
# registry ID (via_device_id); older releases by identifier (via_device)
VIA_DEVICE_ID = "via_device_id" in DeviceInfo.__annotations__


class _Default:
    """Marker for 'name the entity after its object'."""


DEFAULT_NAME: Any = _Default()


def system_id(entry: ConfigEntry) -> str:
    """Return the stable identifier of the IntelliCenter of a config entry.

    The config flow sets the entry's unique ID from the IntelliCenter itself, so
    it is the same every time the system is added to Home Assistant (unlike the
    entry ID). Entries without one fall back to their entry ID.
    """
    return entry.unique_id or entry.entry_id


def system_device_info(entry: ConfigEntry, controller: ModelController) -> DeviceInfo:
    """Return the device of the IntelliCenter itself."""
    info = controller.systemInfo
    device_info = DeviceInfo(
        identifiers={(DOMAIN, system_id(entry))},
        manufacturer="Pentair",
        model="IntelliCenter",
        name=info.propName if info else entry.title,
        sw_version=info.swVersion if info else None,
    )
    try:
        # (brackets around an IPv6 address)
        device_info["configuration_url"] = str(
            URL.build(scheme="http", host=entry.data[CONF_HOST])
        )
    except ValueError:
        pass
    return device_info


def object_device_identifier(entry: ConfigEntry, objnam: str) -> tuple[str, str]:
    """Return the device identifier of an object with a device of its own."""
    return (DOMAIN, f"{system_id(entry)}_{objnam}")


def object_device_name(obj: PoolObject, model: PoolModel | None = None) -> str:
    """Return the name of an object's device.

    A schedule is named after what it's called in the IntelliCenter, which is
    often the circuit's name ("Pool"): "Pool schedule". Schedules with the same
    name (two for the pool) are numbered, in the IntelliCenter's order:
    "Pool schedule 1", "Pool schedule 2".
    """
    if obj.objtype != SCHED_TYPE:
        return obj.sname or obj.objnam

    def schedule_name(schedule: PoolObject) -> str:
        name = schedule.sname or schedule.objnam
        if not name.lower().endswith("schedule"):
            name = f"{name} schedule"
        return name

    name = schedule_name(obj)
    if model is not None:
        same = sorted(
            other.objnam
            for other in model.getByType(SCHED_TYPE)
            if schedule_name(other).lower() == name.lower()
        )
        if len(same) > 1 and obj.objnam in same:
            name = f"{name} {same.index(obj.objnam) + 1}"
    return name


def object_device_info(
    entry: ConfigEntry,
    obj: PoolObject,
    system_device_id: str | None,
    model: PoolModel | None = None,
) -> DeviceInfo:
    """Return the device of a body, pump, heater, chemistry controller or schedule.

    system_device_id: the registry ID of the IntelliCenter's device, which these
    are connected through.
    """
    model_name = MODELS.get(obj.objtype, {}).get(obj.subtype) or DEFAULT_MODELS.get(
        obj.objtype
    )
    info = DeviceInfo(
        identifiers={object_device_identifier(entry, obj.objnam)},
        manufacturer="Pentair",
        model=model_name,
        name=object_device_name(obj, model),
    )
    if VIA_DEVICE_ID:
        if system_device_id:
            info["via_device_id"] = system_device_id
    else:
        info["via_device"] = (DOMAIN, system_id(entry))
    return info


def get_device(
    device_registry: dr.DeviceRegistry, identifier: tuple[str, str], entry_id: str
) -> dr.DeviceEntry | None:
    """Return a config entry's device with the given identifier."""
    if hasattr(device_registry, "async_get_device_by_identifier"):
        # Home Assistant 2026.9 and later
        return device_registry.async_get_device_by_identifier(identifier, entry_id)
    return device_registry.async_get_device(identifiers={identifier})


# circuits a user doesn't turn on: freeze protection, and the "all lights
# on/off" commands
NOT_USER_CIRCUITS = {"FRZ", "ALL"}


def egg_timer_circuits(
    model: PoolModel,
) -> list[tuple[PoolObject, PoolObject | None]]:
    """Return the circuits whose egg timer is offered, with their body of water.

    A circuit's egg timer turns it off after it has run that many minutes since
    it was turned on by hand (not by a schedule), unless its "Don't Stop" is
    on. It is offered for the circuits Home Assistant shows: those of the bodies
    of water (paired with their body), lights and light shows, featured
    circuits and circuit groups (paired with None).
    """
    # a body's circuit is its FILTER (IC 1.064) or CIRCUIT
    body_of = {}
    for body in model.getByType(BODY_TYPE):
        for attribute in (FILTER_ATTR, CIRCUIT_ATTR):
            if body[attribute]:
                body_of.setdefault(body[attribute], body)

    circuits = []
    for obj in model.objectList:
        if obj.objtype != CIRCUIT_TYPE or obj.subtype in NOT_USER_CIRCUITS:
            continue
        try:
            int(obj[TIME_ATTR])
        except (TypeError, ValueError):
            continue
        body = body_of.get(obj.objnam)
        if (
            body is not None
            or obj.isALight
            or obj.isALightShow
            or obj.isFeatured
            or obj.subtype == "CIRCGRP"
        ):
            circuits.append((obj, body))
    return circuits


class PoolEntity(Entity):
    """An entity linked to an object of the IntelliCenter.

    Bodies of water, pumps, heaters and chemistry controllers are devices of
    their own (connected through the IntelliCenter): their main entity takes the
    device's name and the others are named after what they measure ("Power",
    "Salt"...). Everything else (circuits, lights, sensors, schedules...)
    belongs to the IntelliCenter's device and is named after its object.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry: ConfigEntry,
        controller: ModelController,
        poolObject: PoolObject,
        attribute_key=STATUS_ATTR,
        name=DEFAULT_NAME,
        enabled_by_default=True,
        extraStateAttributes=None,
        icon: str | None = None,
        unit_of_measurement: str | None = None,
        deviceObject: PoolObject | None = None,
    ):
        """Initialize a Pool entity.

        name: the entity's name, None for the name of its device, or (the
        default) None on a device of its own and the object's name otherwise.
        deviceObject: the object whose device the entity belongs to, when not
        its own (a pump's speed setting for a circuit belongs to the pump).
        """
        self._entry = entry
        self._entry_id = entry.entry_id
        self._controller = controller
        self._poolObject = poolObject
        self._attr_available = True
        self._extra_state_attributes = extraStateAttributes or set()
        self._attribute_key = attribute_key
        self._attr_entity_registry_enabled_default = enabled_by_default
        self._attr_native_unit_of_measurement = unit_of_measurement
        self._attr_icon = icon

        deviceObject = deviceObject or poolObject
        self._ownDevice = deviceObject.objtype in DEVICE_TYPES
        # an entity named after its object follows that object's name
        self._followsName = name is DEFAULT_NAME and not self._ownDevice
        if name is DEFAULT_NAME:
            name = None if self._ownDevice else (poolObject.sname or poolObject.objnam)
        self._attr_name = name

        self._attr_unique_id = system_id(entry) + poolObject.objnam
        if attribute_key != STATUS_ATTR:
            self._attr_unique_id += attribute_key

        self._attr_device_info = (
            object_device_info(
                entry,
                deviceObject,
                getattr(entry.runtime_data, "system_device_id", None),
                controller.model,
            )
            if self._ownDevice
            else DeviceInfo(identifiers={(DOMAIN, system_id(entry))})
        )

        _LOGGER.debug(f"mapping {poolObject}")

    async def async_added_to_hass(self):
        """Entity is added to Home Assistant."""
        # the connection may have dropped while the entities were being set up
        self._attr_available = self._controller.connected
        self.async_on_remove(
            dispatcher.async_dispatcher_connect(
                self.hass, update_signal(self._entry_id), self._update_callback
            )
        )

        self.async_on_remove(
            dispatcher.async_dispatcher_connect(
                self.hass,
                connection_signal(self._entry_id),
                self._connection_callback,
            )
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes of the entity."""

        object = self._poolObject

        objectType = object.objtype
        if object.subtype:
            objectType += f"/{object.subtype}"

        attributes = {"OBJNAM": object.objnam, "OBJTYPE": objectType}

        if object.status:
            attributes["Status"] = object.status

        for attribute in self._extra_state_attributes:
            if object[attribute]:
                attributes[attribute] = object[attribute]

        return attributes

    async def async_request_changes(self, changes: dict) -> None:
        """Make changes (key:value pairs) to the object, raising if they fail.

        The IntelliCenter answers each change; one it refuses, doesn't answer
        in time, or can't receive (no connection) raises an error that Home
        Assistant shows, instead of the change being silently lost. The new
        values themselves arrive as updates.
        """
        poolObject = self._poolObject
        placeholders = {"name": poolObject.sname or poolObject.objnam}
        try:
            await self._controller.requestChangesAndWait(
                poolObject.objnam, changes, COMMAND_TIMEOUT
            )
        except CommandError as err:
            _LOGGER.warning(
                f"the IntelliCenter refused {changes} for {poolObject.objnam}"
                f" (error {err.errorCode})"
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_refused",
                translation_placeholders={**placeholders, "code": str(err.errorCode)},
            ) from err
        except TimeoutError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_timeout",
                translation_placeholders={
                    **placeholders,
                    "seconds": str(COMMAND_TIMEOUT),
                },
            ) from err
        except ConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_connected",
                translation_placeholders=placeholders,
            ) from err

    def requestChanges(self, changes: dict) -> None:
        """Request changes as key:value pairs to the associated Pool object.

        Fire and forget, usable from any thread: whatever changes were requested
        will be reflected as an update if successful (a refusal is only
        logged). Commands use async_request_changes instead.

        The connection to the system belongs to the event loop and asyncio
        transports are not thread safe, so a request made from any other thread
        is handed over to the loop instead of being written from that thread.
        """
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:  # not in an event loop at all
            running_loop = None

        if self.hass is None or running_loop is self.hass.loop:
            self._controller.requestChanges(
                self._poolObject.objnam, changes, waitForResponse=False
            )
        else:
            self.hass.loop.call_soon_threadsafe(
                partial(
                    self._controller.requestChanges,
                    self._poolObject.objnam,
                    changes,
                    waitForResponse=False,
                )
            )

    def isUpdated(self, updates: dict[str, dict[str, str]]) -> bool:
        """Return true if the entity is updated by the updates from Intellicenter."""

        return self._attribute_key in updates.get(self._poolObject.objnam, {})

    @callback
    def _update_callback(self, updates: dict[str, dict[str, str]]):
        """Update the entity if its underlying pool object has changed."""

        renamed = (
            self._followsName
            and SNAME_ATTR in updates.get(self._poolObject.objnam, {})
            and self._poolObject.sname
        )
        if renamed:
            self._attr_name = self._poolObject.sname

        if renamed or self.isUpdated(updates):
            self._attr_available = True
            _LOGGER.debug(f"updating {self} from {updates}")
            self.async_write_ha_state()

    @callback
    def _connection_callback(self, is_connected):
        """Mark the entity as unavailable after being disconnected from the server."""
        if is_connected:
            poolObject = self._controller.model[self._poolObject.objnam]
            if poolObject is None:
                # the object was removed from the system while we were
                # disconnected: the entity stays unavailable
                return
            self._poolObject = poolObject
        self._attr_available = is_connected
        self.async_write_ha_state()

    def pentairTemperatureSettings(self):
        """Return the temperature units from the Pentair system."""
        return (
            UnitOfTemperature.CELSIUS
            if self._controller.systemInfo.usesMetric
            else UnitOfTemperature.FAHRENHEIT
        )
