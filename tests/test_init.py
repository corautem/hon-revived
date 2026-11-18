"""Tests for setting up and unloading the hOn integration."""

import json
import logging
import threading
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pyhon.exceptions import HonAuthenticationError
from pytest_homeassistant.common import MockConfigEntry

from custom_components.hon import UNSUPPORTED_HA_ISSUE
from custom_components.hon.const import DOMAIN

from .conftest import PASSWORD, FakeHon, login_url_error

EN_JSON = Path(__file__).parent.parent / "custom_components/hon/translations/en.json"


async def test_older_home_assistant_is_refused_with_a_repair_issue(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_hon: FakeHon
) -> None:
    config_entry.add_to_hass(hass)
    with (
        patch("custom_components.hon.MINOR_VERSION", 10),
        patch("custom_components.hon.HA_VERSION", "2026.10.4"),
    ):
        assert not await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert fake_hon.notify is None  # stopped before logging in to hOn
    issue = ir.async_get(hass).async_get_issue(DOMAIN, UNSUPPORTED_HA_ISSUE)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.translation_placeholders == {
        "required": "2026.11.0",
        "installed": "2026.10.4",
    }
    text = json.loads(EN_JSON.read_text(encoding="utf-8"))["issues"][
        UNSUPPORTED_HA_ISSUE
    ]
    for placeholder in ("{required}", "{installed}"):
        assert placeholder in text["description"]


async def test_supported_home_assistant_clears_the_repair_issue(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_hon: FakeHon
) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        UNSUPPORTED_HA_ISSUE,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=UNSUPPORTED_HA_ISSUE,
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert ir.async_get(hass).async_get_issue(DOMAIN, UNSUPPORTED_HA_ISSUE) is None


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
