"""Tests for hOn control switches."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from custom_components.hon.const import DOMAIN

from .conftest import FakeAppliance, FakeHon


def with_commands(appliance: FakeAppliance) -> FakeAppliance:
    appliance.sync_command = MagicMock()  # type: ignore[attr-defined]
    for name in ("startProgram", "stopProgram"):
        appliance.commands[name] = MagicMock(send=AsyncMock(), settings={})
    return appliance


async def set_up(
    hass: HomeAssistant, config_entry: MockConfigEntry, unique_id: str
) -> State:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    entity_id = er.async_get(hass).async_get_entity_id("switch", DOMAIN, unique_id)
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    return state


async def call(hass: HomeAssistant, service: str, entity_id: str) -> None:
    await hass.services.async_call(
        "switch", service, {"entity_id": entity_id}, blocking=True
    )


async def test_washer_switch_follows_mach_mode(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    appliances: list[FakeAppliance],
) -> None:
    # hOn keeps "active" set after the cycle ends; machMode 7 means it ended
    washer = with_commands(FakeAppliance("WM", {"active": True, "machMode": 7}))
    appliances.append(washer)
    state = await set_up(hass, config_entry, "wm_testactive")
    assert state.state == "off"

    await call(hass, "turn_on", state.entity_id)
    washer.commands["startProgram"].send.assert_awaited_once_with(False)
    assert "active" not in washer.attributes  # the next status sets the state


async def test_water_heater_power_uses_on_off_values(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    appliances: list[FakeAppliance],
) -> None:
    heater = with_commands(FakeAppliance("WH", {"onOffStatus": 1}))
    appliances.append(heater)
    state = await set_up(hass, config_entry, "wh_testonOffStatus")
    assert state.state == "on"

    await call(hass, "turn_off", state.entity_id)
    heater.commands["stopProgram"].send.assert_awaited_once_with(True)
    assert heater.attributes["onOffStatus"] == 0
