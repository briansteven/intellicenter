"""Pentair Intellicenter water heaters."""

import logging
from typing import Any, Optional

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, STATE_OFF
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.core import HomeAssistant

from . import PoolEntity
from .const import DOMAIN
from .pyintellicenter import (
    BODY_ATTR,
    BODY_TYPE,
    HEATER_ATTR,
    HEATER_TYPE,
    HTMODE_ATTR,
    LISTORD_ATTR,
    LOTMP_ATTR,
    LSTTMP_ATTR,
    NULL_OBJNAM,
    STATUS_ATTR,
    ModelController,
    PoolObject,
)

# from homeassistant.components.climate.const import CURRENT_HVAC_OFF, CURRENT_HVAC_HEAT, CURRENT_HVAC_IDLE
_LOGGER = logging.getLogger(__name__)


def heater_serves_body(heater: PoolObject, body: PoolObject) -> bool:
    """Return True if the heater is assigned to the given body of water.

    The heater's BODY attribute lists, space separated, the bodies the
    IntelliCenter lets it heat (both the pool and the spa for a heater shared
    by them). Only those bodies are heated: a body can keep a heater selected
    after the heater was unassigned from it, and the IntelliCenter then doesn't
    heat it (see issues.async_check_heater_assignments).
    """
    return body.objnam in (heater[BODY_ATTR] or "").split()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Load pool sensors based on a config entry."""

    controller = hass.data[DOMAIN][entry.entry_id].controller

    # here we try to figure out which heater, if any, can be used for a given
    # body of water

    # first find all heaters
    # and sort them by their UI order (if they don't have one, use 100 and place them last)
    heaters = sorted(
        controller.model.getByType(HEATER_TYPE),
        key=lambda h: int(h[LISTORD_ATTR]) if h[LISTORD_ATTR] else 100,
    )

    bodies = controller.model.getByType(BODY_TYPE)

    water_heaters = []
    body: PoolObject
    for body in bodies:
        heater_list = []
        heater: PoolObject
        for heater in heaters:
            # if the heater supports this body, add it to the list
            if heater_serves_body(heater, body):
                heater_list.append(heater.objnam)
        if heater_list:
            water_heaters.append(PoolWaterHeater(entry, controller, body, heater_list))

    async_add_entities(water_heaters)


# -------------------------------------------------------------------------------------


class PoolWaterHeater(PoolEntity, WaterHeaterEntity, RestoreEntity):
    """Representation of a Pentair water heater."""

    LAST_HEATER_ATTR = "LAST_HEATER"

    def __init__(
        self,
        entry: ConfigEntry,
        controller: ModelController,
        poolObject: PoolObject,
        heater_list,
    ):
        """Initialize."""
        super().__init__(
            entry,
            controller,
            poolObject,
            extraStateAttributes=[HEATER_ATTR, HTMODE_ATTR],
        )
        self._heater_list = heater_list
        self._lastHeater = self._poolObject[HEATER_ATTR] or NULL_OBJNAM
        self._attr_icon = "mdi:thermometer"

    @property
    def extra_state_attributes(self) -> Optional[dict[str, Any]]:
        """Return the state attributes of the entity."""

        state_attributes = super().extra_state_attributes

        if self._lastHeater not in (None, NULL_OBJNAM):
            state_attributes[self.LAST_HEATER_ATTR] = self._lastHeater

        return state_attributes

    @property
    def unique_id(self):
        """Return a unique ID."""
        return super().unique_id + LOTMP_ATTR

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return (
            WaterHeaterEntityFeature.TARGET_TEMPERATURE
            | WaterHeaterEntityFeature.OPERATION_MODE
            | WaterHeaterEntityFeature.ON_OFF
        )

    @property
    def temperature_unit(self):
        """Return the unit of measurement used by the platform."""
        return self.pentairTemperatureSettings()

    @property
    def min_temp(self):
        """Return the minimum value."""
        return 5.0 if self._controller.systemInfo.usesMetric else 40.0

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        return 40.0 if self._controller.systemInfo.usesMetric else 104.0

    def _as_float(self, value):
        """Parse a Pentair temperature value, or return None if missing."""
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._as_float(self._poolObject[LSTTMP_ATTR])

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._as_float(self._poolObject[LOTMP_ATTR])

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperatures."""
        target_temperature = kwargs.get(ATTR_TEMPERATURE)
        self.requestChanges({LOTMP_ATTR: str(int(target_temperature))})

    def _heaterName(self, objnam: str) -> str:
        """Return the name of a heater, falling back to its id if it has none."""
        heater = self._controller.model[objnam]
        return heater.sname if heater is not None and heater.sname else objnam

    @property
    def current_operation(self):
        """Return current operation."""
        heater = self._poolObject[HEATER_ATTR]
        if heater in self._heater_list:
            return self._heaterName(heater)
        return STATE_OFF

    @property
    def operation_list(self):
        """Return the list of available operation modes."""
        return [STATE_OFF] + [self._heaterName(heater) for heater in self._heater_list]

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set new target operation mode."""
        if operation_mode == STATE_OFF:
            self._turnOff()
        else:
            for heater in self._heater_list:
                if operation_mode == self._heaterName(heater):
                    self.requestChanges({HEATER_ATTR: heater})
                    break

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn heating on, with the heater used last if there is one."""
        heater = (
            self._lastHeater
            if self._lastHeater in self._heater_list
            else self._heater_list[0]
        )
        self.requestChanges({HEATER_ATTR: heater})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn heating off."""
        self._turnOff()

    def _turnOff(self):
        self.requestChanges({HEATER_ATTR: NULL_OBJNAM})

    def isUpdated(self, updates: dict[str, dict[str, str]]) -> bool:
        """Return true if the entity is updated by the updates from Intellicenter."""

        myUpdates = updates.get(self._poolObject.objnam, {})

        updated = (
            myUpdates
            and {STATUS_ATTR, HEATER_ATTR, HTMODE_ATTR, LOTMP_ATTR, LSTTMP_ATTR}
            & myUpdates.keys()
        )

        if updated and self._poolObject[HEATER_ATTR] not in (None, NULL_OBJNAM):
            self._lastHeater = self._poolObject[HEATER_ATTR]

        return updated

    async def async_added_to_hass(self):
        """Entity is added to Home Assistant."""

        await super().async_added_to_hass()

        if self._lastHeater == NULL_OBJNAM:
            # our current state is OFF so
            # let's see if we find a previous value stored in out state
            last_state = await self.async_get_last_state()

            if last_state:
                value = last_state.attributes.get(self.LAST_HEATER_ATTR)
                # ignore a missing value or a heater no longer wired to the body
                if value in self._heater_list:
                    self._lastHeater = value
