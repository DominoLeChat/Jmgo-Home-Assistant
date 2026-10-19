"""Media player support for JMGO projector using existing Projector client."""
from __future__ import annotations

from typing import Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    SUPPORT_VOLUME_SET,
    SUPPORT_VOLUME_STEP,
    SUPPORT_TURN_ON,
    SUPPORT_TURN_OFF,
)
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN

from .Projector import Projector, match_power_state
from .const import DOMAIN
import logging

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    # Backwards compatibility for platform setup
    host = config.get(CONF_HOST)
    name = config.get(CONF_NAME)
    port = config.get(CONF_PORT)
    unique_id = f"{name}-{host}-media_player"

    xgimi_api = Projector(host, port)
    async_add_entities([XgimiMediaPlayer(xgimi_api, name, unique_id)])


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    config = hass.data[DOMAIN][config_entry.entry_id]
    host = config[CONF_HOST]
    name = config[CONF_NAME]
    port = config[CONF_PORT]

    unique_id = config_entry.unique_id
    assert unique_id is not None

    store = hass.data[DOMAIN].setdefault(config_entry.entry_id, {})
    client = store.get("client")
    if client is None:
        client = Projector(host, port)
        store["client"] = client

    media_unique = f"{unique_id}-media_player"
    async_add_entities([XgimiMediaPlayer(client, name, media_unique)])


class XgimiMediaPlayer(MediaPlayerEntity):
    """Media player for JMGO projector, reusing Projector client."""

    def __init__(self, client: Projector, name: str, unique_id: str):
        self._client = client
        self._name = f"{name} Media Player"
        self._unique_id = unique_id
        self._attr_icon = "mdi:projector"
        self._available = False
        self._power_known = False

    def update(self) -> None:
        """Fetch latest data from the projector synchronously."""
        try:
            self._client.async_fetch_data()
            # volume is updated into client.volume by async_fetch_data
            # power detection via match_power_state is done there; we inspect client attributes
            self._available = True
        except Exception as exc:  # keep minimal changes to client behavior
            _LOGGER.debug("Error fetching data from JMGO client: %s", exc)
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    @property
    def unique_id(self) -> str:
        return self._unique_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self):
        # Only report ON/OFF if power_state was explicitly parsed by client
        try:
            # Projector.async_check_alive may set internal flags; we rely on client's logic
            power = None
            # try to re-check quickly
            # Note: avoid network calls here; prefer the stored state from last update
            # Some Projector implementations set _is_on; fall back to that
            if hasattr(self._client, "_is_on"):
                power = self._client._is_on
            if power is True:
                return STATE_ON
            if power is False:
                return STATE_OFF
            return STATE_UNKNOWN
        except Exception:
            return STATE_UNKNOWN

    @property
    def volume_level(self) -> float | None:
        vol = getattr(self._client, "volume", None)
        if vol is None:
            return None
        try:
            return max(0.0, min(1.0, vol / 100.0))
        except Exception:
            return None

    @property
    def supported_features(self) -> int:
        features = SUPPORT_VOLUME_SET | SUPPORT_VOLUME_STEP
        # offer turn on/off only if client provides power info (we check for match_power_state presence)
        # Heuristic: if async_check_alive returns power info via _is_on attribute, allow turn on/off
        if hasattr(self._client, "_is_on"):
            # only advertise turn on/off if client can report power state
            features |= SUPPORT_TURN_ON | SUPPORT_TURN_OFF
        return features

    def _level_to_volume(self, level: float) -> int:
        return int(round(max(0.0, min(1.0, level)) * 100))

    def async_set_volume_level(self, volume: float) -> None:
        """Set volume as 0.0-1.0 using existing client set_volume."""
        v = self._level_to_volume(volume)
        try:
            self._client.set_volume(v)
            self._client.volume = v
        except Exception as exc:
            _LOGGER.debug("Error setting volume on JMGO client: %s", exc)

    def async_volume_up(self) -> None:
        try:
            self._client.volup()
        except Exception as exc:
            _LOGGER.debug("Error increasing volume on JMGO client: %s", exc)

    def async_volume_down(self) -> None:
        try:
            self._client.voldown()
        except Exception as exc:
            _LOGGER.debug("Error decreasing volume on JMGO client: %s", exc)

    def async_turn_on(self) -> None:
        # Prudent power handling: only send if we know the current power state and action is coherent
        try:
            # ensure state fetched recently
            self._client.async_fetch_data()
            # Check known power flags
            power = getattr(self._client, "_is_on", None)
            # If unknown, refuse to send power to avoid unwanted behavior
            if power is None:
                _LOGGER.warning("Power state unknown; refusing to send power toggle (turn_on)")
                return
            if power is False:
                self._client.async_send_command("power")
        except Exception as exc:
            _LOGGER.debug("Error turning on JMGO client: %s", exc)

    def async_turn_off(self) -> None:
        try:
            self._client.async_fetch_data()
            power = getattr(self._client, "_is_on", None)
            if power is None:
                _LOGGER.warning("Power state unknown; refusing to send power toggle (turn_off)")
                return
            if power is True:
                self._client.async_send_command("power")
        except Exception as exc:
            _LOGGER.debug("Error turning off JMGO client: %s", exc)
