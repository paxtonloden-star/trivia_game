from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_DEFAULT_ANSWER_SECONDS,
    CONF_DEFAULT_AUTO_NEXT,
    CONF_DEFAULT_PACK_SOURCE,
    CONF_DEFAULT_REVEAL_SECONDS,
    CONF_REMOTE_BASE_URL,
    DEFAULT_ANSWER_SECONDS,
    DEFAULT_AUTO_NEXT,
    DEFAULT_PACK_SOURCE,
    DEFAULT_REVEAL_SECONDS,
    DEFAULT_REMOTE_BASE_URL,
    DEFAULT_TITLE,
    DOMAIN,
)


class TriviaGameConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return TriviaGameOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title=DEFAULT_TITLE, data=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema({}))


class TriviaGameOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        defaults = {**self._config_entry.data, **self._config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_schema(defaults))


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_REMOTE_BASE_URL, default=defaults.get(CONF_REMOTE_BASE_URL, DEFAULT_REMOTE_BASE_URL)): selector.TextSelector(),
            vol.Optional(CONF_DEFAULT_PACK_SOURCE, default=defaults.get(CONF_DEFAULT_PACK_SOURCE, DEFAULT_PACK_SOURCE)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=["offline_curated", "ai"], mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_DEFAULT_ANSWER_SECONDS, default=defaults.get(CONF_DEFAULT_ANSWER_SECONDS, DEFAULT_ANSWER_SECONDS)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=3, max=120, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_DEFAULT_REVEAL_SECONDS, default=defaults.get(CONF_DEFAULT_REVEAL_SECONDS, DEFAULT_REVEAL_SECONDS)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=60, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_DEFAULT_AUTO_NEXT, default=defaults.get(CONF_DEFAULT_AUTO_NEXT, DEFAULT_AUTO_NEXT)): selector.BooleanSelector(),
        }
    )
