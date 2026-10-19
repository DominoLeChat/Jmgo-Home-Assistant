"""JMGO Projector — Remote Entity.

Provides full remote control (key events) for the projector.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from homeassistant.components.remote import RemoteEntity, RemoteEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import API, COORDINATOR, DOMAIN
from .projector_api import JMGOProjectorAPI, KEY_COMMANDS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the JMGO remote entity."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    api: JMGOProjectorAPI = data[API]
    coordinator: DataUpdateCoordinator = data[COORDINATOR]

    async_add_entities(
        [JMGORemote(coordinator, api, config_entry)],
        update_before_add=False,
    )


class JMGORemote(CoordinatorEntity, RemoteEntity):
    """Remote entity for JMGO Projector.

    Supports all key commands discovered via packet capture of the
    official 坚果控 app.
    """

    _attr_has_entity_name = True
    _attr_name = "Remote"
    _attr_icon = "mdi:remote"
    _attr_supported_features = RemoteEntityFeature.LEARN_COMMAND

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        api: JMGOProjectorAPI,
        config_entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._api = api
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.unique_id}_remote"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._config_entry.unique_id)},
            name=self._config_entry.data.get("name", "JMGO Projector"),
            manufacturer="JMGO",
            model="N5S Ultra Max",
        )

    @property
    def is_on(self) -> bool:
        """Return True if the projector is on."""
        if self.coordinator.data is None:
            return False
        return self.coordinator.data.is_on

    @property
    def available(self) -> bool:
        """Return availability."""
        if self.coordinator.data is None:
            return False
        return self.coordinator.data.available

    @property
    def extra_state_attributes(self) -> dict:
        """Expose all known remote commands as an attribute."""
        return {"available_commands": sorted(KEY_COMMANDS.keys())}

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the projector on (power toggle)."""
        await self._api.async_power_toggle()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the projector off."""
        await self._api.async_turn_off()
        await self.coordinator.async_request_refresh()

    async def async_send_command(self, command: Iterable[str], **kwargs) -> None:
        """Send one or more remote commands."""
        for cmd in command:
            await self._api.async_send_command(cmd)
