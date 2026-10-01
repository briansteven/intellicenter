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
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfTime,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant

try:
    from homeassistant.const import UnitOfRatio

    PARTS_PER_MILLION = UnitOfRatio.PARTS_PER_MILLION
except ImportError:  # older Home Assistant releases without UnitOfRatio
    from homeassistant.const import (
        CONCENTRATION_PARTS_PER_MILLION as PARTS_PER_MILLION,
    )

from .entity import PoolEntity, egg_timer_circuits
from .pyintellicenter import (
    ALK_ATTR,
    BODY_ATTR,
    CALC_ATTR,
    CHEM_TYPE,
    CIRCUIT_ATTR,
    CYACID_ATTR,
    MAX_ATTR,
    MAXF_ATTR,
    MIN_ATTR,
    MINF_ATTR,
    ORPSET_ATTR,
    PARENT_ATTR,
    PHSET_ATTR,
    PMPCIRC_TYPE,
    PRIM_ATTR,
    PUMP_TYPE,
    SEC_ATTR,
    SELECT_ATTR,
    SPEED_ATTR,
    TIME_ATTR,
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

# a circuit's egg timer, in minutes: up to 23 hours 59 minutes, as the
# IntelliCenter offers it (beyond that is its "Don't Stop")
EGG_TIMER_MAX = 23 * 60 + 59

# -------------------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Load pool numbers based on a config entry."""

    controller: ModelController = entry.runtime_data.controller

    numbers = []

    obj: PoolObject
    for obj in controller.model.objectList:
        if obj.objtype == PMPCIRC_TYPE:
            pump = controller.model[obj[PARENT_ATTR]] if obj[PARENT_ATTR] else None
            circuit = controller.model[obj[CIRCUIT_ATTR]] if obj[CIRCUIT_ATTR] else None
            if (
                pump is not None
                and pump.objtype == PUMP_TYPE
                and circuit is not None
                and obj[SPEED_ATTR] is not None
            ):
                numbers.append(PumpSpeed(entry, controller, obj, pump, circuit))
            continue
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

    for circuit, body in egg_timer_circuits(controller.model):
        numbers.append(EggTimer(entry, controller, circuit, body))

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


# -------------------------------------------------------------------------------------


class PumpSpeed(PoolNumber):
    """The speed (or flow) a pump runs at for one of its circuits.

    The IntelliCenter keeps one setting per circuit a pump serves (its PMPCIRC
    objects): the pump runs at the highest setting of the circuits that are on.
    Disabled by default: changing pump speeds is for those who choose to.
    """

    _attr_entity_registry_enabled_default = False

    def __init__(self, entry, controller, poolObject, pump, circuit):
        """Initialize."""
        super().__init__(
            entry,
            controller,
            poolObject,
            attribute_key=SPEED_ATTR,
            name=f"{circuit.sname or circuit.objnam} speed",
            icon="mdi:speedometer",
            mode=NumberMode.BOX,
            deviceObject=pump,
            enabled_by_default=False,
        )
        self._pump = pump

    @property
    def _usesFlow(self) -> bool:
        return self._poolObject[SELECT_ATTR] == "GPM"

    def _limit(self, attribute, default):
        try:
            return float(self._pump[attribute])
        except (TypeError, ValueError):
            return default

    @property
    def native_unit_of_measurement(self) -> str:
        """Return RPM or GPM, as the setting is."""
        return (
            UnitOfVolumeFlowRate.GALLONS_PER_MINUTE
            if self._usesFlow
            else REVOLUTIONS_PER_MINUTE
        )

    @property
    def native_min_value(self) -> float:
        """Return the pump's minimum."""
        return self._limit(MINF_ATTR, 15) if self._usesFlow else self._limit(MIN_ATTR, 450)

    @property
    def native_max_value(self) -> float:
        """Return the pump's maximum."""
        return (
            self._limit(MAXF_ATTR, 140) if self._usesFlow else self._limit(MAX_ATTR, 3450)
        )

    @property
    def native_step(self) -> float:
        """Return the step (1 GPM or 10 RPM)."""
        return 1 if self._usesFlow else 10

    def isUpdated(self, updates: dict[str, dict[str, str]]) -> bool:
        """Return true if the setting (or its unit) changed."""
        return bool(
            {SPEED_ATTR, SELECT_ATTR} & updates.get(self._poolObject.objnam, {}).keys()
        )


# -------------------------------------------------------------------------------------


class EggTimer(PoolNumber):
    """How long a circuit runs once turned on by hand (its egg timer).

    A body's circuit has its egg timer on the body's device; other circuits on
    the IntelliCenter's. Disabled by default.
    """

    def __init__(self, entry, controller, circuit, body):
        """Initialize."""
        super().__init__(
            entry,
            controller,
            circuit,
            attribute_key=TIME_ATTR,
            name="Egg timer"
            if body is not None
            else f"{circuit.sname or circuit.objnam} egg timer",
            icon="mdi:timer-outline",
            unit_of_measurement=UnitOfTime.MINUTES,
            device_class=NumberDeviceClass.DURATION,
            min_value=1,
            max_value=EGG_TIMER_MAX,
            mode=NumberMode.BOX,
            deviceObject=body,
            enabled_by_default=False,
        )
