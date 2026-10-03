import logging
from contextlib import suppress
from pathlib import Path
from typing import Any

from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pyhon import Hon
from pyhon.exceptions import HonAuthenticationError

from .const import DOMAIN, PLATFORMS, MOBILE_ID, CONF_REFRESH_TOKEN

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # A dedicated session keeps the hOn login cookies out of the shared one.
    # Home Assistant detaches it when the entry is unloaded.
    session = aiohttp_client.async_create_clientsession(hass)
    if (config_dir := hass.config.config_dir) is None:
        raise ValueError("Missing Config Dir")
    try:
        hon = await Hon(
            email=entry.data[CONF_EMAIL],
            password=entry.data[CONF_PASSWORD],
            mobile_id=MOBILE_ID,
            session=session,
            test_data_path=Path(config_dir),
            refresh_token=entry.data.get(CONF_REFRESH_TOKEN, ""),
        ).create()
    except HonAuthenticationError as error:
        raise ConfigEntryAuthFailed("hOn rejected the login") from error
    except (ClientError, TimeoutError) as error:
        # Some aiohttp errors include the login URL, which carries the
        # credentials, so only the error type is reported
        raise ConfigEntryNotReady(
            f"Cannot connect to hOn ({type(error).__name__})"
        ) from None

    # Save the new refresh token
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_REFRESH_TOKEN: hon.api.auth.refresh_token}
    )

    coordinator: DataUpdateCoordinator[dict[str, Any]] = DataUpdateCoordinator(
        hass, _LOGGER, config_entry=entry, name=DOMAIN
    )

    def notify(data: Any) -> None:
        # pyhon calls this from the MQTT client thread
        with suppress(RuntimeError):  # the event loop is closed on shutdown
            hass.loop.call_soon_threadsafe(coordinator.async_set_updated_data, data)

    hon.subscribe_updates(notify)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.unique_id] = {"hon": hon, "coordinator": coordinator}

    async def async_stop(_: Event) -> None:
        await async_close_hon(hon)

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_stop)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hon: Hon = hass.data[DOMAIN][entry.unique_id]["hon"]

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_REFRESH_TOKEN: hon.api.auth.refresh_token}
    )
    unload = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload:
        hass.data[DOMAIN].pop(entry.unique_id)
        await async_close_hon(hon)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN, None)
    return unload


async def async_close_hon(hon: Hon) -> None:
    """Stop the MQTT connection and close the hOn API handlers."""
    hon.subscribe_updates(lambda _: None)
    # Hon.close() leaves the MQTT client and its reconnect watchdog running
    # (pyhon-revived 0.19.2), so each reload used to add another connection
    if (mqtt := getattr(hon, "_mqtt_client", None)) is not None:
        if (watchdog := getattr(mqtt, "_watchdog_task", None)) is not None:
            watchdog.cancel()
        if (client := getattr(mqtt, "_client", None)) is not None:
            client.stop()
    await hon.close()
