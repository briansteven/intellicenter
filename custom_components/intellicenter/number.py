"""Pentair Intellicenter numbers."""

import logging

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant

from .entity import PoolEntity
from .pyintellicenter import (
    BODY_ATTR,
    CHEM_TYPE,
    PRIM_ATTR,
    SEC_ATTR,
    ModelController,
    PoolObject,
)

_LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Load pool numbers based on a config entry."""

    controller: ModelController = entry.runtime_data.controller

    numbers = []

    obj: PoolObject
    for obj in controller.model.objectList:
        if (
            obj.objtype == CHEM_TYPE
            and obj.subtype == "ICHLOR"
            and PRIM_ATTR in obj.attributes
        ):
            intellichlor_bodies = (obj[BODY_ATTR] or "").split()

            # one output setting per body the IntelliChlor serves (PRIM for the
            # first, SEC for the second)
            for index, body_id in enumerate(intellichlor_bodies[:2]):
                body = controller.model[body_id]
                if body is not None:
                    attribute_key = PRIM_ATTR if index == 0 else SEC_ATTR
                    numbers.append(
                        PoolNumber(
                            entry,
                            controller,
                            obj,
                            unit_of_measurement=PERCENTAGE,
                            attribute_key=attribute_key,
                            name=f"{body.sname or body.objnam} output",
                        )
                    )

    async_add_entities(numbers)


# -------------------------------------------------------------------------------------


class PoolNumber(PoolEntity, NumberEntity):
    """Representation of a pool number entity."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1

    def __init__(
        self,
        entry: ConfigEntry,
        controller: ModelController,
        poolObject: PoolObject,
        **kwargs,
    ):
        """Initialize."""
        super().__init__(entry, controller, poolObject, **kwargs)
        self._attr_icon = "mdi:gauge"

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        value = self._poolObject[self._attribute_key]
        if value is None or value == "":
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        # keep whole numbers whole ("25", not "25.0"), as the system reports them
        return int(number) if number.is_integer() else number

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        changes = {self._attribute_key: str(int(value))}
        self.requestChanges(changes)
