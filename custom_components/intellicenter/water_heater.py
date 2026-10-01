"""Pentair Intellicenter water heaters."""

import logging
from typing import Any, Optional

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers.restore_state import RestoreEntity

from .entity import PoolEntity
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
    PoolModel,
    PoolObject,
)

_LOGGER = logging.getLogger(__name__)


def heater_serves_body(heater: PoolObject, body: PoolObject) -> bool:
    """Return True if the heater is assigned to the given body of water.

    The heater's BODY attribute lists, space separated, the bodies the heater
    is assigned to in the IntelliCenter (both the pool and the spa for a heater
    they share).
    """
    return body.objnam in (heater[BODY_ATTR] or "").split()


def heaters_for_body(model: PoolModel, body: PoolObject) -> list[str]:
    """Return the heaters a body can use, in the IntelliCenter's order.

    Those assigned to the body, and the one it has selected if that one isn't:
    some IntelliCenters heat a body with a heater that isn't assigned to it
    (others don't, see issues.HeaterAssignmentMonitor).
    """
    heaters = sorted(
        model.getByType(HEATER_TYPE),
        # heaters without an order go last
        key=lambda h: int(h[LISTORD_ATTR]) if h[LISTORD_ATTR] else 100,
    )
    result = [heater.objnam for heater in heaters if heater_serves_body(heater, body)]
    selected = model[body[HEATER_ATTR]] if body[HEATER_ATTR] else None
    if (
        selected is not None
        and selected.objtype == HEATER_TYPE
        and selected.objnam not in result
    ):
        result.append(selected.objnam)
    return result


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Load the water heaters (one per body of water that can be heated)."""

    controller: ModelController = entry.runtime_data.controller

    water_heaters = []
    body: PoolObject
    for body in controller.model.getByType(BODY_TYPE):
        heater_list = heaters_for_body(controller.model, body)
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
            name="Heater",
            extraStateAttributes=[HEATER_ATTR, HTMODE_ATTR],
        )
        # the unique ID of the body's switch, with a suffix
        self._attr_unique_id += LOTMP_ATTR
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

    def _heaters(self) -> list[str]:
        """Return the heaters to offer, with the selected one if not listed."""
        selected = self._poolObject[HEATER_ATTR]
        if selected in (None, NULL_OBJNAM) or selected in self._heater_list:
            return self._heater_list
        # selected at the IntelliCenter since Home Assistant started
        return self._heater_list + [selected]

    @property
    def current_operation(self):
        """Return current operation."""
        heater = self._poolObject[HEATER_ATTR]
        if heater in (None, NULL_OBJNAM):
            return STATE_OFF
        return self._heaterName(heater)

    @property
    def operation_list(self):
        """Return the list of available operation modes."""
        return [STATE_OFF] + [self._heaterName(heater) for heater in self._heaters()]

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set new target operation mode."""
        if operation_mode == STATE_OFF:
            self._turnOff()
        else:
            for heater in self._heaters():
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
