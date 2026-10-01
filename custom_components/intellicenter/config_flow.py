"""Config flow for Pentair Intellicenter integration."""

import asyncio
import logging
from typing import Optional

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .const import DOMAIN, FLOW_TIMEOUT
from .pyintellicenter import BaseController, SystemInfo

_LOGGER = logging.getLogger(__name__)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class IntelliCenterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pentair Intellicenter config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[ConfigType] = None
    ) -> ConfigFlowResult:
        """Handle a flow initiated by the user."""
        if user_input is None:
            return self._show_setup_form()

        try:
            system_info = await self._get_system_info(user_input[CONF_HOST])
        except CannotConnect:
            return self._show_setup_form({"base": "cannot_connect"})
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("unexpected error while connecting")
            return self._show_setup_form({"base": "unknown"})

        # Check if already configured
        await self.async_set_unique_id(system_info.uniqueID)
        self._abort_if_unique_id_configured(updates={CONF_HOST: user_input[CONF_HOST]})

        return self.async_create_entry(
            title=system_info.propName, data={CONF_HOST: user_input[CONF_HOST]}
        )

    async def async_step_reconfigure(
        self, user_input: Optional[ConfigType] = None
    ) -> ConfigFlowResult:
        """Change the address of a configured IntelliCenter."""
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            try:
                system_info = await self._get_system_info(user_input[CONF_HOST])
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("unexpected error while connecting")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(system_info.uniqueID)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_HOST: user_input[CONF_HOST]}
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST,
                        default=(user_input or entry.data).get(CONF_HOST, ""),
                    ): str
                }
            ),
            errors=errors,
        )

    async def async_step_zeroconf(self, discovery_info) -> ConfigFlowResult:
        """Handle device found via zeroconf."""

        _LOGGER.debug(f"zeroconf discovery {discovery_info}")

        host = discovery_info.host

        if self._host_already_configured(host):
            return self.async_abort(reason="already_configured")

        try:
            system_info = await self._get_system_info(host)
        except CannotConnect:
            return self.async_abort(reason="cannot_connect")
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("unexpected error while connecting")
            return self.async_abort(reason="unknown")

        await self.async_set_unique_id(system_info.uniqueID)

        # if this system is already configured, update its address (it may
        # have changed) instead of offering to add it again
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self.context.update(
            {
                CONF_HOST: host,
                CONF_NAME: system_info.propName,
                "title_placeholders": {"name": system_info.propName},
            }
        )

        return self._show_confirm_dialog()

    async def async_step_zeroconf_confirm(
        self, user_input: ConfigType = None
    ) -> ConfigFlowResult:
        """Handle a flow initiated by zeroconf."""
        if user_input is None:
            return self._show_confirm_dialog()

        try:
            system_info = await self._get_system_info(self.context.get(CONF_HOST))
        except CannotConnect:
            return self.async_abort(reason="cannot_connect")
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("unexpected error while connecting")
            return self.async_abort(reason="unknown")

        # Check if already configured
        await self.async_set_unique_id(system_info.uniqueID)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=system_info.propName, data={CONF_HOST: self.context.get(CONF_HOST)}
        )

    def _show_setup_form(self, errors: Optional[dict] = None) -> ConfigFlowResult:
        """Show the setup form to the user."""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors or {},
        )

    def _show_confirm_dialog(self) -> ConfigFlowResult:
        """Show the confirm dialog to the user."""

        host = self.context.get(CONF_HOST)
        name = self.context.get(CONF_NAME)

        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={"host": host, "name": name},
        )

    async def _get_system_info(self, host: str) -> SystemInfo:
        """Connect to the host and retrieve basic system information."""

        controller = BaseController(host, loop=self.hass.loop, keepAliveInterval=0)

        try:
            async with asyncio.timeout(FLOW_TIMEOUT):
                await controller.start()
            return controller.systemInfo
        except (OSError, TimeoutError) as err:
            raise CannotConnect from err
        finally:
            controller.stop()

    def _host_already_configured(self, host):
        """Check if we already have a system with the same host address."""
        existing_hosts = {
            entry.data[CONF_HOST]
            for entry in self._async_current_entries()
            if CONF_HOST in entry.data
        }
        return host in existing_hosts
