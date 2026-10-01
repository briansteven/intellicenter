"""Pentair IntelliCenter Integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    dispatcher,
    entity_registry as er,
)
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, SETUP_TIMEOUT, connection_signal, update_signal
from .entity import get_device, system_device_info, system_id
from .equipment import EquipmentWatcher
from .issues import HeaterAssignmentMonitor
from .pyintellicenter import (
    ACT_ATTR,
    BODY_ATTR,
    BODY_TYPE,
    CHEM_TYPE,
    CIRCGRP_TYPE,
    CIRCUIT_ATTR,
    CIRCUIT_TYPE,
    DNTSTP_ATTR,
    EXTINSTR_TYPE,
    FEATR_ATTR,
    FILTER_ATTR,
    GPM_ATTR,
    HEATER_ATTR,
    HEATER_TYPE,
    HTMODE_ATTR,
    LISTORD_ATTR,
    LOTMP_ATTR,
    LSTTMP_ATTR,
    MAX_ATTR,
    MAXF_ATTR,
    MIN_ATTR,
    MINF_ATTR,
    MODE_ATTR,
    NORMAL_ATTR,
    PMPCIRC_TYPE,
    POSIT_ATTR,
    PUMP_TYPE,
    PWR_ATTR,
    RPM_ATTR,
    SCHED_TYPE,
    SELECT_ATTR,
    SENSE_TYPE,
    SERVICE_ATTR,
    SNAME_ATTR,
    SOURCE_ATTR,
    SPEED_ATTR,
    STATUS_ATTR,
    SUBTYP_ATTR,
    SYSTEM_TYPE,
    TIME_ATTR,
    USE_ATTR,
    VACFLO_ATTR,
    VOL_ATTR,
    ConnectionHandler,
    ModelController,
    PoolModel,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.COVER,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.WATER_HEATER,
]

# the objects loaded from the IntelliCenter and the attributes followed for
# each (an empty set: every attribute known for that type)
ATTRIBUTES_MAP = {
    BODY_TYPE: {
        SNAME_ATTR,
        CIRCUIT_ATTR,
        FILTER_ATTR,
        HEATER_ATTR,
        HTMODE_ATTR,
        LOTMP_ATTR,
        LSTTMP_ATTR,
        STATUS_ATTR,
        VOL_ATTR,
    },
    CIRCUIT_TYPE: {
        SNAME_ATTR,
        STATUS_ATTR,
        USE_ATTR,
        SUBTYP_ATTR,
        FEATR_ATTR,
        TIME_ATTR,
        DNTSTP_ATTR,
    },
    CIRCGRP_TYPE: {CIRCUIT_ATTR},
    CHEM_TYPE: set(),
    EXTINSTR_TYPE: {SNAME_ATTR, STATUS_ATTR, NORMAL_ATTR, POSIT_ATTR, BODY_ATTR},
    HEATER_TYPE: {SNAME_ATTR, BODY_ATTR, LISTORD_ATTR},
    PMPCIRC_TYPE: {CIRCUIT_ATTR, SPEED_ATTR, SELECT_ATTR},
    PUMP_TYPE: {
        SNAME_ATTR,
        STATUS_ATTR,
        PWR_ATTR,
        RPM_ATTR,
        GPM_ATTR,
        MIN_ATTR,
        MAX_ATTR,
        MINF_ATTR,
        MAXF_ATTR,
    },
    SENSE_TYPE: {SNAME_ATTR, SOURCE_ATTR},
    SCHED_TYPE: {SNAME_ATTR, ACT_ATTR, VACFLO_ATTR},
    SYSTEM_TYPE: {MODE_ATTR, VACFLO_ATTR, SERVICE_ATTR},
}

type IntelliCenterConfigEntry = ConfigEntry[IntelliCenterHandler]

# -------------------------------------------------------------------------------------


class IntelliCenterHandler(ConnectionHandler):
    """Keep a config entry connected to its IntelliCenter."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, controller: ModelController
    ):
        """Initialize."""
        super().__init__(controller)
        self._hass = hass
        self._entry_id = entry.entry_id
        self.monitor = HeaterAssignmentMonitor(hass, entry.entry_id, controller.model)
        # follows equipment changes once the integration is set up
        self.watcher: EquipmentWatcher | None = None
        # the registry ID of the IntelliCenter's device
        self.system_device_id: str | None = None

    @callback
    def reconnected(self, controller):
        """Handle reconnection to the IntelliCenter."""
        _LOGGER.info(f"reconnected to {controller.host}")
        dispatcher.async_dispatcher_send(
            self._hass, connection_signal(self._entry_id), True
        )
        self.monitor.async_check()
        if self.watcher:
            # the IntelliCenter may have restarted after its equipment changed
            self._hass.async_create_background_task(
                self.watcher.async_check(), "intellicenter equipment check"
            )

    @callback
    def disconnected(self, controller, exc):
        """Handle the connection to the IntelliCenter being lost."""
        # what the model says is stale until reconnected (see reconnected)
        self.monitor.async_cancel_timers()
        dispatcher.async_dispatcher_send(
            self._hass, connection_signal(self._entry_id), False
        )

    @callback
    def updated(self, controller, updates: dict[str, dict[str, str]]):
        """Handle updates from the IntelliCenter."""
        _LOGGER.debug(f"received update for {len(updates)} pool objects")
        dispatcher.async_dispatcher_send(
            self._hass, update_signal(self._entry_id), updates
        )
        self.monitor.async_check(updates)
        if self.watcher:
            self.watcher.async_updated(updates)

    @callback
    def stop_watching(self) -> None:
        """Stop the heater and equipment checks."""
        self.monitor.async_stop(clear_issues=False)
        if self.watcher:
            self.watcher.async_stop()


