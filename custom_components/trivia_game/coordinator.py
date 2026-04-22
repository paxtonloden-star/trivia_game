from __future__ import annotations

import secrets
import string
from typing import Any

from aiohttp import web
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_DEFAULT_ANSWER_SECONDS,
    CONF_DEFAULT_AUTO_NEXT,
    CONF_DEFAULT_REVEAL_SECONDS,
    CONF_REMOTE_BASE_URL,
    DEFAULT_ANSWER_SECONDS,
    DEFAULT_AUTO_NEXT,
    DEFAULT_REVEAL_SECONDS,
    DEFAULT_REMOTE_BASE_URL,
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
    WS_EVENT_STATE,
)

_ALPHABET = string.ascii_uppercase + string.digits


class TriviaGameCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, None, name=DOMAIN)
        self.entry = entry
        self.store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.base_url = ""
        self.join_code = self._generate_join_code()
        self.players: list[dict[str, Any]] = []
        self.question: dict[str, Any] = {}
        self.answer_seconds = DEFAULT_ANSWER_SECONDS
        self.reveal_seconds = DEFAULT_REVEAL_SECONDS
        self.auto_next = DEFAULT_AUTO_NEXT
        self.state = "idle"
        self._sockets: set[web.WebSocketResponse] = set()
        self.data = self.as_dict()

    async def async_load(self) -> None:
        saved = await self.store.async_load() or {}
        self.base_url = str(saved.get("base_url", "")).rstrip("/")
        self.join_code = saved.get("join_code") or self._generate_join_code()
        self.players = list(saved.get("players", []))
        self.question = dict(saved.get("question", {}))
        self.answer_seconds = int(saved.get("answer_seconds", DEFAULT_ANSWER_SECONDS))
        self.reveal_seconds = int(saved.get("reveal_seconds", DEFAULT_REVEAL_SECONDS))
        self.auto_next = bool(saved.get("auto_next", DEFAULT_AUTO_NEXT))
        self.state = str(saved.get("state", "idle"))
        self.data = self.as_dict()

    async def async_apply_options(self, options: dict[str, Any]) -> None:
        self.base_url = str(options.get(CONF_REMOTE_BASE_URL, self.base_url or DEFAULT_REMOTE_BASE_URL)).rstrip("/")
        self.answer_seconds = int(options.get(CONF_DEFAULT_ANSWER_SECONDS, self.answer_seconds))
        self.reveal_seconds = int(options.get(CONF_DEFAULT_REVEAL_SECONDS, self.reveal_seconds))
        self.auto_next = bool(options.get(CONF_DEFAULT_AUTO_NEXT, self.auto_next))
        await self.async_save()

    async def async_save(self) -> None:
        self.data = self.as_dict()
        await self.store.async_save(
            {
                "base_url": self.base_url,
                "join_code": self.join_code,
                "players": self.players,
                "question": self.question,
                "answer_seconds": self.answer_seconds,
                "reveal_seconds": self.reveal_seconds,
                "auto_next": self.auto_next,
                "state": self.state,
            }
        )
        await self.async_broadcast_state()

    def as_dict(self) -> dict[str, Any]:
        return {
            "join_code": self.join_code,
            "join_url": self.join_url,
            "players": self.players,
            "question": self.question,
            "answer_seconds": self.answer_seconds,
            "reveal_seconds": self.reveal_seconds,
            "auto_next": self.auto_next,
            "state": self.state,
        }

    @property
    def join_url(self) -> str:
        if not self.base_url:
            return f"/local/{DOMAIN}/player.html?join={self.join_code}"
        return f"{self.base_url}/local/{DOMAIN}/player.html?join={self.join_code}"

    async def async_register_socket(self, ws: web.WebSocketResponse) -> None:
        self._sockets.add(ws)
        await ws.send_json({"event": WS_EVENT_STATE, "state": self.as_dict()})

    async def async_unregister_socket(self, ws: web.WebSocketResponse) -> None:
        self._sockets.discard(ws)

    async def async_broadcast_state(self) -> None:
        dead: list[web.WebSocketResponse] = []
        for ws in self._sockets:
            try:
                await ws.send_json({"event": WS_EVENT_STATE, "state": self.as_dict()})
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._sockets.discard(ws)

    def _generate_join_code(self) -> str:
        return "".join(secrets.choice(_ALPHABET) for _ in range(6))
