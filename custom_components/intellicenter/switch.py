"""Pentair Intellicenter switches."""

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from .entity import PoolEntity, egg_timer_circuits
from .pyintellicenter import (
    BODY_TYPE,
    CHEM_TYPE,
    CIRCUIT_TYPE,
    DNTSTP_ATTR,
    HEATER_ATTR,
    HTMODE_ATTR,
    SUPER_ATTR,
    SYSTEM_TYPE,
    VACFLO_ATTR,
    VOL_ATTR,
    ModelController,
    PoolObject,
)

_LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Load a Pentair switch based on a config entry."""
    controller: ModelController = entry.runtime_data.controller

    switches = []

    obj: PoolObject
    for obj in controller.model.objectList:
        if obj.objtype == BODY_TYPE:
            switches.append(PoolBody(entry, controller, obj))
        elif (
            obj.objtype == CHEM_TYPE
            and obj.subtype == "ICHLOR"
            and SUPER_ATTR in obj.attributes
        ):
            switches.append(
                PoolCircuit(
                    entry,
                    controller,
                    obj,
                    attribute_key=SUPER_ATTR,
                    name="Superchlorinate",
                    icon="mdi:alpha-s-box-outline",
                )
            )
        elif (
            obj.objtype == CIRCUIT_TYPE
            and not (obj.isALight or obj.isALightShow)
            and obj.isFeatured
        ):
            switches.append(
                PoolCircuit(entry, controller, obj, icon="mdi:alpha-f-box-outline"))
        elif (
            obj.objtype == CIRCUIT_TYPE
            and obj.subtype == "CIRCGRP"
        ):
            switches.append(
                PoolCircuit(entry, controller, obj, icon="mdi:alpha-g-box-outline"))
        elif obj.objtype == SYSTEM_TYPE:
            switches.append(VacationMode(entry, controller, obj))

    for circuit, body in egg_timer_circuits(controller.model):
        if circuit[DNTSTP_ATTR] in ("ON", "OFF"):
            switches.append(DoNotStop(entry, controller, circuit, body))

    async_add_entities(switches)


# -------------------------------------------------------------------------------------


class PoolCircuit(PoolEntity, SwitchEntity):
    """Representation of an standard pool circuit."""

    @property
    def is_on(self) -> bool:
        """Return the state of the circuit."""
        return self._poolObject[self._attribute_key] == self._poolObject.onStatus

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch."""
        await self.async_request_changes(
            {self._attribute_key: self._poolObject.offStatus}
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch."""
        await self.async_request_changes(
            {self._attribute_key: self._poolObject.onStatus}
        )


# -------------------------------------------------------------------------------------


class PoolBody(PoolCircuit):
    """Representation of a body of water."""

    def __init__(self, entry: ConfigEntry, controller, poolObject):
        """Initialize a Pool body from the underlying circuit."""
        super().__init__(
            entry,
            controller,
            poolObject,
            extraStateAttributes=[VOL_ATTR, HEATER_ATTR, HTMODE_ATTR],
            icon="mdi:hot-tub" if poolObject.subtype == "SPA" else "mdi:pool",
        )


class VacationMode(PoolCircuit):
    """The IntelliCenter's vacation mode."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, controller, poolObject):
        """Initialize."""
        super().__init__(
            entry,
            controller,
            poolObject,
            attribute_key=VACFLO_ATTR,
            name="Vacation mode",
            icon="mdi:palm-tree",
            enabled_by_default=False,
        )


class DoNotStop(PoolCircuit):
    """A circuit's "Don't Stop": on, it runs until turned off (no egg timer).

    Disabled by default, with the circuit's egg timer.
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, controller, circuit, body):
        """Initialize."""
        super().__init__(
            entry,
            controller,
            circuit,
            attribute_key=DNTSTP_ATTR,
            name="Do not stop"
            if body is not None
            else f"{circuit.sname or circuit.objnam} do not stop",
            icon="mdi:timer-off-outline",
            deviceObject=body,
            enabled_by_default=False,
        )

    @property
    def is_on(self) -> bool:
        """Return true if the circuit runs until turned off."""
        return self._poolObject[DNTSTP_ATTR] == "ON"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Run the circuit until turned off."""
        await self.async_request_changes({DNTSTP_ATTR: "ON"})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Use the circuit's egg timer."""
        await self.async_request_changes({DNTSTP_ATTR: "OFF"})
