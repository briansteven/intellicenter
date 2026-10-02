"""Pentair Intellicenter sensors."""

import logging
from typing import Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    REVOLUTIONS_PER_MINUTE,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import dispatcher
from homeassistant.util import dt as dt_util

try:
    from homeassistant.const import UnitOfRatio

    PARTS_PER_MILLION = UnitOfRatio.PARTS_PER_MILLION
except ImportError:  # older Home Assistant releases without UnitOfRatio
    from homeassistant.const import (
        CONCENTRATION_PARTS_PER_MILLION as PARTS_PER_MILLION,
    )

from .const import alerts_signal
from .entity import PoolEntity
from .pyintellicenter import (
    BODY_TYPE,
    CHEM_TYPE,
    GPM_ATTR,
    LOTMP_ATTR,
    LSTTMP_ATTR,
    ORPTNK_ATTR,
    ORPVAL_ATTR,
    PARENT_ATTR,
    PHTNK_ATTR,
    PHVAL_ATTR,
    PUMP_TYPE,
    PWR_ATTR,
    QUALTY_ATTR,
    RPM_ATTR,
    SALT_ATTR,
    SENSE_TYPE,
    SNAME_ATTR,
    SOURCE_ATTR,
    SYSTEM_TYPE,
    TIME_ATTR,
    ModelController,
    PoolObject,
)

_LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Load pool sensors based on a config entry."""

    controller: ModelController = entry.runtime_data.controller

    sensors = []

    def add(obj, cls=None, **kwargs):
        sensors.append((cls or PoolSensor)(entry, controller, obj, **kwargs))

    obj: PoolObject
    for obj in controller.model.objectList:
        if obj.objtype == SENSE_TYPE:
            add(obj, device_class=SensorDeviceClass.TEMPERATURE, attribute_key=SOURCE_ATTR)
        elif obj.objtype == PUMP_TYPE:
            if obj[PWR_ATTR]:
                add(
                    obj,
                    device_class=SensorDeviceClass.POWER,
                    unit_of_measurement=UnitOfPower.WATT,
                    attribute_key=PWR_ATTR,
                    name="Power",
                    rounding_factor=25,
                )
            if obj[RPM_ATTR]:
                add(
                    obj,
                    unit_of_measurement=REVOLUTIONS_PER_MINUTE,
                    attribute_key=RPM_ATTR,
                    name="Speed",
                    icon="mdi:speedometer",
                )
            if obj[GPM_ATTR]:
                add(
                    obj,
                    device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
                    unit_of_measurement=UnitOfVolumeFlowRate.GALLONS_PER_MINUTE,
                    attribute_key=GPM_ATTR,
                    name="Flow",
                )
        elif obj.objtype == BODY_TYPE:
            add(
                obj,
                device_class=SensorDeviceClass.TEMPERATURE,
                attribute_key=LSTTMP_ATTR,
                name="Temperature",
            )
            add(
                obj,
                device_class=SensorDeviceClass.TEMPERATURE,
                attribute_key=LOTMP_ATTR,
                name="Target temperature",
            )
        elif obj.objtype == CHEM_TYPE:
            if obj.subtype == "ICHEM":
                if PHVAL_ATTR in obj.attributes:
                    add(
                        obj,
                        unit_of_measurement="pH",
                        attribute_key=PHVAL_ATTR,
                        name="pH",
                        icon="mdi:ph",
                    )
                if ORPVAL_ATTR in obj.attributes:
                    add(
                        obj,
                        unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
                        attribute_key=ORPVAL_ATTR,
                        name="ORP",
                    )
                if QUALTY_ATTR in obj.attributes:
                    # the Langelier saturation index the IntelliChem computes
                    # (balanced between -0.5 and +0.5)
                    add(
                        obj,
                        attribute_key=QUALTY_ATTR,
                        name="Saturation index",
                        icon="mdi:scale-balance",
                    )
                if PHTNK_ATTR in obj.attributes:
                    add(
                        obj,
                        TankLevelSensor,
                        attribute_key=PHTNK_ATTR,
                        name="pH tank level",
                    )
                if ORPTNK_ATTR in obj.attributes:
                    add(
                        obj,
                        TankLevelSensor,
                        attribute_key=ORPTNK_ATTR,
                        name="ORP tank level",
                    )
            elif obj.subtype == "ICHLOR":
                if SALT_ATTR in obj.attributes:
                    add(
                        obj,
                        unit_of_measurement=PARTS_PER_MILLION,
                        attribute_key=SALT_ATTR,
                        name="Salt",
                        icon="mdi:shaker-outline",
                    )
        elif obj.objtype == SYSTEM_TYPE and controller.supportsAlerts:
            sensors.append(AlertsSensor(entry, controller, obj))
    async_add_entities(sensors)


# -------------------------------------------------------------------------------------


class PoolSensor(PoolEntity, SensorEntity):
    """Representation of an Pentair sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        entry: ConfigEntry,
        controller: ModelController,
        poolObject: PoolObject,
        device_class: Optional[SensorDeviceClass] = None,
        rounding_factor: int = 0,
        **kwargs,
    ):
        """Initialize."""
        super().__init__(entry, controller, poolObject, **kwargs)
        self._attr_device_class = device_class
        self._rounding_factor = rounding_factor

    def _number(self):
        """Return the attribute's value as a number, None if it has none."""
        value = self._poolObject[self._attribute_key]
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @property
    def native_value(self):
        """Return the value of the sensor."""

        numeric = self._number()
        if numeric is None:
            return None

        # some sensors, like variable speed pumps, can vary constantly
        # so rounding their value to a nearest multiplier of 'rounding'
        # smoothes the curve and limits the number of updates in the log

        if self._rounding_factor:
            return int(round(numeric / self._rounding_factor) * self._rounding_factor)

        return int(numeric) if numeric.is_integer() else numeric

    @property
    def native_unit_of_measurement(self) -> Optional[str]:
        """Return the unit of measurement of this entity, if any."""
        if self._attr_device_class == SensorDeviceClass.TEMPERATURE:
            return self.pentairTemperatureSettings()
        return self._attr_native_unit_of_measurement


