import asyncio
import json
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry
from pyhon.appliance import HonAppliance

from .const import DOMAIN
from .export import TOPICS, anonymize_json, load_topics


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    hon = hass.data[DOMAIN][entry.unique_id]["hon"]
    return {
        "appliances": [
            await _async_appliance_data(appliance) for appliance in hon.appliances
        ]
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    hon = hass.data[DOMAIN][entry.unique_id]["hon"]
    for appliance in hon.appliances:
        if (DOMAIN, appliance.unique_id) in device.identifiers:
            return await _async_appliance_data(appliance)
    return {}


async def _async_appliance_data(appliance: HonAppliance) -> dict[str, Any]:
    # The data of the "Create Data Archive" zip, in one file
    results = await asyncio.gather(*load_topics(appliance), return_exceptions=True)
    data: dict[str, Any] = {
        "appliance_type": appliance.appliance_type,
        "model_id": appliance.model_id,
    }
    for topic, result in zip(TOPICS, results):
        if isinstance(result, BaseException):
            result = f"error: {type(result).__name__}"
        data[topic] = result
    try:
        anonymized: dict[str, Any] = json.loads(anonymize_json(data))
    except ValueError:
        return {"error": "anonymization failed"}
    return anonymized
