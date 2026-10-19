import pytest
from types import SimpleNamespace
from unittest.mock import Mock

from custom_components.jmgo.media_player import XgimiMediaPlayer
from homeassistant.components.media_player import (
    SUPPORT_VOLUME_SET,
    SUPPORT_VOLUME_STEP,
    SUPPORT_TURN_ON,
    SUPPORT_TURN_OFF,
)


def make_client(volume=None, is_on=None):
    client = SimpleNamespace()
    client.volume = volume
    client._is_on = is_on
    client.async_fetch_data = Mock()
    client.set_volume = Mock()
    client.volup = Mock()
    client.voldown = Mock()
    client.async_send_command = Mock()
    return client


def test_volume_conversion_bounds():
    c = make_client(volume=50, is_on=True)
    mp = XgimiMediaPlayer(c, "Name", "id-media_player")
    assert mp.volume_level == pytest.approx(0.5)

    mp.async_set_volume_level(0.33)
    c.set_volume.assert_called_once_with(33)


def test_volume_none():
    c = make_client(volume=None, is_on=True)
    mp = XgimiMediaPlayer(c, "Name", "id-media_player")
    assert mp.volume_level is None


def test_availability_and_fetch():
    c = make_client(volume=10, is_on=True)
    mp = XgimiMediaPlayer(c, "Name", "id-media_player")
    mp.update()
    c.async_fetch_data.assert_called_once()


def test_prudent_power():
    # power known OFF -> turn_on should send power
    c = make_client(volume=10, is_on=False)
    mp = XgimiMediaPlayer(c, "Name", "id-media_player")
    mp.async_turn_on()
    c.async_send_command.assert_called_with("power")

    # power unknown -> turn_off should not send
    c2 = make_client(volume=10, is_on=None)
    mp2 = XgimiMediaPlayer(c2, "Name", "id-media_player")
    mp2.async_turn_off()
    c2.async_send_command.assert_not_called()


def test_supported_features_flags():
    c = make_client(volume=10, is_on=True)
    mp = XgimiMediaPlayer(c, "Name", "id-media_player")
    flags = mp.supported_features
    assert flags & SUPPORT_VOLUME_SET
    assert flags & SUPPORT_VOLUME_STEP
    # TURN_ON/TURN_OFF advertised because client provides _is_on attribute
    assert flags & SUPPORT_TURN_ON
    assert flags & SUPPORT_TURN_OFF
