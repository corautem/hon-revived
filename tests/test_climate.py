"""Tests for hOn climate entities."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pyhon.parameter.enum import HonParameterEnum
from pyhon.parameter.range import HonParameterRange
from pytest_homeassistant.common import MockConfigEntry

from custom_components.hon.climate import HonACClimateEntity, HonClimateEntity
from custom_components.hon.const import DOMAIN

from .conftest import FakeAppliance, FakeHon

# Renamed with a native_ prefix in Home Assistant 2026.11; the old names
# stop working in 2027.11
DEPRECATED = {
    "current_temperature",
    "target_temperature",
    "target_temperature_high",
    "target_temperature_low",
    "temperature_unit",
}


def temperature_range(key: str, minimum: str, maximum: str) -> HonParameterRange:
    return HonParameterRange(
        key,
        {"minimumValue": minimum, "maximumValue": maximum, "incrementValue": "1"},
        "parameters",
    )


def choice(key: str, values: list[str]) -> HonParameterEnum:
    return HonParameterEnum(key, {"enumValues": values}, "parameters")


def make_fridge() -> FakeAppliance:
    fridge = FakeAppliance(
        "REF", {"tempSelZ1": 4, "tempZ1": 5, "settings": {"tempSelZ1": 4}}
    )
    fridge.settings["settings.tempSelZ1"] = temperature_range("tempSelZ1", "2", "8")
    fridge.available_settings.append("settings.tempSelZ1")
    fridge.commands["startProgram"] = SimpleNamespace(categories={})
    fridge.commands["settings"] = MagicMock(send=AsyncMock())
    return fridge


def make_air_conditioner() -> FakeAppliance:
    air_conditioner = FakeAppliance(
        "AC",
        {
            "tempSel": 22,
            "tempIndoor": 24.5,
            "onOffStatus": 1,
            "machMode": 1,
            "windSpeed": 3,
            "windDirectionHorizontal": 0,
            "windDirectionVertical": 5,
        },
    )
    air_conditioner.settings["settings.tempSel"] = temperature_range(
        "tempSel", "16", "30"
    )
    air_conditioner.settings["settings.machMode"] = choice("machMode", ["0", "1"])
    air_conditioner.settings["startProgram.program"] = choice(
        "program", ["iot_auto", "iot_cool"]
    )
    air_conditioner.settings["settings.windSpeed"] = choice(
        "windSpeed", ["1", "2", "3"]
    )
    air_conditioner.commands["settings"] = MagicMock(send=AsyncMock())
    return air_conditioner


async def set_up(
    hass: HomeAssistant, config_entry: MockConfigEntry, unique_id: str
) -> State:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    entity_id = er.async_get(hass).async_get_entity_id("climate", DOMAIN, unique_id)
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    return state


@pytest.mark.parametrize("entity_class", [HonACClimateEntity, HonClimateEntity])
def test_no_deprecated_temperature_names(entity_class: type) -> None:
    names = DEPRECATED | {f"_attr_{name}" for name in DEPRECATED}
    for klass in entity_class.__mro__:
        if klass.__module__.startswith("custom_components."):
            assert names.isdisjoint(vars(klass)), klass


async def test_fridge_temperatures(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    appliances: list[FakeAppliance],
    caplog: pytest.LogCaptureFixture,
) -> None:
    appliances.append(make_fridge())
    state = await set_up(hass, config_entry, "ref_testsettings.tempSelZ1")

    assert state.state == "cool"
    assert state.attributes["temperature"] == 4
    assert state.attributes["current_temperature"] == 5
    assert state.attributes["temperature_unit"] == "°C"
    assert state.attributes["min_temp"] == 2
    assert state.attributes["max_temp"] == 8
    assert "deprecated" not in caplog.text


async def test_fridge_temperatures_in_fahrenheit(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    appliances: list[FakeAppliance],
) -> None:
    # The fridge reports Celsius; Home Assistant converts to the user's units
    hass.config.units = US_CUSTOMARY_SYSTEM
    appliances.append(make_fridge())
    state = await set_up(hass, config_entry, "ref_testsettings.tempSelZ1")

    assert state.attributes["temperature"] == 39
    assert state.attributes["current_temperature"] == 41
    assert state.attributes["temperature_unit"] == "°F"


async def test_air_conditioner_temperatures(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    appliances: list[FakeAppliance],
    caplog: pytest.LogCaptureFixture,
) -> None:
    air_conditioner = make_air_conditioner()
    appliances.append(air_conditioner)
    state = await set_up(hass, config_entry, "ac_testsettings")

    assert state.state == "cool"
    assert state.attributes["temperature"] == 22
    assert state.attributes["current_temperature"] == 24.5
    assert state.attributes["temperature_unit"] == "°C"

    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": state.entity_id, "temperature": 21},
        blocking=True,
    )
    assert air_conditioner.settings["settings.tempSel"].value == 21
    air_conditioner.commands["settings"].send.assert_awaited_once()
    assert "deprecated" not in caplog.text
