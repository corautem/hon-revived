"""Tests for the anonymized exports and the data archive download."""

import io
import json
import re
import zipfile
from datetime import timedelta
from http import HTTPStatus
from typing import Any
from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.hon.const import DOMAIN
from custom_components.hon.export import (
    TOPICS,
    anonymize_json,
    async_data_archive,
    device_info,
)

from .conftest import FakeAppliance, FakeHon

# Made-up values in the shape of an oven's appliance data
ACCOUNT_NUMBER = "001R200000AbcDEfGHI"
APPLIANCE_INFO: dict[str, Any] = {
    "PK": "user#eu-west-1:12345678-aaaa-bbbb-cccc-1234567890ab",
    "SK": "app#aa-bb-cc-dd-ee-ff",
    "macAddress": "aa-bb-cc-dd-ee-ff",
    "modelName": "H6 ID25L5YTX",
    "nickName": "Kitchen oven",
    "sfPersonAccountId": ACCOUNT_NUMBER,
    "camera": {
        "attributes": [
            {"parName": "fwLabel", "parValue": "iotfw_cew"},
            {"parName": "userId", "parValue": ACCOUNT_NUMBER},
        ],
        "macAddress": "11-22-33-44-55-66",
    },
}
COMMAND_HISTORY = {"command": {"device": {"mobileId": "0123456789abcdef"}}}
# The customer number under a key the export doesn't list
LAST_COMMAND = {"lastCommand": {"ownerRef": ACCOUNT_NUMBER}}
PERSONAL_VALUES = (
    "12345678-aaaa",
    "aa-bb-cc-dd-ee-ff",
    "11-22-33-44-55-66",
    "Kitchen oven",
    ACCOUNT_NUMBER,
    "0123456789abcdef",
)


def oven_with_data() -> FakeAppliance:
    oven = FakeAppliance("OV", {})
    oven.info = APPLIANCE_INFO
    oven.attributes = {
        "commandHistory": COMMAND_HISTORY,
        "parameters": {},
        **LAST_COMMAND,
    }
    data = {
        "appliance_data": APPLIANCE_INFO,
        "attributes": LAST_COMMAND,
        "command_history": COMMAND_HISTORY,
    }
    for topic in TOPICS:
        loader = AsyncMock(return_value=data.get(topic, {"temp": "180"}))
        setattr(oven.api, f"load_{topic}", loader)
    return oven


def assert_anonymized(text: str) -> None:
    for value in PERSONAL_VALUES:
        assert value not in text
    assert "H6 ID25L5YTX" in text
    assert "iotfw_cew" in text


def test_json_export_masks_personal_values() -> None:
    text = anonymize_json(APPLIANCE_INFO)

    assert_anonymized(text)
    data = json.loads(text)
    assert data["sfPersonAccountId"] == "111X111111XxxXXxXXX"
    assert data["camera"]["attributes"][1]["parValue"] == "111X111111XxxXXxXXX"


def test_device_info_masks_personal_values() -> None:
    assert_anonymized(device_info(oven_with_data()))


async def test_data_archive_layout() -> None:
    content = await async_data_archive(oven_with_data())

    archive = zipfile.ZipFile(io.BytesIO(content))
    assert sorted(archive.namelist()) == sorted(f"{topic}.json" for topic in TOPICS)
    for name in archive.namelist():
        json.loads(archive.read(name))
    assert_anonymized(archive.read("appliance_data.json").decode())
    assert "0123456789abcdef" not in archive.read("command_history.json").decode()
    assert ACCOUNT_NUMBER not in archive.read("attributes.json").decode()


async def test_data_archive_link_is_signed_and_expires(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_hon: FakeHon,
    appliances: list[FakeAppliance],
    entity_registry: er.EntityRegistry,
    hass_client_no_auth: ClientSessionGenerator,
    freezer: FrozenDateTimeFactory,
) -> None:
    appliances.append(oven_with_data())
    entity_registry.async_get_or_create(
        "button",
        DOMAIN,
        "ov_test_create_data_archive",
        suggested_object_id="ov_create_data_archive",
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    notification = "custom_components.hon.button.persistent_notification.async_create"
    with patch(notification) as create:
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.ov_create_data_archive"},
            blocking=True,
        )
    match = re.search(r'href="([^"]+)"', create.call_args.args[1])
    assert match is not None
    link = match.group(1)
    assert link.startswith("/api/hon/data_archive/")

    client = await hass_client_no_auth()
    response = await client.get(link)
    assert response.status == HTTPStatus.OK
    assert response.headers["Content-Disposition"] == 'attachment; filename="ov_1.zip"'
    archive = zipfile.ZipFile(io.BytesIO(await response.read()))
    assert_anonymized(archive.read("appliance_data.json").decode())

    unsigned = await client.get(link.split("?")[0])
    assert unsigned.status == HTTPStatus.UNAUTHORIZED

    freezer.tick(timedelta(minutes=11))
    expired = await client.get(link)
    assert expired.status == HTTPStatus.UNAUTHORIZED
