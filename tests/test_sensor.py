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


# Probe readings of an H6 ID25L5YTX, from its owner's "Show Device Info"
PROBE_COOKING = {
    "connectionStatusEmployedProbe1": 1,
    "tempEmployedProbe1": 26,
    "tempStatusEmployedProbe1": 0,
    "chargeAvailableProbe1": 56,
    "chargeEmployedProbe1": 56,
    "signalAvailableProbe1": 73,
    "signalEmployedProbe1": 73,
}
PROBE_IN_HOLDER = {
    "connectionStatusEmployedProbe1": 0,
    "tempEmployedProbe1": 0,
    "tempStatusEmployedProbe1": 0,
    "chargeAvailableProbe1": 56,
    "chargeEmployedProbe1": 0,
    "signalAvailableProbe1": 52,
    "signalEmployedProbe1": -128,
}


@pytest.fixture
def oven(appliances: list[FakeAppliance]) -> FakeAppliance:
    oven = FakeAppliance("OV", dict(PROBE_COOKING))
    appliances.append(oven)
    return oven


def enable_probe_signal(entity_registry: er.EntityRegistry) -> None:
    """Register the signal sensor, which is disabled by default, as enabled."""
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "ov_testsignalAvailableProbe1",
        suggested_object_id="ov_meat_probe_signal",
    )


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
    assert battery.state == "56"
    assert battery.attributes["unit_of_measurement"] == PERCENTAGE
    assert hass.states.get("sensor.ov_meat_probe_temperature").state == "26"

    signal = entity_registry.async_get("sensor.ov_meat_probe_signal")
    assert signal is not None
    assert signal.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert signal.entity_category == "diagnostic"


async def test_dropped_entities_are_removed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    oven: FakeAppliance,
    entity_registry: er.EntityRegistry,
) -> None:
    config_entry.add_to_hass(hass)
    for platform, unique_id in (
        ("button", "ov_test_create_data_archive"),
        ("binary_sensor", "ov_testtempStatusEmployedProbe1"),
        ("binary_sensor", "ov_testconnectionStatusEmployedProbe1"),
    ):
        entity_registry.async_get_or_create(
            platform, DOMAIN, unique_id, config_entry=config_entry
        )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert not entity_registry.async_get_entity_id(
        "binary_sensor", DOMAIN, "ov_testtempStatusEmployedProbe1"
    )
    for platform, unique_id in (
        # Removed in 0.19.2.4, provided again since 0.19.2.5
        ("button", "ov_test_create_data_archive"),
        ("binary_sensor", "ov_testconnectionStatusEmployedProbe1"),
    ):
        assert entity_registry.async_get_entity_id(platform, DOMAIN, unique_id)


async def test_probe_in_holder(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    oven: FakeAppliance,
    entity_registry: er.EntityRegistry,
) -> None:
    enable_probe_signal(entity_registry)
    oven.data.update(PROBE_IN_HOLDER)
    await setup_integration(hass, config_entry)

    assert hass.states.get("sensor.ov_meat_probe_battery").state == "56"
    signal = hass.states.get("sensor.ov_meat_probe_signal")
    assert signal.state == "52"
    assert "unit_of_measurement" not in signal.attributes
    assert hass.states.get("sensor.ov_meat_probe_temperature").state == STATE_UNKNOWN
    assert hass.states.get("binary_sensor.ov_meat_probe_connected").state == STATE_OFF

    oven.data.update(PROBE_COOKING)
    await push_update(hass, fake_hon)
    assert hass.states.get("sensor.ov_meat_probe_signal").state == "73"
    assert hass.states.get("sensor.ov_meat_probe_temperature").state == "26"
    assert hass.states.get("binary_sensor.ov_meat_probe_connected").state == STATE_ON


async def test_probe_not_paired_is_unknown(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    oven: FakeAppliance,
    entity_registry: er.EntityRegistry,
) -> None:
    enable_probe_signal(entity_registry)
    # What hon-test-data ov_15146 reports with no probe paired
    oven.data.update(chargeAvailableProbe1=0, signalAvailableProbe1=-128)
    await setup_integration(hass, config_entry)

    assert hass.states.get("sensor.ov_meat_probe_signal").state == STATE_UNKNOWN
    assert hass.states.get("sensor.ov_meat_probe_battery").state == STATE_UNKNOWN


async def test_probe_temperature_without_connection_status(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    appliances: list[FakeAppliance],
) -> None:
    appliances.append(FakeAppliance("OV", {"tempEmployedProbe1": 0}))
    await setup_integration(hass, config_entry)

    assert hass.states.get("sensor.ov_meat_probe_temperature").state == "0"


async def test_probe_sensors_keep_their_entity_ids(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    oven: FakeAppliance,
    entity_registry: er.EntityRegistry,
) -> None:
    # 0.19.2.1 and 0.19.2.2 used the "Employed" keys for battery and signal
    config_entry.add_to_hass(hass)
    for key, object_id in (
        ("chargeEmployedProbe1", "ov_meat_probe_battery"),
        ("signalEmployedProbe1", "ov_meat_probe_signal"),
    ):
        entity_registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"ov_test{key}",
            suggested_object_id=object_id,
            config_entry=config_entry,
        )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    battery = entity_registry.async_get("sensor.ov_meat_probe_battery")
    assert battery.unique_id == "ov_testchargeAvailableProbe1"
    signal = entity_registry.async_get("sensor.ov_meat_probe_signal")
    assert signal.unique_id == "ov_testsignalAvailableProbe1"
    assert hass.states.get("sensor.ov_meat_probe_battery").state == "56"
    assert hass.states.get("sensor.ov_meat_probe_signal").state == "73"
    assert entity_registry.async_get("sensor.ov_meat_probe_battery_2") is None


async def test_probe_migration_leaves_taken_ids(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    oven: FakeAppliance,
    entity_registry: er.EntityRegistry,
) -> None:
    # Both IDs exist after downgrading from 0.19.2.3 and upgrading again
    config_entry.add_to_hass(hass)
    for key in ("chargeEmployedProbe1", "chargeAvailableProbe1"):
        entity_registry.async_get_or_create(
            "sensor", DOMAIN, f"ov_test{key}", config_entry=config_entry
        )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert entity_registry.async_get_entity_id(
        "sensor", DOMAIN, "ov_testchargeEmployedProbe1"
    )
    battery = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, "ov_testchargeAvailableProbe1"
    )
    assert battery is not None
    assert hass.states.get(battery).state == "56"


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
