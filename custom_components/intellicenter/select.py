"""Pentair IntelliCenter selects: a schedule's start, stop and heater."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .pyintellicenter import (
    HEATER_ATTR,
    START_ATTR,
    STOP_ATTR,
    TIME_ATTR,
    TIMOUT_ATTR,
    ModelController,
)
from .schedule import ScheduleHeater, ScheduleTimeMode, schedules


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Load the selects of a config entry."""
    controller: ModelController = entry.runtime_data.controller

    selects = []
    for schedule in schedules(controller.model):
        if schedule[START_ATTR] is not None:
            selects.append(
                ScheduleTimeMode(
                    entry, controller, schedule, START_ATTR, "Start", TIME_ATTR
                )
            )
        if schedule[STOP_ATTR] is not None:
            selects.append(
                ScheduleTimeMode(
                    entry, controller, schedule, STOP_ATTR, "Stop", TIMOUT_ATTR
                )
            )
        if schedule[HEATER_ATTR] is not None:
            selects.append(ScheduleHeater(entry, controller, schedule))

    async_add_entities(selects)
