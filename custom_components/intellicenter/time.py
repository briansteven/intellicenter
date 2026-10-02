"""Pentair IntelliCenter times: when a schedule starts and stops."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .pyintellicenter import (
    START_ATTR,
    STOP_ATTR,
    TIME_ATTR,
    TIMOUT_ATTR,
    ModelController,
)
from .schedule import ScheduleTime, schedules


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Load the times of a config entry."""
    controller: ModelController = entry.runtime_data.controller

    times = []
    for schedule in schedules(controller.model):
        if schedule[TIME_ATTR] is not None:
            times.append(
                ScheduleTime(
                    entry, controller, schedule, TIME_ATTR, "Start time", START_ATTR
                )
            )
        if schedule[TIMOUT_ATTR] is not None:
            times.append(
                ScheduleTime(
                    entry, controller, schedule, TIMOUT_ATTR, "Stop time", STOP_ATTR
                )
            )

    async_add_entities(times)
