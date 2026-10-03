"""Tests for hOn light entities."""

from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from pyhon.parameter.range import HonParameterRange
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import FakeAppliance, FakeHon


async def test_light_reports_color_mode(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    appliances: list[FakeAppliance],
) -> None:
    dishwasher = FakeAppliance("DW", {"lightStatus": 1})
    dishwasher.settings["settings.lightStatus"] = HonParameterRange(
        "lightStatus",
        {"minimumValue": "0", "maximumValue": "1", "incrementValue": "1"},
        "parameters",
    )
    dishwasher.available_settings.append("settings.lightStatus")
    appliances.append(dishwasher)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("light.dw_light")
    assert state is not None
    assert state.state == STATE_ON
    assert state.attributes["color_mode"] == "onoff"
    assert state.attributes["supported_color_modes"] == ["onoff"]
