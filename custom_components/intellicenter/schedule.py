"""The IntelliCenter's schedules: a device each, with their settings.

A schedule turns a circuit on during a time window on given days, optionally
setting how its body of water is heated. In the IntelliCenter (seen on IC 1.064
and IC 3.014) a SCHED object has:

- STATUS: ON when the schedule is enabled; ACT: ON while it's running
- START / STOP: how the window starts and ends: ABSTIM (at a time), SRIS
  (sunrise) or SSET (sunset); TIME / TIMOUT: those times ("HH,MM,SS"), today's
  sunrise or sunset when the window follows the sun
- DAY: the days it runs, one letter each: M T W R F A U (Monday to Sunday)
- HEATER: the heater to heat with, 00000 (off) or HOLD (don't change, written
  as 00001: IC 3.014 refuses HOLD); LOTMP: the temperature to heat to
- VACFLO: ON if it only runs in vacation mode; SINGLE: ON if it runs once
- CIRCUIT: the circuit it turns on

Schedules can't be created or deleted here (only in the IntelliCenter or the
Pentair app).
"""

from __future__ import annotations

import asyncio
from datetime import time
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .entity import PoolEntity, object_device_name
from .pyintellicenter import (
    ACT_ATTR,
    CIRCUIT_ATTR,
    DAY_ATTR,
    HEATER_ATTR,
    HEATER_TYPE,
    LOTMP_ATTR,
    NULL_OBJNAM,
    SCHED_TYPE,
    SINGLE_ATTR,
    START_ATTR,
    STATUS_ATTR,
    STOP_ATTR,
    TIME_ATTR,
    TIMOUT_ATTR,
    VACFLO_ATTR,
    ModelController,
    PoolModel,
    PoolObject,
)

# the days of DAY, in the IntelliCenter's order
DAYS = [
    ("M", "Monday"),
    ("T", "Tuesday"),
    ("W", "Wednesday"),
    ("R", "Thursday"),
    ("F", "Friday"),
    ("A", "Saturday"),
    ("U", "Sunday"),
]

# how a schedule's window starts or ends
AT_TIME = "ABSTIM"
TIME_MODES = {AT_TIME: "Time", "SRIS": "Sunrise", "SSET": "Sunset"}
# also seen in documentation for a time (never on a panel)
TIME_MODE_ALIASES = {"ABSTIME": AT_TIME}

# a schedule's heater, besides a HEATER objnam
HEATER_OFF = NULL_OBJNAM
HEATER_HOLD = "HOLD"  # how it reads
HEATER_HOLD_WRITTEN = "00001"  # how it's written
HEATER_OFF_NAME = "Off"
HEATER_HOLD_NAME = "Don't change"


def parse_time(value: str | None) -> time | None:
    """Return the time of a TIME or TIMOUT value ("HH,MM,SS")."""
    if not value:
        return None
    try:
        parts = [int(part) for part in value.split(",")]
        while len(parts) < 3:
            parts.append(0)
        return time(*parts[:3])
    except (TypeError, ValueError):
        return None


def format_time(value: time) -> str:
    """Return a time as the IntelliCenter writes it ("HH,MM,SS")."""
    return f"{value.hour:02d},{value.minute:02d},{value.second:02d}"


def time_mode(value: str | None) -> str | None:
    """Return START or STOP as one of TIME_MODES, None if unknown."""
    value = TIME_MODE_ALIASES.get(value, value)
    return value if value in TIME_MODES else None


def heater_name(model: PoolModel, value: str | None) -> str | None:
    """Return what a schedule's HEATER means."""
    if value is None:
        return None
    if value == HEATER_OFF:
        return HEATER_OFF_NAME
    if value in (HEATER_HOLD, HEATER_HOLD_WRITTEN):
        return HEATER_HOLD_NAME
    heater = model[value]
    return (heater.sname or heater.objnam) if heater is not None else value


