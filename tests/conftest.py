"""Shared fixtures for the hOn integration tests."""

from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ContentTypeError, RequestInfo
from multidict import CIMultiDict, CIMultiDictProxy
from pytest_homeassistant_custom_component.common import MockConfigEntry
from yarl import URL

from custom_components.hon.const import DOMAIN

EMAIL = "user@example.com"
PASSWORD = "hunter2"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components."""


class FakeAppliance:
    """The parts of pyhon's HonAppliance that the platforms read."""

    def __init__(self, appliance_type: str, data: dict[str, Any]) -> None:
        self.appliance_type = appliance_type
        self.unique_id = f"{appliance_type.lower()}_test"
        self.nick_name = appliance_type.lower()
        self.model_name = "Test model"
        self.model_id = 1
        self.connection = True
        self.settings: dict[str, Any] = {}
        self.commands: dict[str, Any] = {}
        self.available_settings: list[str] = []
        self.data = data
        self.api = MagicMock()
        # Read by the device info and data archive exports
        self.info: dict[str, Any] = {}
        self.attributes: dict[str, Any] = {}
        self.statistics: dict[str, Any] = {}
        self.additional_data: dict[str, Any] = {}

    def get(self, item: str, default: Any = None) -> Any:
        return self.data.get(item, default)


class FakeHon:
    """Stands in for pyhon's Hon so no hOn cloud connection is made."""

    def __init__(self, appliances: list[FakeAppliance]) -> None:
        self.appliances = appliances
        self.api = MagicMock()
        self.api.auth.refresh_token = "refresh-token"
        self.notify: Callable[[Any], None] | None = None
        self.mqtt_client = MagicMock()
        self.close = AsyncMock()
        self.create_error: BaseException | None = None

    @property
    def _mqtt_client(self) -> MagicMock:
        return self.mqtt_client

    async def create(self) -> "FakeHon":
        if self.create_error is not None:
            raise self.create_error
        return self

    def subscribe_updates(self, notify: Callable[[Any], None]) -> None:
        self.notify = notify


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=EMAIL,
        unique_id=EMAIL,
        data={"email": EMAIL, "password": PASSWORD},
    )


@pytest.fixture
def appliances() -> list[FakeAppliance]:
    """Appliances on the fake account; tests replace or extend the list."""
    return []


@pytest.fixture
def fake_hon(appliances: list[FakeAppliance]) -> Iterator[FakeHon]:
    hon = FakeHon(appliances)
    with patch("custom_components.hon.Hon", return_value=hon):
        yield hon


def login_url_error() -> ContentTypeError:
    """An aiohttp error whose message contains the hOn login URL."""
    url = URL(
        f"https://api.example/ciam/authorize?username={EMAIL}&password={PASSWORD}"
    )
    info = RequestInfo(url, "GET", CIMultiDictProxy(CIMultiDict()), url)
    return ContentTypeError(info, (), message="unexpected mimetype: text/html")