class TankLevelSensor(PoolSensor):
    """The level of an IntelliChem tank, 0 (empty) to 6 (full).

    The IntelliCenter reports levels 1 to 7 for what the IntelliChem shows as
    0 to 6 (found by the joyfulhouse and nodejs-poolController projects).
    """

    def __init__(self, *args, **kwargs):
        """Initialize."""
        super().__init__(*args, icon="mdi:storage-tank-outline", **kwargs)

    @property
    def native_value(self):
        """Return the level."""
        numeric = self._number()
        if numeric is None:
            return None
        return max(int(numeric) - 1, 0)


# the alerts sensor's unique ID ends with this (after the system object's name)
ALERTS_KEY = "ALERTS"


class AlertsSensor(PoolEntity, SensorEntity):
    """The number of alerts the IntelliCenter has raised and not cleared.

    The alerts ("IntelliChlor 1: Communication Lost"...) are in the "alerts"
    attribute, oldest first: their message, the equipment they are about and
    when they were raised. Only firmware that pushes them as they are raised and
    cleared (IC 3.x) gets this sensor.
    """

    def __init__(
        self, entry: ConfigEntry, controller: ModelController, poolObject: PoolObject
    ):
        """Initialize."""
        super().__init__(
            entry, controller, poolObject, attribute_key=ALERTS_KEY, name="Alerts"
        )

    async def async_added_to_hass(self):
        """Entity is added to Home Assistant."""
        await super().async_added_to_hass()
        self.async_on_remove(
            dispatcher.async_dispatcher_connect(
                self.hass, alerts_signal(self._entry_id), self._alerts_callback
            )
        )

    @callback
    def _alerts_callback(self, alerts: dict[str, dict[str, str]]) -> None:
        self.async_write_ha_state()

    def isUpdated(self, updates: dict[str, dict[str, str]]) -> bool:
        """Return False: changes to the objects don't change the alerts."""
        return False

    @property
    def native_value(self) -> int:
        """Return the number of active alerts."""
        return len(self._controller.alerts)

    @property
    def icon(self) -> str:
        """Return the icon."""
        return (
            "mdi:alert-circle" if self._controller.alerts else "mdi:check-circle-outline"
        )

    @property
    def extra_state_attributes(self) -> dict:
        """Return the alerts, oldest first."""
        model = self._controller.model
        alerts = []
        for objnam, params in self._controller.alerts.items():
            alert = {"message": params.get(SNAME_ATTR) or objnam}
            parent = model[params.get(PARENT_ATTR)]
            if parent is not None:
                alert["equipment"] = parent.sname or parent.objnam
            since = _raised(params)
            if since is not None:
                alert["since"] = since.isoformat()
            alert["id"] = objnam
            alerts.append(alert)
        alerts.sort(key=lambda alert: (alert.get("since", ""), alert["id"]))
        return {"alerts": alerts}


def _raised(params: dict[str, str]):
    """Return when an alert was raised (TIME, in seconds since 1970), if known."""
    try:
        seconds = int(params.get(TIME_ATTR))
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    try:
        return dt_util.utc_from_timestamp(seconds)
    except (OverflowError, OSError, ValueError):
        return None
