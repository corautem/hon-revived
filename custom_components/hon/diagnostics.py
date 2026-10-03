import asyncio
import json
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry
from pyhon.appliance import HonAppliance
from pyhon.diagnose import anonymize_data

from .const import DOMAIN

TO_REDACT = {
    "code",
    "coords",
    "email",
    "lat",
    "lng",
    "macAddress",
    "mobileId",
    "nickName",
    "PK",
    "serialNumber",
    "SK",
}

# The same API data the former "Create Data Archive" button collected
TOPICS = (
    "commands",
    "attributes",
    "command_history",
    "statistics",
    "maintenance",
    "appliance_data",
)


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
    results = await asyncio.gather(
        *(getattr(appliance.api, f"load_{topic}")(appliance) for topic in TOPICS),
        return_exceptions=True,
    )
    data: dict[str, Any] = {
        "appliance_type": appliance.appliance_type,
        "model_id": appliance.model_id,
    }
    for topic, result in zip(TOPICS, results):
        if isinstance(result, BaseException):
            result = f"error: {type(result).__name__}"
        data[topic] = result
    # pyhon's anonymizer also masks MAC addresses and timestamps inside values
    try:
        data = json.loads(anonymize_data(json.dumps(data, indent=4)))
    except ValueError:
        return {"error": "anonymization failed"}
    redacted: dict[str, Any] = async_redact_data(data, TO_REDACT)
    return redacted