# -------------------------------------------------------------------------------------


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Pentair IntelliCenter Integration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: IntelliCenterConfigEntry) -> bool:
    """Set up IntelliCenter integration from a config entry."""

    host = entry.data[CONF_HOST]
    controller = ModelController(host, PoolModel(ATTRIBUTES_MAP), loop=hass.loop)
    handler = IntelliCenterHandler(hass, entry, controller)

    try:
        await _async_setup(hass, entry, handler)
    except BaseException:
        # nothing may keep running (or reconnecting) after a failed setup
        handler.stop_watching()
        handler.stop()
        raise

    return True


async def _async_setup(
    hass: HomeAssistant, entry: IntelliCenterConfigEntry, handler: IntelliCenterHandler
) -> None:
    controller = handler.controller
    host = controller.host

    # connect now, so that a system that can't be reached shows as such (and
    # setup is retried) instead of a setup that succeeds without any entity
    try:
        await handler.connect(SETUP_TIMEOUT)
    except Exception as err:  # noqa: BLE001 - any failure: try again later
        raise ConfigEntryNotReady(
            f"cannot connect to the IntelliCenter at {host}: {err!r}"
        ) from err

    _LOGGER.info(
        f"connected to '{controller.systemInfo.propName}' at {host}"
        f" ({controller.model.numObjects} objects,"
        f" firmware {controller.systemInfo.swVersion})"
    )
    for obj in controller.model:
        _LOGGER.debug(f"   loaded {obj}")

    entry.runtime_data = handler

    _async_migrate_registry(hass, entry, controller.model)

    device_registry = dr.async_get(hass)
    handler.system_device_id = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, **system_device_info(entry, controller)
    ).id
    known_devices = {
        device.id
        for device in dr.async_entries_for_config_entry(
            device_registry, entry.entry_id
        )
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_place_new_devices(hass, entry, known_devices)

    handler.monitor.async_start()
    handler.watcher = EquipmentWatcher(hass, entry, controller, set(ATTRIBUTES_MAP))
    handler.watcher.async_start()

    @callback
    def on_hass_stop(event: Event) -> None:
        """Disconnect when Home Assistant stops."""
        handler.stop()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, on_hass_stop)
    )


