"""Repair issues about the IntelliCenter's own configuration."""

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN
from .pyintellicenter import (
    BODY_ATTR,
    BODY_TYPE,
    HEATER_ATTR,
    HEATER_TYPE,
    HTMODE_ATTR,
    LOTMP_ATTR,
    LSTTMP_ATTR,
    NULL_OBJNAM,
    STATUS_ATTR,
    PoolModel,
    PoolObject,
)

HEATER_NOT_HEATING = "heater_not_heating"
# the v2.2 issue, raised on the configuration alone
LEGACY_HEATER_NOT_ASSIGNED = "heater_not_assigned"

# how long a body may stay unheated before we say so: the panel can delay
# starting a heater by a few minutes (heater delay, pump priming, valves)
NOT_HEATING_DELAY = 600

# body attributes the check depends on
WATCHED_BODY_ATTRIBUTES = {STATUS_ATTR, HEATER_ATTR, HTMODE_ATTR, LOTMP_ATTR, LSTTMP_ATTR}


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class HeaterAssignmentMonitor:
    """Explain a body that never heats because its heater isn't assigned to it.

    A body can keep a heater selected after the heater was unassigned from it in
    the IntelliCenter settings. On some systems the IntelliCenter then never
    heats that body (the pump runs and the water stays cold, with nothing to say
    why); on others it heats it anyway. So the configuration alone proves
    nothing: an issue is raised only when the symptom shows, i.e. the body is
    on, below its target, with an unassigned heater selected, and isn't heated
    for NOT_HEATING_DELAY seconds. It clears once the body heats or the heater
    is assigned to it (or another heat source is selected).
    """

    def __init__(self, hass: HomeAssistant, entry_id: str, model: PoolModel):
        """Initialize."""
        self._hass = hass
        self._entry_id = entry_id
        self._model = model
        self._timers: dict[str, CALLBACK_TYPE] = {}
        self.delay = NOT_HEATING_DELAY

    def _issue_id(self, body: PoolObject) -> str:
        return f"{HEATER_NOT_HEATING}_{self._entry_id}_{body.objnam}"

    def _unassigned_heater(self, body: PoolObject) -> PoolObject | None:
        """Return the heater the body selects if it isn't assigned to the body."""
        selected = body[HEATER_ATTR]
        if selected in (None, NULL_OBJNAM):
            return None
        heater = self._model[selected]
        # only a known heater that says which bodies it heats can be checked
        # (a heat source can also be a combination such as "solar preferred")
        if heater is None or heater.objtype != HEATER_TYPE or not heater[BODY_ATTR]:
            return None
        if body.objnam in heater[BODY_ATTR].split():
            return None
        return heater

    @staticmethod
    def _waiting_for_heat(body: PoolObject) -> bool:
        """Return True if the body is on, below its target and not being heated."""
        current, target = _float(body[LSTTMP_ATTR]), _float(body[LOTMP_ATTR])
        return (
            body[STATUS_ATTR] == "ON"
            and body[HTMODE_ATTR] == "0"
            and current is not None
            and target is not None
            and current < target
        )

    @callback
    def async_start(self) -> None:
        """Check every body (and clear issues an earlier version left)."""
        registry = ir.async_get(self._hass)
        for body in self._model.getByType(BODY_TYPE):
            legacy = f"{LEGACY_HEATER_NOT_ASSIGNED}_{self._entry_id}_{body.objnam}"
            if registry.async_get_issue(DOMAIN, legacy):
                ir.async_delete_issue(self._hass, DOMAIN, legacy)
        self.async_check()

    @callback
    def async_check(self, updates: dict[str, dict[str, str]] | None = None) -> None:
        """Re-evaluate the bodies affected by updates (all of them if None)."""
        if updates is not None:
            relevant = False
            for objnam, changes in updates.items():
                obj = self._model[objnam]
                if obj is None:
                    continue
                if obj.objtype == BODY_TYPE and WATCHED_BODY_ATTRIBUTES & changes.keys():
                    relevant = True
                elif obj.objtype == HEATER_TYPE and BODY_ATTR in changes:
                    relevant = True
            if not relevant:
                return
        for body in self._model.getByType(BODY_TYPE):
            self._check_body(body)

    @callback
    def _check_body(self, body: PoolObject) -> None:
        issue_id = self._issue_id(body)
        heater = self._unassigned_heater(body)
        heating = body[HTMODE_ATTR] not in (None, "0")

        if heater is None or heating:
            # nothing wrong, or the body does get heated on this system
            self._cancel_timer(body)
            ir.async_delete_issue(self._hass, DOMAIN, issue_id)
            return

        if not self._waiting_for_heat(body):
            # off, or warm enough: nothing to observe right now (an issue
            # already raised stays until the heater is assigned or heats)
            self._cancel_timer(body)
            return

        if body.objnam not in self._timers and not self._has_issue(issue_id):
            # (a callback, so that it runs in the event loop)
            self._timers[body.objnam] = async_call_later(
                self._hass,
                self.delay,
                callback(lambda _now, b=body: self._timer_fired(b)),
            )

    @callback
    def _timer_fired(self, body: PoolObject) -> None:
        self._timers.pop(body.objnam, None)
        heater = self._unassigned_heater(body)
        if heater is None or not self._waiting_for_heat(body):
            return
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            self._issue_id(body),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=HEATER_NOT_HEATING,
            translation_placeholders={
                "body": body.sname or body.objnam,
                "heater": heater.sname or heater.objnam,
                "minutes": str(round(self.delay / 60)),
            },
        )

    def _has_issue(self, issue_id: str) -> bool:
        return ir.async_get(self._hass).async_get_issue(DOMAIN, issue_id) is not None

    def _cancel_timer(self, body: PoolObject) -> None:
        cancel = self._timers.pop(body.objnam, None)
        if cancel:
            cancel()

    @callback
    def async_cancel_timers(self) -> None:
        """Stop waiting (until the next check), e.g. while disconnected."""
        for cancel in self._timers.values():
            cancel()
        self._timers.clear()

    @callback
    def async_stop(self, clear_issues: bool = True) -> None:
        """Cancel the timers and, unless told otherwise, remove the issues."""
        self.async_cancel_timers()
        if clear_issues:
            for body in self._model.getByType(BODY_TYPE):
                ir.async_delete_issue(self._hass, DOMAIN, self._issue_id(body))
