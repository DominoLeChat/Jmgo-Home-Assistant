"""Config flow for JMGO Projector Integration."""
from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.data_entry_flow import FlowResult
from homeassistant.util.network import is_host_valid

from .const import DEFAULT_PORT, DOMAIN
from .projector_api import JMGOProjectorAPI


class JMGOConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for JMGO Projector."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            name = user_input[CONF_NAME].strip()
            port = int(user_input.get(CONF_PORT, DEFAULT_PORT))

            if not is_host_valid(host):
                errors[CONF_HOST] = "invalid_host"
            else:
                # Try to connect to the projector
                api = JMGOProjectorAPI(host, port)
                try:
                    state = await api.async_update()
                    # Connection succeeded (projector reachable or at least port open)
                except Exception:
                    errors["base"] = "cannot_connect"

                if not errors:
                    unique_id = f"{name}-{host}"
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=name,
                        data={
                            CONF_NAME: name,
                            CONF_HOST: host,
                            CONF_PORT: port,
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME,
                        default=(user_input or {}).get(CONF_NAME, "JMGO Projector"),
                    ): str,
                    vol.Required(
                        CONF_HOST,
                        default=(user_input or {}).get(CONF_HOST, ""),
                    ): str,
                    vol.Optional(
                        CONF_PORT,
                        default=(user_input or {}).get(CONF_PORT, DEFAULT_PORT),
                    ): int,
                }
            ),
            errors=errors,
        )
