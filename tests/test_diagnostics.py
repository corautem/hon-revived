"""Tests for the hOn diagnostics."""

import json
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hon.const import DOMAIN
from custom_components.hon.diagnostics import (
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)

from .conftest import FakeAppliance, FakeHon

ATTRIBUTES = {
    "serialNumber": "SN123456",
    "macAddress": "aa-bb-cc-dd-ee-ff",
    "topic": "haier/things/aa-bb-cc-dd-ee-ff/event",
    "parameters": {"temp": {"parNewVal": "180"}},
}
# A made-up Haier customer number, also listed as the camera's userId
APPLIANCE_DATA = {
    "sfPersonAccountId": "001R200000AbcDEfGHI",
    "camera": {
        "attributes": [{"parName": "userId", "parValue": "001R200000AbcDEfGHI"}]
    },
}


async def test_diagnostics_are_anonymized(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    appliances: list[FakeAppliance],
    device_registry: dr.DeviceRegistry,
) -> None:
    oven = FakeAppliance("OV", {})
    for topic in ("commands", "command_history", "statistics"):
        setattr(oven.api, f"load_{topic}", AsyncMock(return_value={}))
    oven.api.load_attributes = AsyncMock(return_value=ATTRIBUTES)
    oven.api.load_appliance_data = AsyncMock(return_value=APPLIANCE_DATA)
    oven.api.load_maintenance = AsyncMock(side_effect=TimeoutError)
    appliances.append(oven)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, config_entry)
    text = json.dumps(result)
    assert "SN123456" not in text
    assert "aa-bb-cc-dd-ee-ff" not in text
    assert "001R200000AbcDEfGHI" not in text
    appliance = result["appliances"][0]
    assert appliance["attributes"]["parameters"]["temp"]["parNewVal"] == "180"
    assert appliance["maintenance"] == "error: TimeoutError"

    devices = dr.async_entries_for_config_entry(device_registry, config_entry.entry_id)
    assert [device.identifiers for device in devices] == [{(DOMAIN, "ov_test")}]
    device_result = await async_get_device_diagnostics(hass, config_entry, devices[0])
    assert device_result == appliance
