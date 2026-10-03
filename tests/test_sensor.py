"""Tests for hOn sensor and binary sensor entities."""

import pytest
from homeassistant.const import PERCENTAGE, STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hon.const import DOMAIN

from .conftest import FakeAppliance, FakeHon


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def push_update(hass: HomeAssistant, fake_hon: FakeHon) -> None:
    assert fake_hon.notify is not None
    fake_hon.notify(None)
    # One loop pass runs the coordinator update, the next one the state
    # write that schedule_update_ha_state() queues
    await hass.async_block_till_done()
    await hass.async_block_till_done()


@pytest.fixture
def oven(appliances: list[FakeAppliance]) -> FakeAppliance:
    oven = FakeAppliance(
        "OV",
        {
            "tempEmployedProbe1": 55,
            "connectionStatusEmployedProbe1": 1,
            "signalEmployedProbe1": -60,
            "chargeEmployedProbe1": 80,
        },
    )
    appliances.append(oven)
    return oven


async def test_probe_entities(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    oven: FakeAppliance,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)

    assert hass.states.get("binary_sensor.ov_meat_probe_connected").state == STATE_ON
    battery = hass.states.get("sensor.ov_meat_probe_battery")
    assert battery.state == "80"
    assert battery.attributes["unit_of_measurement"] == PERCENTAGE
    assert hass.states.get("sensor.ov_meat_probe_temperature").state == "55"

    signal = entity_registry.async_get("sensor.ov_meat_probe_signal")
    assert signal is not None
    assert signal.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert signal.entity_category == "diagnostic"


async def test_probe_without_reading_is_unknown(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    oven: FakeAppliance,
    entity_registry: er.EntityRegistry,
) -> None:
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "ov_testsignalEmployedProbe1",
        suggested_object_id="ov_meat_probe_signal",
    )
    oven.data.update(
        signalEmployedProbe1=-128,
        chargeEmployedProbe1=0,
        connectionStatusEmployedProbe1=0,
    )
    await setup_integration(hass, config_entry)

    assert hass.states.get("sensor.ov_meat_probe_signal").state == STATE_UNKNOWN
    assert hass.states.get("sensor.ov_meat_probe_battery").state == STATE_UNKNOWN
    assert hass.states.get("binary_sensor.ov_meat_probe_connected").state == STATE_OFF

    oven.data.update(signalEmployedProbe1=-70, connectionStatusEmployedProbe1=1)
    await push_update(hass, fake_hon)
    signal = hass.states.get("sensor.ov_meat_probe_signal")
    assert signal.state == "-70"
    assert signal.attributes["unit_of_measurement"] == "dBm"
    assert hass.states.get("binary_sensor.ov_meat_probe_connected").state == STATE_ON


async def test_unmapped_program_code_is_shown(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    appliances: list[FakeAppliance],
) -> None:
    washer = FakeAppliance("WM", {"prCode": 999})
    appliances.append(washer)
    await setup_integration(hass, config_entry)

    state = hass.states.get("sensor.wm_program_code")
    assert state.state == "999"
    assert "999" in state.attributes["options"]

    washer.data["prCode"] = 115
    await push_update(hass, fake_hon)
    assert hass.states.get("sensor.wm_program_code").state == "cottons"


async def test_empty_value_is_unknown(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    oven: FakeAppliance,
) -> None:
    oven.data["tempEmployedProbe1"] = ""
    await setup_integration(hass, config_entry)

    assert hass.states.get("sensor.ov_meat_probe_temperature").state == STATE_UNKNOWN


async def test_cycle_consumption_is_total_increasing(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    appliances: list[FakeAppliance],
) -> None:
    data = {"currentElectricityUsed": 0.4, "currentWaterUsed": 12}
    appliances.extend([FakeAppliance("WM", data), FakeAppliance("DW", data)])
    await setup_integration(hass, config_entry)

    consumption = [
        state
        for state in hass.states.async_all("sensor")
        if state.attributes.get("device_class") in ("energy", "water", "volume")
    ]
    assert len(consumption) == 4
    for state in consumption:
        assert state.attributes["state_class"] == "total_increasing", state.entity_id


async def test_fridge_zone_without_reading_is_unknown(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    appliances: list[FakeAppliance],
) -> None:
    appliances.append(FakeAppliance("REF", {"tempZ1": -38, "tempZ2": -18}))
    await setup_integration(hass, config_entry)

    assert hass.states.get("sensor.ref_fridge_temperature").state == STATE_UNKNOWN
    assert hass.states.get("sensor.ref_freezer_temperature").state == "-18"
