from __future__ import annotations

from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.frontend import async_register_built_in_panel

from .api import async_register_api
from .const import DOMAIN
from .coordinator import TriviaGameCoordinator

PLATFORMS: list[Platform] = []

_STATIC_URL = f"/api/{DOMAIN}/static"
_PANEL_MODULE_URL = f"{_STATIC_URL}/trivia-game-host-panel.js"
_PANEL_URL_PATH = "trivia-game-host"
_PANEL_FRONTEND_DIR = Path(__file__).parent / "frontend"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = TriviaGameCoordinator(hass, entry)
    await coordinator.async_load()
    await coordinator.async_apply_options({**entry.data, **entry.options})
    await async_register_api(hass, coordinator)

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(_STATIC_URL, str(_PANEL_FRONTEND_DIR), cache_headers=False),
        ]
    )

    async_register_built_in_panel(
        hass,
        component_name="custom",
        frontend_url_path=_PANEL_URL_PATH,
        config={"_panel_custom": {"name": "trivia-game-host-panel", "module_url": _PANEL_MODULE_URL}},
        sidebar_title="Trivia Host",
        sidebar_icon="mdi:cards-playing-spade-multiple",
        require_admin=False,
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_apply_options({**entry.data, **entry.options})
