"""JMGO Projector Integration — init."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API,
    COORDINATOR,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .projector_api import JMGOProjectorAPI, ProjectorState

_LOGGER = logging.getLogger(__name__)

PLATFORMS: Final[list[Platform]] = [
    Platform.REMOTE,
    Platform.MEDIA_PLAYER,
]


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up JMGO Projector from a config entry."""
    host = config_entry.data[CONF_HOST]
    port = int(config_entry.data.get(CONF_PORT, DEFAULT_PORT))

    api = JMGOProjectorAPI(host, port)

    # Initial poll to verify connectivity
    state = await api.async_update()
    if not state.available and not state.is_on:
        # Not reachable — raise so HA retries later
        _LOGGER.warning(
            "JMGO projector at %s:%s not reachable during setup. "
            "Will retry. Make sure the projector is on the network.",
            host, port,
        )
        # Don't raise ConfigEntryNotReady — projector may simply be off.
        # We allow the integration to load and show as unavailable.

    async def _async_update_data() -> ProjectorState:
        """Fetch state from the projector."""
        try:
            return await api.async_update()
        except Exception as exc:
            raise UpdateFailed(f"Error communicating with JMGO projector: {exc}") from exc

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"JMGO Projector ({host})",
        update_method=_async_update_data,
        update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
    )

    # Trigger first refresh (non-blocking — already done above)
    coordinator.data = state

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][config_entry.entry_id] = {
        API: api,
        COORDINATOR: coordinator,
        CONF_HOST: host,
        CONF_PORT: port,
        CONF_NAME: config_entry.data.get(CONF_NAME, "JMGO Projector"),
    }

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    # Register a reload listener
    config_entry.async_on_unload(config_entry.add_update_listener(_async_reload_entry))

    return True


async def _async_reload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Reload on options update."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
    if unload_ok:
        hass.data[DOMAIN].pop(config_entry.entry_id)
    return unload_ok
