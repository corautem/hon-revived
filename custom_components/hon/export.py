"""Anonymized appliance data: "Show Device Info", "Create Data Archive", diagnostics.

pyhon's anonymizer masks MAC addresses, timestamps and a few keys, and the keys only
where they appear as JSON. It leaves the Haier customer number (sfPersonAccountId,
also sent as principalUserId and as the camera module's userId) in every export, and
in the YAML of "Show Device Info" also the account, phone and appliance names (PK,
mobileId, nickName). Masking the data before it is printed covers both formats, and
masking the same values wherever else they appear covers keys not listed here.
"""

import asyncio
import io
import json
import re
import zipfile
from collections.abc import Awaitable
from datetime import timedelta
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any, cast

from aiohttp import ClientError, web
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pyhon.appliance import HonAppliance
from pyhon.diagnose import anonymize_data, yaml_export

from .const import DOMAIN

# Keys whose values identify the user, the phone or the appliance
PERSONAL_KEYS = frozenset(
    {
        "PK",
        "SK",
        "code",
        "coords",
        "email",
        "lat",
        "lng",
        "mobileId",
        "nickName",
        "principalUserId",
        "serialNumber",
        "sfPersonAccountId",
    }
)
# Names in name/value lists, such as the attributes of the camera module
PERSONAL_PARAMETERS = frozenset({"userId"})
# Shorter personal values, such as a nickname like "Oven", are only masked
# under their key; replacing them everywhere would also change other text
MIN_REPLACED_LENGTH = 8

# The API data in pyhon's data archive, one JSON file each
TOPICS = (
    "commands",
    "attributes",
    "command_history",
    "statistics",
    "maintenance",
    "appliance_data",
)

ARCHIVE_URL = "/api/hon/data_archive/{device_id}"
ARCHIVE_LINK_LIFETIME = timedelta(hours=1)


def _mask(value: Any) -> Any:
    """Keep the shape of a value, as pyhon does: letters become x or X, digits 1."""
    if isinstance(value, dict):
        return {key: _mask(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask(item) for item in value]
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return value
    text = re.sub(r"\d", "1", re.sub("[A-Z]", "X", re.sub("[a-z]", "x", str(value))))
    if isinstance(value, str):
        return text
    try:
        return type(value)(text)
    except ValueError:
        return text


def anonymize(data: Any) -> Any:
    """Return a copy of data with personal values masked."""
    if isinstance(data, dict):
        result = {
            key: _mask(value) if key in PERSONAL_KEYS else anonymize(value)
            for key, value in data.items()
        }
        name = result.get("parName")
        if isinstance(name, str) and name in PERSONAL_PARAMETERS:
            result["parValue"] = _mask(result.get("parValue"))
        return result
    if isinstance(data, list):
        return [anonymize(item) for item in data]
    return data


def personal_values(*data: Any) -> set[str]:
    """The personal values in data that are long enough to mask anywhere."""
    found: set[str] = set()

    def collect(item: Any) -> None:
        if isinstance(item, dict):
            name = item.get("parName")
            if isinstance(name, str) and name in PERSONAL_PARAMETERS:
                found.add(str(item.get("parValue", "")))
            for key, value in item.items():
                if key in PERSONAL_KEYS and isinstance(value, (str, int)):
                    found.add(str(value))
                else:
                    collect(value)
        elif isinstance(item, list):
            for value in item:
                collect(value)

    for item in data:
        collect(item)
    return {value for value in found if len(value) >= MIN_REPLACED_LENGTH}


def mask_values(text: str, values: set[str]) -> str:
    """Mask each of values wherever it appears in text."""
    for value in sorted(values, key=len, reverse=True):
        text = text.replace(value, _mask(value))
    return text


def anonymize_json(data: Any, values: set[str] | None = None) -> str:
    """Indented JSON as in pyhon's archive files, with personal values masked."""
    if values is None:
        values = personal_values(data)
    text = mask_values(json.dumps(anonymize(data), indent=4), values)
    return anonymize_data(text)


def device_info(appliance: HonAppliance) -> str:
    """The text of "Show Device Info": pyhon's YAML export of masked data."""
    parts = (
        appliance.attributes,
        appliance.info,
        appliance.statistics,
        appliance.additional_data,
    )
    masked = SimpleNamespace(
        attributes=anonymize(appliance.attributes),
        info=anonymize(appliance.info),
        statistics=anonymize(appliance.statistics),
        additional_data=anonymize(appliance.additional_data),
        commands=appliance.commands,
    )
    # yaml_export reads only these attributes
    text = yaml_export(cast(HonAppliance, masked), anonymous=True)
    return mask_values(text, personal_values(*parts))


def load_topics(appliance: HonAppliance) -> list[Awaitable[Any]]:
    """Requests for the API data of each topic, in the order of TOPICS."""
    return [getattr(appliance.api, f"load_{topic}")(appliance) for topic in TOPICS]


def archive_name(appliance: HonAppliance) -> str:
    return f"{appliance.appliance_type}_{appliance.model_id}.zip".lower()


async def async_data_archive(appliance: HonAppliance) -> bytes:
    """The zip pyhon's data archive contains, built in memory."""
    results = await asyncio.gather(*load_topics(appliance))
    # A value found in one file, such as the customer number in the appliance
    # data, is masked in the other files too
    values = personal_values(*results)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for topic, data in zip(TOPICS, results):
            archive.writestr(f"{topic}.json", anonymize_json(data, values))
    return buffer.getvalue()


def archive_link(hass: HomeAssistant, device_id: str) -> str:
    """A link to a device's data archive that needs a login and expires."""
    path = ARCHIVE_URL.format(device_id=device_id)
    return async_sign_path(hass, path, ARCHIVE_LINK_LIFETIME)


class HonDataArchiveView(HomeAssistantView):
    """Serve data archives to logged-in users.

    pyhon saves the archive in /config/www, which Home Assistant serves to anyone
    at /local/ without a login.
    """

    url = ARCHIVE_URL
    name = "api:hon:data_archive"
    requires_auth = True

    async def get(self, request: web.Request, device_id: str) -> web.Response:
        hass = request.app[KEY_HASS]
        if (appliance := _find_appliance(hass, device_id)) is None:
            return self.json_message("Unknown appliance", HTTPStatus.NOT_FOUND)
        try:
            content = await async_data_archive(appliance)
        except (ClientError, TimeoutError) as error:
            return self.json_message(
                f"hOn did not send the appliance data ({type(error).__name__})",
                HTTPStatus.BAD_GATEWAY,
            )
        disposition = f'attachment; filename="{archive_name(appliance)}"'
        return web.Response(
            body=content,
            content_type="application/zip",
            headers={"Content-Disposition": disposition},
        )


def _find_appliance(hass: HomeAssistant, device_id: str) -> HonAppliance | None:
    if (device := dr.async_get(hass).async_get(device_id)) is None:
        return None
    for data in hass.data.get(DOMAIN, {}).values():
        for appliance in data["hon"].appliances:
            if (DOMAIN, appliance.unique_id) in device.identifiers:
                return cast(HonAppliance, appliance)
    return None
