"""JMGO Projector — Media Player Entity.

Provides a fully-featured media_player entity exposing:
- Power state (on/off/standby → unavailable)
- Volume level & mute
- Source selection (Android, HDMI 1, HDMI 2, USB, AV)
- Media controls (play/pause, stop, next, previous)
- Extra attributes: brightness, picture_mode
"""
from __future__ import annotations

import logging

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import API, COORDINATOR, DOMAIN
from .projector_api import JMGOProjectorAPI, PICTURE_MODES, SOURCE_IDS

_LOGGER = logging.getLogger(__name__)

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the JMGO media player entity."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    api: JMGOProjectorAPI = data[API]
    coordinator: DataUpdateCoordinator = data[COORDINATOR]

    async_add_entities(
        [JMGOMediaPlayer(coordinator, api, config_entry)],
        update_before_add=False,
    )


class JMGOMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    """Media Player entity for JMGO Projector.

    Reflects the projector's real-time state (polled every 30 s) and
    exposes all supported controls to Home Assistant.
    """

    _attr_has_entity_name = True
    _attr_name = "Media Player"
    _attr_icon = "mdi:projector"
    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_supported_features = SUPPORTED_FEATURES
    _attr_source_list = list(SOURCE_IDS.keys())

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        api: JMGOProjectorAPI,
        config_entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._api = api
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.unique_id}_media_player"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info — same identifiers as remote to group them."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._config_entry.unique_id)},
            name=self._config_entry.data.get("name", "JMGO Projector"),
            manufacturer="JMGO",
            model="N5S Ultra Max",
        )

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """True if projector is reachable on the network."""
        if self.coordinator.data is None:
            return False
        return self.coordinator.data.available

    @property
    def state(self) -> MediaPlayerState | None:
        """Return the current state."""
        if self.coordinator.data is None:
            return None
        if not self.coordinator.data.available:
            return MediaPlayerState.OFF
        if self.coordinator.data.is_on:
            return MediaPlayerState.ON
        return MediaPlayerState.STANDBY

    # ------------------------------------------------------------------
    # Volume
    # ------------------------------------------------------------------

    @property
    def volume_level(self) -> float | None:
        """Volume level as 0.0–1.0."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.volume / 100.0

    @property
    def is_volume_muted(self) -> bool | None:
        """Return mute state."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.is_muted

    # ------------------------------------------------------------------
    # Source
    # ------------------------------------------------------------------

    @property
    def source(self) -> str | None:
        """Current input source."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.source

    # ------------------------------------------------------------------
    # Extra attributes
    # ------------------------------------------------------------------

    @property
    def extra_state_attributes(self) -> dict:
        """Expose brightness and picture_mode as extra attributes."""
        attrs: dict = {}
        if self.coordinator.data is None:
            return attrs
        if self.coordinator.data.brightness is not None:
            attrs["brightness"] = self.coordinator.data.brightness
        if self.coordinator.data.picture_mode is not None:
            attrs["picture_mode"] = self.coordinator.data.picture_mode
        attrs["available_picture_modes"] = PICTURE_MODES
        return attrs

    # ------------------------------------------------------------------
    # Power commands
    # ------------------------------------------------------------------

    async def async_turn_on(self) -> None:
        """Turn the projector on."""
        await self._api.async_power_toggle()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Turn the projector off."""
        await self._api.async_turn_off()
        await self.coordinator.async_request_refresh()

    # ------------------------------------------------------------------
    # Volume commands
    # ------------------------------------------------------------------

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume from HA (0.0 – 1.0 → 0–100)."""
        await self._api.async_set_volume(int(round(volume * 100)))
        await self.coordinator.async_request_refresh()

    async def async_volume_up(self) -> None:
        """Increase volume by 1."""
        await self._api.async_volume_up()
        await self.coordinator.async_request_refresh()

    async def async_volume_down(self) -> None:
        """Decrease volume by 1."""
        await self._api.async_volume_down()
        await self.coordinator.async_request_refresh()

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute."""
        if mute:
            await self._api.async_mute()
        else:
            await self._api.async_unmute()
        await self.coordinator.async_request_refresh()

    # ------------------------------------------------------------------
    # Source selection
    # ------------------------------------------------------------------

    async def async_select_source(self, source: str) -> None:
        """Switch input source."""
        await self._api.async_select_source(source)
        await self.coordinator.async_request_refresh()

    # ------------------------------------------------------------------
    # Media playback controls
    # ------------------------------------------------------------------

    async def async_media_play_pause(self) -> None:
        """Toggle play/pause."""
        await self._api.async_send_key("play_pause")

    async def async_media_play(self) -> None:
        """Send play."""
        await self._api.async_send_key("play_pause")

    async def async_media_pause(self) -> None:
        """Send pause."""
        await self._api.async_send_key("play_pause")

    async def async_media_stop(self) -> None:
        """Send stop."""
        await self._api.async_send_key("stop")

    async def async_media_next_track(self) -> None:
        """Skip to next."""
        await self._api.async_send_key("next")

    async def async_media_previous_track(self) -> None:
        """Go to previous."""
        await self._api.async_send_key("prev")
