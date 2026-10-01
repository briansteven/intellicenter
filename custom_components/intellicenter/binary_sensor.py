"""Pentair Intellicenter binary sensors."""

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from .entity import PoolEntity
from .pyintellicenter import (
    ACT_ATTR,
    BODY_TYPE,
    CIRCUIT_TYPE,
    GPM_ATTR,
    HEATER_ATTR,
    HEATER_TYPE,
    HTMODE_ATTR,
    PUMP_TYPE,
    PWR_ATTR,
    RPM_ATTR,
    SCHED_TYPE,
    SERVICE_ATTR,
    STATUS_ATTR,
    SYSTEM_TYPE,
    VACFLO_ATTR,
    ModelController,
    PoolObject,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Load pool sensors based on a config entry."""

    controller: ModelController = entry.runtime_data.controller

    sensors = []

    obj: PoolObject
    for obj in controller.model.objectList:
        if obj.objtype == CIRCUIT_TYPE and obj.subtype == "FRZ":
            sensors.append(FreezeProtection(entry, controller, obj))
        elif obj.objtype == HEATER_TYPE:
            sensors.append(HeaterBinarySensor(entry, controller, obj))
        elif obj.objtype == SCHED_TYPE:
            sensors.append(
                PoolBinarySensor(
                    entry,
                    controller,
                    obj,
                    attribute_key=ACT_ATTR,
                    name=f"{obj.sname or obj.objnam} schedule",
                    enabled_by_default=False,
                    extraStateAttributes={VACFLO_ATTR},
                )
            )
        elif obj.objtype == PUMP_TYPE:
            sensors.append(PumpBinarySensor(entry, controller, obj))
        elif obj.objtype == SYSTEM_TYPE and obj[SERVICE_ATTR]:
            sensors.append(ServiceMode(entry, controller, obj))
    async_add_entities(sensors)


# -------------------------------------------------------------------------------------


class PoolBinarySensor(PoolEntity, BinarySensorEntity):
    """Representation of a Pentair Binary Sensor."""

    def __init__(
        self,
        entry: ConfigEntry,
        controller: ModelController,
        poolObject: PoolObject,
        valueForON="ON",
        **kwargs,
    ):
        """Initialize."""
        super().__init__(entry, controller, poolObject, **kwargs)
        self._valueForON = valueForON

    @property
    def is_on(self):
        """Return true if sensor is on, None if the system doesn't say."""
        value = self._poolObject[self._attribute_key]
        if value is None:
            return None
        return value == self._valueForON


class FreezeProtection(PoolBinarySensor):
    """On while the IntelliCenter protects the equipment from freezing."""

    _attr_device_class = BinarySensorDeviceClass.COLD


class ServiceMode(PoolBinarySensor):
    """On while the IntelliCenter isn't in its normal (automatic) mode.

    SERVICE is AUTO normally, and MANUAL (service mode) or TIMOUT (service mode
    that ends by itself) while equipment is worked on: the IntelliCenter then
    suspends its normal operation, such as schedules.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry, controller, poolObject):
        """Initialize."""
        super().__init__(
            entry,
            controller,
            poolObject,
            attribute_key=SERVICE_ATTR,
            name="Service mode",
            icon="mdi:account-wrench",
            extraStateAttributes={SERVICE_ATTR},
        )

    @property
    def is_on(self):
        """Return true when not in automatic mode."""
        value = self._poolObject[SERVICE_ATTR]
        if value is None:
            return None
        return value != "AUTO"


# -------------------------------------------------------------------------------------

# Real time telemetry a variable speed pump publishes while it turns, most to least
# reliable. A pump that publishes none of these has only STATUS to go on.
PUMP_ACTIVITY_ATTRS = (RPM_ATTR, PWR_ATTR, GPM_ATTR)


class PumpBinarySensor(PoolEntity, BinarySensorEntity):
    """Representation of a Pentair pump, on while it is actually running."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(
        self,
        entry: ConfigEntry,
        controller: ModelController,
        poolObject: PoolObject,
        **kwargs,
    ):
        """Initialize."""
        super().__init__(entry, controller, poolObject, **kwargs)
        self._activityAttrs = [
            attr for attr in PUMP_ACTIVITY_ATTRS if poolObject[attr] is not None
        ]

    @property
    def is_on(self):
        """Return true if the pump is running."""
        if not self._activityAttrs:
            # Single speed pumps report no telemetry, so STATUS is all we have.
            return self._poolObject[STATUS_ATTR] == self._poolObject.onStatus
        for attr in self._activityAttrs:
            try:
                if float(self._poolObject[attr]) > 0:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def isUpdated(self, updates: dict[str, dict[str, str]]) -> bool:
        """Return true if the entity is updated by the updates from Intellicenter."""

        keys = updates.get(self._poolObject.objnam, {}).keys()
        if not self._activityAttrs:
            return STATUS_ATTR in keys
        return bool(set(self._activityAttrs) & keys)


# -------------------------------------------------------------------------------------


class HeaterBinarySensor(PoolEntity, BinarySensorEntity):
    """A heater, on while it heats (or, for a heat pump, cools) a body."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(
        self,
        entry: ConfigEntry,
        controller: ModelController,
        poolObject: PoolObject,
        **kwargs,
    ):
        """Initialize."""
        super().__init__(entry, controller, poolObject, **kwargs)
        self._attr_icon = "mdi:fire-circle"

    @property
    def is_on(self) -> bool:
        """Return true if the heater is running for any body of water.

        Every body that selects the heater counts, not only those it is
        assigned to (the heater's BODY): some IntelliCenters heat a body with a
        heater that isn't assigned to it.
        """
        for body in self._controller.model.getByType(BODY_TYPE):
            if (
                body[STATUS_ATTR] == "ON"
                and body[HEATER_ATTR] == self._poolObject.objnam
                and body[HTMODE_ATTR] not in (None, "0")
            ):
                return True
        return False

    def isUpdated(self, updates: dict[str, dict[str, str]]) -> bool:
        """Return true if the entity is updated by the updates from Intellicenter."""

        for objnam, changes in updates.items():
            obj = self._controller.model[objnam]
            if (
                obj is not None
                and obj.objtype == BODY_TYPE
                and {STATUS_ATTR, HEATER_ATTR, HTMODE_ATTR} & changes.keys()
            ):
                return True
        return False
