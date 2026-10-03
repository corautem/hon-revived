import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from aiohttp import ClientError
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers import aiohttp_client
from pyhon.connection.api import HonAPI
from pyhon.exceptions import HonAuthenticationError

from .const import CONF_REFRESH_TOKEN, DOMAIN, MOBILE_ID

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str}
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


class HonFlowHandler(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_EMAIL])
            self._abort_if_unique_id_configured()
            error = await self._async_try_login(
                user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if error is None:
                return self.async_create_entry(
                    title=user_input[CONF_EMAIL],
                    data={
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
            errors["base"] = error

        suggested = {CONF_EMAIL: user_input[CONF_EMAIL]} if user_input else None
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, suggested),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await self._async_try_login(
                entry.data[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if error is None:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_REFRESH_TOKEN: "",
                    },
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={CONF_EMAIL: entry.data[CONF_EMAIL]},
            errors=errors,
        )

    async def _async_try_login(self, email: str, password: str) -> str | None:
        """Log in to hOn and return an error key, or None on success."""
        # Own session, so the login does not clear the cookies of a running entry
        session = aiohttp_client.async_create_clientsession(
            self.hass, auto_cleanup=False
        )
        api = HonAPI(
            email=email, password=password, mobile_id=MOBILE_ID, session=session
        )
        try:
            await api.create()
            await api.load_appliances()
        except HonAuthenticationError:
            return "invalid_auth"
        except (ClientError, TimeoutError) as error:
            # Only the type: some messages include the login URL with the password
            _LOGGER.warning("Cannot connect to hOn: %s", type(error).__name__)
            return "cannot_connect"
        except Exception as error:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected hOn login error: %s", type(error).__name__)
            return "unknown"
        finally:
            await api.close()
            session.detach()
        return None
