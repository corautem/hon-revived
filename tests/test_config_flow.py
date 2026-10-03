"""Tests for the hOn config flow."""

import logging
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientConnectionError
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pyhon.exceptions import HonAuthenticationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hon.const import DOMAIN

from .conftest import EMAIL, PASSWORD, login_url_error

USER_INPUT = {"email": EMAIL, "password": PASSWORD}


@pytest.fixture
def mock_api() -> Iterator[MagicMock]:
    api = MagicMock()
    api.create = AsyncMock(return_value=api)
    api.load_appliances = AsyncMock(return_value=[])
    api.close = AsyncMock()
    with patch("custom_components.hon.config_flow.HonAPI", return_value=api):
        yield api


@pytest.fixture(autouse=True)
def no_entry_setup() -> Iterator[None]:
    with patch("custom_components.hon.async_setup_entry", return_value=True):
        yield


async def test_user_flow_creates_entry(
    hass: HomeAssistant, mock_api: MagicMock
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == EMAIL
    assert result["data"] == USER_INPUT
    mock_api.load_appliances.assert_awaited_once()
    mock_api.close.assert_awaited_once()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (HonAuthenticationError("Can't login"), "invalid_auth"),
        (ClientConnectionError(), "cannot_connect"),
        (TimeoutError(), "cannot_connect"),
        (ValueError(), "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, mock_api: MagicMock, error: Exception, expected: str
) -> None:
    mock_api.load_appliances.side_effect = error
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}
    mock_api.close.assert_awaited_once()

    mock_api.load_appliances.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_login_error_does_not_log_password(
    hass: HomeAssistant, mock_api: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    mock_api.load_appliances.side_effect = login_url_error()
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["errors"] == {"base": "cannot_connect"}
    assert "ContentTypeError" in caplog.text
    assert PASSWORD not in caplog.text


async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_api: MagicMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    mock_api.load_appliances.assert_not_awaited()


async def test_reauth_updates_password(
    hass: HomeAssistant, mock_api: MagicMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    mock_api.load_appliances.side_effect = HonAuthenticationError("Can't login")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"password": "still-wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}
    assert config_entry.data["password"] == PASSWORD

    mock_api.load_appliances.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"password": "new-password"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data["password"] == "new-password"
    assert config_entry.data["email"] == EMAIL
