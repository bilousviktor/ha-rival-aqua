"""Config flow for Rival Aqua."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RivalAquaClient, RivalError
from .const import DOMAIN

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_NAME, default="Aquarium light"): str,
    }
)


class RivalAquaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Rival Aqua."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            for prefix in ("http://", "https://"):
                host = host.removeprefix(prefix)
            host = host.rstrip("/")

            # The controller exposes no MAC/serial endpoint, so the host is the
            # identity. Give it a DHCP reservation on your router.
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

            client = RivalAquaClient(host, async_get_clientsession(self.hass))
            try:
                await client.async_get_info()
            except RivalError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME) or f"Rival {host}",
                    data={CONF_HOST: host},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_SCHEMA, user_input),
            errors=errors,
        )
