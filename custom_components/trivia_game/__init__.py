from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import async_register_api
from .const import DOMAIN
from .coordinator import TriviaGameCoordinator

PLATFORMS: list[Platform] = []


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = TriviaGameCoordinator(hass, entry)
    await coordinator.async_load()
    await coordinator.async_apply_options({**entry.data, **entry.options})
    await async_register_api(hass, coordinator)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_apply_options({**entry.data, **entry.options})
