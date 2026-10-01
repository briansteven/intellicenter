"""Pentair Intellicenter numbers."""

from decimal import Decimal
import logging

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant

try:
    from homeassistant.const import UnitOfRatio

    PARTS_PER_MILLION = UnitOfRatio.PARTS_PER_MILLION
except ImportError:  # older Home Assistant releases without UnitOfRatio
    from homeassistant.const import (
        CONCENTRATION_PARTS_PER_MILLION as PARTS_PER_MILLION,
    )

from .entity import PoolEntity
from .pyintellicenter import (
    ALK_ATTR,
    BODY_ATTR,
    CALC_ATTR,
    CHEM_TYPE,
    CYACID_ATTR,
    ORPSET_ATTR,
    PHSET_ATTR,
    PRIM_ATTR,
    SEC_ATTR,
    TIMOUT_ATTR,
    ModelController,
    PoolObject,
)

_LOGGER = logging.getLogger(__name__)

# IntelliChem settings: attribute, name, min, max, step, unit, device class.
# Setpoint ranges are the IntelliChem's (its manual: pH 7.2-7.8 by 0.1, ORP
# 400-800 mV by 10), widened a little for pH; the water test values are entered
# for the saturation index. The IntelliCenter refuses a value out of its range.
INTELLICHEM_SETTINGS = [
    (PHSET_ATTR, "pH target", 7.0, 7.8, 0.1, None, NumberDeviceClass.PH),
    (ORPSET_ATTR, "ORP target", 400, 800, 10, UnitOfElectricPotential.MILLIVOLT, None),
    (ALK_ATTR, "Total alkalinity", 0, 300, 1, PARTS_PER_MILLION, None),
    (CALC_ATTR, "Calcium hardness", 0, 800, 1, PARTS_PER_MILLION, None),
    (CYACID_ATTR, "Cyanuric acid", 0, 200, 1, PARTS_PER_MILLION, None),
]

# -------------------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Load pool numbers based on a config entry."""

    controller: ModelController = entry.runtime_data.controller

    numbers = []

    obj: PoolObject
    for obj in controller.model.objectList:
        if obj.objtype != CHEM_TYPE:
            continue
        if obj.subtype == "ICHLOR":
            if PRIM_ATTR in obj.attributes:
                intellichlor_bodies = (obj[BODY_ATTR] or "").split()

                # one output setting per body the IntelliChlor serves (PRIM for
                # the first, SEC for the second)
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
                                icon="mdi:gauge",
                            )
                        )
            if TIMOUT_ATTR in obj.attributes:
                # how long superchlorinate runs; the IntelliCenter keeps seconds
                numbers.append(
                    PoolNumber(
                        entry,
                        controller,
                        obj,
                        attribute_key=TIMOUT_ATTR,
                        name="Superchlorinate duration",
                        unit_of_measurement=UnitOfTime.HOURS,
                        device_class=NumberDeviceClass.DURATION,
                        min_value=1,
                        max_value=96,
                        scale=3600,
                        mode=NumberMode.BOX,
                    )
                )
        elif obj.subtype == "ICHEM":
            for attr, name, low, high, step, unit, device_class in INTELLICHEM_SETTINGS:
                if attr in obj.attributes:
                    numbers.append(
                        PoolNumber(
                            entry,
                            controller,
                            obj,
                            attribute_key=attr,
                            name=name,
                            unit_of_measurement=unit,
                            device_class=device_class,
                            min_value=low,
                            max_value=high,
                            step=step,
                            mode=NumberMode.BOX,
                        )
                    )

    async_add_entities(numbers)


# -------------------------------------------------------------------------------------


class PoolNumber(PoolEntity, NumberEntity):
    """A setting of an IntelliCenter object.

    scale: the IntelliCenter's value is the shown value times scale (3600 for
    hours kept in seconds).
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        entry: ConfigEntry,
        controller: ModelController,
        poolObject: PoolObject,
        min_value: float = 0,
        max_value: float = 100,
        step: float = 1,
        scale: int = 1,
        device_class: NumberDeviceClass | None = None,
        mode: NumberMode = NumberMode.AUTO,
        **kwargs,
    ):
        """Initialize."""
        super().__init__(entry, controller, poolObject, **kwargs)
        self._attr_native_min_value = min_value
        self._attr_native_max_value = max_value
        self._attr_native_step = step
        self._attr_device_class = device_class
        self._attr_mode = mode
        self._scale = scale
        # the decimals the IntelliCenter expects (0 for whole steps)
        self._decimals = max(0, -Decimal(str(step)).normalize().as_tuple().exponent)

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        value = self._poolObject[self._attribute_key]
        if value is None or value == "":
            return None
        try:
            number = float(value) / self._scale
        except (TypeError, ValueError):
            return None
        # keep whole numbers whole ("25", not "25.0"), as the system reports them
        return int(number) if number.is_integer() else number

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        raw = value * self._scale
        text = f"{raw:.{self._decimals}f}" if self._decimals else str(int(round(raw)))
        await self.async_request_changes({self._attribute_key: text})