def schedule_summary(model: PoolModel, schedule: PoolObject) -> dict[str, Any]:
    """Return what a schedule does, as state attributes."""

    def window_end(mode_attr: str, time_attr: str) -> str | None:
        mode = time_mode(schedule[mode_attr])
        at = parse_time(schedule[time_attr])
        text = at.strftime("%H:%M") if at else None
        if mode is None or mode == AT_TIME:
            return text
        # sunrise or sunset, with today's time
        return f"{TIME_MODES[mode].lower()} ({text})" if text else TIME_MODES[mode].lower()

    circuit = model[schedule[CIRCUIT_ATTR]] if schedule[CIRCUIT_ATTR] else None
    days = schedule[DAY_ATTR] or ""
    summary = {
        "circuit": (circuit.sname or circuit.objnam) if circuit else schedule[CIRCUIT_ATTR],
        "days": [name for letter, name in DAYS if letter in days],
        "start": window_end(START_ATTR, TIME_ATTR),
        "stop": window_end(STOP_ATTR, TIMOUT_ATTR),
        "heater": heater_name(model, schedule[HEATER_ATTR]),
        "heat_to": _number(schedule[LOTMP_ATTR]),
        "vacation_only": schedule[VACFLO_ATTR] == "ON",
        "run_once": schedule[SINGLE_ATTR] == "ON",
        "running": schedule[ACT_ATTR] == "ON",
    }
    return {key: value for key, value in summary.items() if value is not None}


def _number(value: str | None) -> int | float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def schedules(model: PoolModel) -> list[PoolObject]:
    """Return the schedules of the IntelliCenter."""
    return model.getByType(SCHED_TYPE)


# -------------------------------------------------------------------------------------


class ScheduleEntity(PoolEntity):
    """An entity of a schedule (on the schedule's device)."""

    def _update_keys(self) -> set[str]:
        """Return the attributes that change what the entity shows."""
        return {self._attribute_key}

    def isUpdated(self, updates: dict[str, dict[str, str]]) -> bool:
        """Return true if what the entity shows changed."""
        return bool(
            self._update_keys() & updates.get(self._poolObject.objnam, {}).keys()
        )