async def async_unload_entry(hass: HomeAssistant, entry: IntelliCenterConfigEntry) -> bool:
    """Unload IntelliCenter config entry."""

    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    handler = entry.runtime_data
    handler.monitor.async_stop()
    if handler.watcher:
        handler.watcher.async_stop()
    handler.stop()
    _LOGGER.info(f"disconnected from {handler.controller.host}")

    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: IntelliCenterConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow removing a device, except the IntelliCenter's and current equipment's.

    The device of equipment the IntelliCenter still has would come back at the
    next start anyway.
    """
    handler = getattr(entry, "runtime_data", None)
    model = handler.controller.model if handler else None
    system = system_id(entry)
    prefix = f"{system}_"
    for domain, identifier in device.identifiers:
        if domain != DOMAIN:
            continue
        if identifier == system:
            return False
        if (
            model is not None
            and identifier.startswith(prefix)
            and model[identifier[len(prefix):]] is not None
        ):
            return False
    return True


# -------------------------------------------------------------------------------------


@callback
def _async_migrate_registry(
    hass: HomeAssistant, entry: ConfigEntry, model: PoolModel
) -> None:
    """Move entities and the IntelliCenter's device to their current IDs.

    Before 3.0 (and in dwradcliffe's version) unique IDs started with the config
    entry ID, which changes every time the system is added to Home Assistant;
    joyfulhouse's version adds an underscore after it. They now start with the
    ID the IntelliCenter gives (like dwradcliffe's PR #46), so removing and
    adding the system again restores entity customizations. Entities keep their
    entity IDs, history and settings.

    This runs at every setup: it is cheap, does nothing once done, and also
    catches entities left by another version installed in between.
    """
    new_prefix = system_id(entry)
    old_prefix = entry.entry_id

    def known(rest: str) -> bool:
        """Return True if rest starts with the name of a known object."""
        return any(rest.startswith(objnam) for objnam in model.objects)

    entity_registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        unique_id = registry_entry.unique_id
        if not unique_id.startswith(old_prefix):
            continue
        rest = unique_id[len(old_prefix):]
        # some objects' names start with an underscore ("_A135"): an underscore
        # is joyfulhouse's separator only if the object name follows it
        if rest.startswith("_") and not known(rest) and known(rest[1:]):
            rest = rest[1:]
        new_unique_id = new_prefix + rest
        if new_unique_id == unique_id:
            continue
        if entity_registry.async_get_entity_id(
            registry_entry.domain, registry_entry.platform, new_unique_id
        ):
            _LOGGER.warning(
                f"not migrating {registry_entry.entity_id}: another entity already"
                f" has its new unique ID {new_unique_id}"
            )
            continue
        _LOGGER.info(f"migrating {registry_entry.entity_id} to unique ID {new_unique_id}")
        entity_registry.async_update_entity(
            registry_entry.entity_id, new_unique_id=new_unique_id
        )

    if new_prefix != old_prefix:
        device_registry = dr.async_get(hass)
        device = get_device(device_registry, (DOMAIN, old_prefix), entry.entry_id)
        if device and not get_device(
            device_registry, (DOMAIN, new_prefix), entry.entry_id
        ):
            device_registry.async_update_device(
                device.id, new_identifiers={(DOMAIN, new_prefix)}
            )


@callback
def _async_place_new_devices(
    hass: HomeAssistant, entry: ConfigEntry, known_devices: set[str]
) -> None:
    """Put devices created by this setup in the IntelliCenter's area.

    Bodies, pumps, heaters and chemistry controllers became devices of their
    own in 3.0: their entities used to belong to the IntelliCenter's device, so
    an area given to it covered them too.
    """
    device_registry = dr.async_get(hass)
    system = get_device(device_registry, (DOMAIN, system_id(entry)), entry.entry_id)
    if system is None or system.area_id is None:
        return
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if device.id not in known_devices and device.area_id is None:
            device_registry.async_update_device(device.id, area_id=system.area_id)
