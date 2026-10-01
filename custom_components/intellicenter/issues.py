"""Repair issues about the IntelliCenter's own configuration."""

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .pyintellicenter import (
    BODY_ATTR,
    BODY_TYPE,
    HEATER_ATTR,
    HEATER_TYPE,
    NULL_OBJNAM,
    PoolModel,
)

HEATER_NOT_ASSIGNED = "heater_not_assigned"


def _issue_id(entry_id: str, body_objnam: str) -> str:
    return f"{HEATER_NOT_ASSIGNED}_{entry_id}_{body_objnam}"


@callback
def async_check_heater_assignments(
    hass: HomeAssistant, entry_id: str, model: PoolModel
) -> None:
    """Report bodies whose selected heater isn't assigned to them.

    A body keeps its selected heater when the heater is unassigned from it in
    the IntelliCenter settings, but the IntelliCenter then never heats that
    body: the pump runs and the water stays cold, with nothing to say why.
    """
    for body in model.getByType(BODY_TYPE):
        issue_id = _issue_id(entry_id, body.objnam)
        selected = body[HEATER_ATTR]
        heater = model[selected] if selected not in (None, NULL_OBJNAM) else None

        # only a known heater that says which bodies it heats can be checked
        # (a heat source can also be a combination such as "solar preferred")
        if (
            heater is not None
            and heater.objtype == HEATER_TYPE
            and heater[BODY_ATTR]
            and body.objnam not in heater[BODY_ATTR].split()
        ):
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=HEATER_NOT_ASSIGNED,
                translation_placeholders={
                    "body": body.sname or body.objnam,
                    "heater": heater.sname or heater.objnam,
                },
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


@callback
def async_clear_issues(hass: HomeAssistant, entry_id: str, model: PoolModel) -> None:
    """Remove the issues raised for a config entry."""
    for body in model.getByType(BODY_TYPE):
        ir.async_delete_issue(hass, DOMAIN, _issue_id(entry_id, body.objnam))