class ScheduleSwitch(ScheduleEntity, SwitchEntity):
    """A schedule: on while it's enabled.

    Its attributes tell what it does: circuit, days, start, stop, heater...
    """

    def __init__(self, entry: ConfigEntry, controller: ModelController, schedule):
        """Initialize."""
        super().__init__(
            entry,
            controller,
            schedule,
            attribute_key=STATUS_ATTR,
            name=None,
            icon="mdi:calendar-clock",
        )

    def _update_keys(self) -> set[str]:
        # everything shown in the attributes
        return {
            STATUS_ATTR,
            ACT_ATTR,
            CIRCUIT_ATTR,
            DAY_ATTR,
            START_ATTR,
            STOP_ATTR,
            TIME_ATTR,
            TIMOUT_ATTR,
            HEATER_ATTR,
            LOTMP_ATTR,
            VACFLO_ATTR,
            SINGLE_ATTR,
        }

    @property
    def is_on(self) -> bool | None:
        """Return true if the schedule is enabled."""
        value = self._poolObject[STATUS_ATTR]
        return None if value is None else value == "ON"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return what the schedule does."""
        return schedule_summary(self._controller.model, self._poolObject)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the schedule."""
        await self.async_request_changes({STATUS_ATTR: "ON"})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the schedule."""
        await self.async_request_changes({STATUS_ATTR: "OFF"})


class ScheduleRunning(ScheduleEntity, BinarySensorEntity):
    """On while the schedule runs (disabled by default)."""

    def __init__(self, entry: ConfigEntry, controller: ModelController, schedule):
        """Initialize."""
        super().__init__(
            entry,
            controller,
            schedule,
            attribute_key=ACT_ATTR,
            name="Running",
            icon="mdi:calendar-check",
            enabled_by_default=False,
        )

    @property
    def is_on(self) -> bool | None:
        """Return true while the schedule runs."""
        value = self._poolObject[ACT_ATTR]
        return None if value is None else value == "ON"


class ScheduleOption(ScheduleEntity, SwitchEntity):
    """An ON/OFF setting of a schedule: vacation only, run once."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry, controller, schedule, attribute_key, name, icon):
        """Initialize."""
        super().__init__(
            entry,
            controller,
            schedule,
            attribute_key=attribute_key,
            name=name,
            icon=icon,
            enabled_by_default=False,
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if the setting is on."""
        value = self._poolObject[self._attribute_key]
        return None if value is None else value == "ON"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        await self.async_request_changes({self._attribute_key: "ON"})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        await self.async_request_changes({self._attribute_key: "OFF"})


class ScheduleDays:
    """The days of one schedule, shared by its day switches.

    Each switch changes one letter of DAY, and DAY is written whole: changes are
    made one at a time, each from the days the previous one wrote (the
    IntelliCenter reports them a little later), so that two changes close
    together (one action on several days) don't undo each other.
    """

    def __init__(self) -> None:
        """Initialize."""
        self.lock = asyncio.Lock()
        # the days last written, until the IntelliCenter reports them
        self.pending: str | None = None

    def reported(self, days: str | None) -> None:
        """Forget what was written once the IntelliCenter reports it.

        (Or reports anything while nothing is being written: what it reports
        then is the latest.)
        """
        if days == self.pending or not self.lock.locked():
            self.pending = None


class ScheduleDay(ScheduleEntity, SwitchEntity):
    """Whether a schedule runs on a day of the week (disabled by default)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, entry, controller, schedule, letter: str, day: str, days: ScheduleDays
    ):
        """Initialize."""
        super().__init__(
            entry,
            controller,
            schedule,
            attribute_key=DAY_ATTR,
            name=day,
            icon="mdi:calendar-week",
            enabled_by_default=False,
        )
        self._letter = letter
        self._days = days
        self._attr_unique_id += letter

    @property
    def is_on(self) -> bool | None:
        """Return true if the schedule runs that day."""
        days = self._poolObject[DAY_ATTR]
        return None if days is None else self._letter in days

    def isUpdated(self, updates: dict[str, dict[str, str]]) -> bool:
        """Return true if the days changed."""
        updated = super().isUpdated(updates)
        if updated:
            self._days.reported(self._poolObject[DAY_ATTR])
        return updated

    async def _async_set_day(self, on: bool) -> None:
        async with self._days.lock:
            if self._days.pending is not None:
                days = self._days.pending
            else:
                days = self._poolObject[DAY_ATTR] or ""
            new = "".join(
                letter
                for letter, _ in DAYS
                if (letter == self._letter and on)
                or (letter != self._letter and letter in days)
            )
            if new == days:
                return
            if not new:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="schedule_without_days",
                    translation_placeholders={
                        "name": object_device_name(
                            self._poolObject, self._controller.model
                        )
                    },
                )
            previous, self._days.pending = self._days.pending, new
            try:
                await self.async_request_changes({DAY_ATTR: new})
            except BaseException:
                # not written: an earlier write may still be unreported
                self._days.pending = previous
                raise

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Run the schedule that day."""
        await self._async_set_day(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Don't run the schedule that day."""
        await self._async_set_day(False)


