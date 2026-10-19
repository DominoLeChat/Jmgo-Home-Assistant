"""
JMGO Projector LAN Protocol API.

Based on reverse-engineering of the TCP protocol used by the official
"坚果控" (JMGO Control) mobile app. Port 9005.

Protocol overview:
- Binary protobuf-like frames for key events (press/release pairs)
- JSON-over-binary frames for status queries and settings (setVolume, reqinfo, etc.)
- Connection: TCP on port 9005
- Status polling: send 'Hello Server!' then read response
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import socket
from dataclasses import dataclass, field
from typing import Any

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 9005
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 3

# ---------------------------------------------------------------------------
# Key command byte payloads (press + release pairs)
# Derived from packet captures: N1S Ultra / JMGO N5S series
# Format: each key has [press_bytes, release_bytes]
# ---------------------------------------------------------------------------
KEY_COMMANDS: dict[str, list[bytes]] = {
    # Power / System
    "power":   [b"\x09\x12\x07\x0a\x05\x08\xc3\x05\x10\x01",
                b"\x09\x12\x07\x0a\x05\x08\xc3\x05\x10\x00"],
    "home":    [b"\x09\x12\x07\x0a\x05\x08\xc2\x05\x10\x01",
                b"\x09\x12\x07\x0a\x05\x08\xc2\x05\x10\x00"],
    "back":    [b"\x08\x12\x06\x0a\x04\x08\x04\x10\x01",
                b"\x08\x12\x06\x0a\x04\x08\x04\x10\x00"],
    "menu":    [b"\x09\x12\x07\x0a\x05\x08\xdd\x04\x10\x01",
                b"\x09\x12\x07\x0a\x05\x08\xdd\x04\x10\x00"],
    "ok":      [b"\x08\x12\x06\x0a\x04\x08\x17\x10\x01",
                b"\x08\x12\x06\x0a\x04\x08\x17\x10\x00"],
    # Navigation
    "up":      [b"\x08\x12\x06\x0a\x04\x08\x13\x10\x01",
                b"\x08\x12\x06\x0a\x04\x08\x13\x10\x00"],
    "down":    [b"\x08\x12\x06\x0a\x04\x08\x14\x10\x01",
                b"\x08\x12\x06\x0a\x04\x08\x14\x10\x00"],
    "left":    [b"\x08\x12\x06\x0a\x04\x08\x15\x10\x01",
                b"\x08\x12\x06\x0a\x04\x08\x15\x10\x00"],
    "right":   [b"\x08\x12\x06\x0a\x04\x08\x16\x10\x01",
                b"\x08\x12\x06\x0a\x04\x08\x16\x10\x00"],
    "option":  [b"\x08\x12\x06\x0a\x04\x08\x52\x10\x01",
                b"\x08\x12\x06\x0a\x04\x08\x52\x10\x00"],
    # Media playback
    "play_pause": [b"\x08\x12\x06\x0a\x04\x08\x55\x10\x01",
                   b"\x08\x12\x06\x0a\x04\x08\x55\x10\x00"],
    "stop":       [b"\x08\x12\x06\x0a\x04\x08\x56\x10\x01",
                   b"\x08\x12\x06\x0a\x04\x08\x56\x10\x00"],
    "prev":       [b"\x08\x12\x06\x0a\x04\x08\x57\x10\x01",
                   b"\x08\x12\x06\x0a\x04\x08\x57\x10\x00"],
    "next":       [b"\x08\x12\x06\x0a\x04\x08\x58\x10\x01",
                   b"\x08\x12\x06\x0a\x04\x08\x58\x10\x00"],
    # Volume keys (for volume up/down without absolute set)
    "volume_up":   [b"\x08\x12\x06\x0a\x04\x08\x18\x10\x01",
                    b"\x08\x12\x06\x0a\x04\x08\x18\x10\x00"],
    "volume_down": [b"\x08\x12\x06\x0a\x04\x08\x19\x10\x01",
                    b"\x08\x12\x06\x0a\x04\x08\x19\x10\x00"],
    "mute_key":    [b"\x08\x12\x06\x0a\x04\x08\x1a\x10\x01",
                    b"\x08\x12\x06\x0a\x04\x08\x1a\x10\x00"],
}

# Source / input switching (sent as JSON-in-binary frames)
# Source IDs observed in packet captures
SOURCE_IDS: dict[str, str] = {
    "Android":  "0",   # built-in launcher / Android TV home
    "HDMI 1":   "1",
    "HDMI 2":   "2",
    "USB":      "3",
    "AV":       "4",
}
SOURCE_ID_TO_NAME: dict[str, str] = {v: k for k, v in SOURCE_IDS.items()}

# Picture modes
PICTURE_MODES = ["standard", "movie", "vivid", "sport", "user"]

# ---------------------------------------------------------------------------
# Volume absolute-set payload builder
# The payload is a JSON string wrapped in a binary length-prefixed frame.
# Frame: [total_len_byte] [0x12] [inner_len_byte] [0x22] [json_len_byte]
#        [0x0a] [0x0a] b"reqestinfo" [0x12] [json_payload_len_byte] + json_bytes
#
# Simpler approach (confirmed working): send raw JSON string as UTF-8.
# The projector also accepts bare JSON strings on the socket.
# ---------------------------------------------------------------------------

def _build_set_volume_cmd(volume: int) -> bytes:
    """Build the binary-framed setVolume command."""
    volume = max(0, min(100, int(volume)))
    json_str = f'{{"req":"setVolume","param":"{volume}"}}'
    json_bytes = json_str.encode("utf-8")
    jlen = len(json_bytes)

    # Inner payload = 0x0a 0x0a b"reqestinfo" 0x12 <jlen> <json>
    reqestinfo = b"reqestinfo"
    inner = b"\x0a\x0a" + reqestinfo + b"\x12" + bytes([jlen]) + json_bytes
    ilen = len(inner)

    # Outer frame = 0x22 <ilen> <inner>
    outer = b"\x22" + bytes([ilen]) + inner
    olen = len(outer)

    # Top frame = <olen+2_approx> 0x12 <olen> <outer>
    frame = bytes([olen + 2]) + b"\x12" + bytes([olen]) + outer
    return frame


def _build_set_source_cmd(source_id: str) -> bytes:
    """Build the setSource command frame."""
    json_str = f'{{"req":"setSource","param":"{source_id}"}}'
    json_bytes = json_str.encode("utf-8")
    jlen = len(json_bytes)

    reqestinfo = b"reqestinfo"
    inner = b"\x0a\x0a" + reqestinfo + b"\x12" + bytes([jlen]) + json_bytes
    ilen = len(inner)

    outer = b"\x22" + bytes([ilen]) + inner
    olen = len(outer)

    frame = bytes([olen + 2]) + b"\x12" + bytes([olen]) + outer
    return frame


def _build_set_brightness_cmd(level: int) -> bytes:
    """Build the setBrightness command frame (level 0-100)."""
    level = max(0, min(100, int(level)))
    json_str = f'{{"req":"setBrightness","param":"{level}"}}'
    json_bytes = json_str.encode("utf-8")
    jlen = len(json_bytes)

    reqestinfo = b"reqestinfo"
    inner = b"\x0a\x0a" + reqestinfo + b"\x12" + bytes([jlen]) + json_bytes
    ilen = len(inner)

    outer = b"\x22" + bytes([ilen]) + inner
    olen = len(outer)

    frame = bytes([olen + 2]) + b"\x12" + bytes([olen]) + outer
    return frame


def _build_set_picture_mode_cmd(mode: str) -> bytes:
    """Build the setPictureMode command frame."""
    json_str = f'{{"req":"setPictureMode","param":"{mode}"}}'
    json_bytes = json_str.encode("utf-8")
    jlen = len(json_bytes)

    reqestinfo = b"reqestinfo"
    inner = b"\x0a\x0a" + reqestinfo + b"\x12" + bytes([jlen]) + json_bytes
    ilen = len(inner)

    outer = b"\x22" + bytes([ilen]) + inner
    olen = len(outer)

    frame = bytes([olen + 2]) + b"\x12" + bytes([olen]) + outer
    return frame


# ---------------------------------------------------------------------------
# State parsing helpers
# ---------------------------------------------------------------------------

def _parse_volume(raw: str) -> int | None:
    """Extract volume value from raw socket response."""
    m = re.search(r'volume[":\s]*(\d{1,3})', raw)
    if m:
        return int(m.group(1))
    m = re.search(r'volume[\x00-\x1F](\d{1,3})', raw)
    if m:
        return int(m.group(1))
    return None


def _parse_power_state(raw: str) -> bool | None:
    """
    Extract power state.
    power_state == 0 → projector is ON (active)
    power_state == 3 → projector is in standby/OFF
    """
    m = re.search(r'power_state[":\s]*(\d)', raw)
    if m:
        val = int(m.group(1))
        if val == 0:
            return True
        if val == 3:
            return False
    return None


def _parse_source(raw: str) -> str | None:
    """Extract current source from raw response."""
    m = re.search(r'source_type[":\s]*(\d+)', raw)
    if m:
        sid = m.group(1)
        return SOURCE_ID_TO_NAME.get(sid, f"Source {sid}")
    return None


def _parse_brightness(raw: str) -> int | None:
    """Extract brightness from raw response."""
    m = re.search(r'brightness[":\s]*(\d+)', raw)
    if m:
        return int(m.group(1))
    return None


def _parse_picture_mode(raw: str) -> str | None:
    """Extract picture mode from raw response."""
    m = re.search(r'picture_?mode[":\s]*"?(\w+)"?', raw, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    return None


def _parse_mute(raw: str) -> bool | None:
    """Extract mute state from raw response."""
    m = re.search(r'mute[":\s]*(\d)', raw)
    if m:
        return bool(int(m.group(1)))
    return None


def _safe_decode(data: bytes) -> str:
    """Decode bytes with fallback to latin-1."""
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return data.decode("latin-1", errors="replace")


# ---------------------------------------------------------------------------
# Projector state dataclass
# ---------------------------------------------------------------------------

@dataclass
class ProjectorState:
    """Holds the last known state of the projector."""
    available: bool = False
    is_on: bool = False
    volume: int = 0
    is_muted: bool = False
    source: str | None = None
    brightness: int | None = None
    picture_mode: str | None = None
    # Raw response for debugging
    raw_response: str = ""


# ---------------------------------------------------------------------------
# Async Projector API
# ---------------------------------------------------------------------------

class JMGOProjectorAPI:
    """
    Async API for JMGO projector LAN control.

    All network I/O is done asynchronously using asyncio streams.
    Each command opens a fresh TCP connection (stateless approach
    matching the official app behavior).
    """

    def __init__(self, host: str, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self._state = ProjectorState()

    @property
    def state(self) -> ProjectorState:
        return self._state

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _open_connection(
        self,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Open a TCP connection with timeout."""
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=CONNECT_TIMEOUT,
        )
        return reader, writer

    async def _send_raw(self, data: bytes) -> None:
        """Send raw bytes and close connection."""
        try:
            reader, writer = await self._open_connection()
            writer.write(data)
            await writer.drain()
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        except asyncio.TimeoutError:
            _LOGGER.debug("JMGO: timeout sending command to %s:%s", self.host, self.port)
            raise
        except OSError as exc:
            _LOGGER.debug("JMGO: OSError sending command: %s", exc)
            raise

    async def _send_key(self, key: str) -> None:
        """Send a key press+release pair."""
        if key not in KEY_COMMANDS:
            _LOGGER.warning("JMGO: unknown key command '%s'", key)
            return
        press, release = KEY_COMMANDS[key]
        try:
            reader, writer = await self._open_connection()
            writer.write(press)
            await writer.drain()
            await asyncio.sleep(0.05)
            writer.write(release)
            await writer.drain()
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        except (asyncio.TimeoutError, OSError) as exc:
            _LOGGER.debug("JMGO: error sending key '%s': %s", key, exc)

    # ------------------------------------------------------------------
    # State polling
    # ------------------------------------------------------------------

    async def async_update(self) -> ProjectorState:
        """
        Poll the projector for current state.

        The projector responds to 'Hello Server!' with a greeting
        followed by a binary status frame containing volume, power_state,
        source_type, etc.
        """
        state = ProjectorState()
        try:
            reader, writer = await self._open_connection()
            # Send greeting
            writer.write(b"Hello Server!")
            await writer.drain()

            # Read first response chunk (greeting / device info)
            try:
                chunk1 = await asyncio.wait_for(reader.read(512), timeout=READ_TIMEOUT)
            except asyncio.TimeoutError:
                chunk1 = b""

            # Read second chunk (status payload)
            try:
                chunk2 = await asyncio.wait_for(reader.read(1024), timeout=READ_TIMEOUT)
            except asyncio.TimeoutError:
                chunk2 = b""

            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

            raw = _safe_decode(chunk1) + _safe_decode(chunk2)
            state.raw_response = raw

            # Parse power state
            power = _parse_power_state(raw)
            if power is not None:
                state.available = True
                state.is_on = power
            else:
                # If we connected but got no parseable power state,
                # treat as available and ON (connection proves it's up)
                state.available = True
                state.is_on = True

            # Parse other fields
            vol = _parse_volume(raw)
            if vol is not None:
                state.volume = vol

            mute = _parse_mute(raw)
            if mute is not None:
                state.is_muted = mute

            src = _parse_source(raw)
            if src is not None:
                state.source = src

            brightness = _parse_brightness(raw)
            if brightness is not None:
                state.brightness = brightness

            pmode = _parse_picture_mode(raw)
            if pmode is not None:
                state.picture_mode = pmode

        except ConnectionRefusedError:
            _LOGGER.debug("JMGO: connection refused on %s:%s (projector OFF/standby)", self.host, self.port)
            state.available = False
            state.is_on = False
        except asyncio.TimeoutError:
            _LOGGER.debug("JMGO: timeout connecting to %s:%s", self.host, self.port)
            state.available = False
        except OSError as exc:
            _LOGGER.debug("JMGO: OS error polling %s:%s — %s", self.host, self.port, exc)
            state.available = False

        self._state = state
        return state

    # ------------------------------------------------------------------
    # Power
    # ------------------------------------------------------------------

    async def async_power_toggle(self) -> None:
        """Toggle power (same button on/off on JMGO remotes)."""
        await self._send_key("power")

    async def async_turn_off(self) -> None:
        """
        Turn the projector off.
        JMGO uses a single power button, so we only send if it appears ON.
        """
        if self._state.is_on:
            await self._send_key("power")

    # ------------------------------------------------------------------
    # Volume
    # ------------------------------------------------------------------

    async def async_set_volume(self, volume: int) -> None:
        """Set absolute volume (0–100)."""
        volume = max(0, min(100, int(volume)))
        cmd = _build_set_volume_cmd(volume)
        await self._send_raw(cmd)
        self._state.volume = volume
        if volume > 0:
            self._state.is_muted = False

    async def async_volume_up(self) -> None:
        """Increment volume by 1 using absolute set."""
        new_vol = min(100, self._state.volume + 1)
        await self.async_set_volume(new_vol)

    async def async_volume_down(self) -> None:
        """Decrement volume by 1 using absolute set."""
        new_vol = max(0, self._state.volume - 1)
        await self.async_set_volume(new_vol)

    async def async_mute(self) -> None:
        """Mute by setting volume to 0."""
        await self.async_set_volume(0)
        self._state.is_muted = True

    async def async_unmute(self) -> None:
        """Restore volume after unmute (restore to 20 if was 0)."""
        if self._state.volume == 0:
            await self.async_set_volume(20)
        self._state.is_muted = False

    async def async_mute_toggle(self) -> None:
        """Toggle mute."""
        if self._state.is_muted:
            await self.async_unmute()
        else:
            await self.async_mute()

    # ------------------------------------------------------------------
    # Source / Input
    # ------------------------------------------------------------------

    async def async_select_source(self, source: str) -> None:
        """Switch input source by name."""
        source_id = SOURCE_IDS.get(source)
        if source_id is None:
            _LOGGER.warning("JMGO: unknown source '%s'. Available: %s", source, list(SOURCE_IDS.keys()))
            return
        cmd = _build_set_source_cmd(source_id)
        await self._send_raw(cmd)
        self._state.source = source

    # ------------------------------------------------------------------
    # Display settings
    # ------------------------------------------------------------------

    async def async_set_brightness(self, level: int) -> None:
        """Set brightness level (0–100)."""
        level = max(0, min(100, int(level)))
        cmd = _build_set_brightness_cmd(level)
        await self._send_raw(cmd)
        self._state.brightness = level

    async def async_set_picture_mode(self, mode: str) -> None:
        """Set picture mode (standard, movie, vivid, sport, user)."""
        mode = mode.lower()
        if mode not in PICTURE_MODES:
            _LOGGER.warning("JMGO: unknown picture mode '%s'. Available: %s", mode, PICTURE_MODES)
            return
        cmd = _build_set_picture_mode_cmd(mode)
        await self._send_raw(cmd)
        self._state.picture_mode = mode

    # ------------------------------------------------------------------
    # Key / remote commands
    # ------------------------------------------------------------------

    async def async_send_key(self, key: str) -> None:
        """Send a named key command."""
        await self._send_key(key)

    async def async_send_command(self, command: str) -> None:
        """
        Dispatch a command string to the appropriate action.

        Supports all KEY_COMMANDS keys plus:
          volup, voldown, mute, mute_toggle, power_toggle,
          source_<name>, brightness_<0-100>, picture_<mode>
        """
        command = command.strip().lower()

        if command in KEY_COMMANDS:
            await self._send_key(command)
        elif command == "volup":
            await self.async_volume_up()
        elif command == "voldown":
            await self.async_volume_down()
        elif command == "mute":
            await self.async_mute()
        elif command == "unmute":
            await self.async_unmute()
        elif command == "mute_toggle":
            await self.async_mute_toggle()
        elif command == "power_toggle":
            await self.async_power_toggle()
        elif command.startswith("source_"):
            source_name = command[7:].replace("_", " ").title()
            await self.async_select_source(source_name)
        elif command.startswith("brightness_"):
            try:
                level = int(command[11:])
                await self.async_set_brightness(level)
            except ValueError:
                _LOGGER.warning("JMGO: invalid brightness value in command '%s'", command)
        elif command.startswith("picture_"):
            mode = command[8:]
            await self.async_set_picture_mode(mode)
        else:
            _LOGGER.warning("JMGO: unknown command '%s'", command)
