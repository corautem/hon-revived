"""Tests for setting up and unloading the hOn integration."""

import logging
import threading
from typing import Any

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from pyhon.exceptions import HonAuthenticationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hon.const import DOMAIN

from .conftest import PASSWORD, FakeHon, login_url_error


async def test_unload_stops_the_mqtt_connection(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_hon: FakeHon
) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.data["refresh_token"] == "refresh-token"

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    assert DOMAIN not in hass.data
    fake_hon.mqtt_client._watchdog_task.cancel.assert_called_once()
    fake_hon.mqtt_client._client.stop.assert_called_once()
    fake_hon.close.assert_awaited_once()


async def test_rejected_login_starts_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_hon: FakeHon
) -> None:
    fake_hon.create_error = HonAuthenticationError("Can't login")
    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_connection_error_retries_without_logging_password(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    fake_hon.create_error = login_url_error()
    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert "ContentTypeError" in caplog.text
    assert PASSWORD not in caplog.text
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_mqtt_update_from_another_thread(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_hon: FakeHon
) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][config_entry.unique_id]["coordinator"]
    updates: list[tuple[Any, int]] = []
    remove = coordinator.async_add_listener(
        lambda: updates.append((coordinator.data, threading.get_ident()))
    )

    # pyhon calls the callback from the MQTT client thread; the coordinator
    # (and so every entity) must still be updated on the event loop thread
    assert fake_hon.notify is not None
    await hass.async_add_executor_job(fake_hon.notify, {"from": "mqtt"})
    await hass.async_block_till_done()
    assert updates == [({"from": "mqtt"}, threading.get_ident())]
    remove()