class ScheduleTimeMode(ScheduleEntity, SelectEntity):
    """How a schedule's window starts or stops: at a time, sunrise or sunset."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(TIME_MODES.values())

    def __init__(self, entry, controller, schedule, attribute_key, name, time_attr):
        """Initialize."""
        super().__init__(
            entry,
            controller,
            schedule,
            attribute_key=attribute_key,
            name=name,
            icon="mdi:weather-sunset",
            enabled_by_default=False,
        )
        self._time_attr = time_attr

    @property
    def current_option(self) -> str | None:
        """Return how the window starts or stops."""
        mode = time_mode(self._poolObject[self._attribute_key])
        return TIME_MODES[mode] if mode else None

    async def async_select_option(self, option: str) -> None:
        """Change how the window starts or stops.

        At a time, it is the time it has now (today's sunrise or sunset).
        """
        for mode, name in TIME_MODES.items():
            if name == option:
                await self.async_request_changes({self._attribute_key: mode})
                return
        raise ValueError(option)


class ScheduleTime(ScheduleEntity, TimeEntity):
    """When a schedule's window starts or stops.

    Following the sun, it's today's sunrise or sunset; setting a time makes
    the window start (or stop) at that time.
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry, controller, schedule, attribute_key, name, mode_attr):
        """Initialize."""
        super().__init__(
            entry,
            controller,
            schedule,
            attribute_key=attribute_key,
            name=name,
            icon="mdi:clock-outline",
            enabled_by_default=False,
        )
        self._mode_attr = mode_attr

    @property
    def native_value(self) -> time | None:
        """Return the time."""
        return parse_time(self._poolObject[self._attribute_key])

    async def async_set_value(self, value: time) -> None:
        """Start (or stop) the window at this time."""
        await self.async_request_changes(
            {self._mode_attr: AT_TIME, self._attribute_key: format_time(value)}
        )


class ScheduleHeater(ScheduleEntity, SelectEntity):
    """The heating a schedule sets: off, don't change, or a heater."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry, controller, schedule):
        """Initialize."""
        super().__init__(
            entry,
            controller,
            schedule,
            attribute_key=HEATER_ATTR,
            name="Heater",
            icon="mdi:fire",
            enabled_by_default=False,
        )

    def _choices(self) -> dict[str, str]:
        """Return the options: name -> value to write."""
        choices = {HEATER_OFF_NAME: HEATER_OFF, HEATER_HOLD_NAME: HEATER_HOLD_WRITTEN}
        for heater in self._controller.model.getByType(HEATER_TYPE):
            choices.setdefault(heater.sname or heater.objnam, heater.objnam)
        current = self._poolObject[HEATER_ATTR]
        name = heater_name(self._controller.model, current)
        if name is not None and name not in choices:
            # a value of its own (another kind of heat source): kept as is
            choices[name] = current
        return choices

    @property
    def options(self) -> list[str]:
        """Return the options."""
        return list(self._choices())

    @property
    def current_option(self) -> str | None:
        """Return the heating set by the schedule."""
        return heater_name(self._controller.model, self._poolObject[HEATER_ATTR])

    async def async_select_option(self, option: str) -> None:
        """Change the heating set by the schedule."""
        choices = self._choices()
        if option not in choices:
            raise ValueError(option)
        await self.async_request_changes({HEATER_ATTR: choices[option]})


class ScheduleHeatTo(ScheduleEntity, NumberEntity):
    """The temperature a schedule heats to (with a heater)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1

    def __init__(self, entry, controller, schedule):
        """Initialize."""
        super().__init__(
            entry,
            controller,
            schedule,
            attribute_key=LOTMP_ATTR,
            name="Heat to",
            icon="mdi:thermometer",
            enabled_by_default=False,
        )

    # the limits of the water heaters, in the IntelliCenter's unit (MODE)

    @property
    def native_min_value(self) -> float:
        """Return the lowest temperature."""
        return 5 if self._controller.systemInfo.usesMetric else 40

    @property
    def native_max_value(self) -> float:
        """Return the highest temperature."""
        return 40 if self._controller.systemInfo.usesMetric else 104

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the IntelliCenter's temperature unit."""
        return self.pentairTemperatureSettings()

    @property
    def native_value(self) -> float | None:
        """Return the temperature."""
        return _number(self._poolObject[LOTMP_ATTR])

    async def async_set_native_value(self, value: float) -> None:
        """Change the temperature."""
        await self.async_request_changes({LOTMP_ATTR: str(int(round(value)))})
