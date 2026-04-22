from __future__ import annotations

from io import BytesIO

import segno
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import TriviaGameCoordinator


async def async_register_api(hass: HomeAssistant, coordinator: TriviaGameCoordinator) -> None:
    hass.http.register_view(TriviaStateView(coordinator))
    hass.http.register_view(TriviaJoinQrView(coordinator))
    hass.http.register_view(TriviaWsView(coordinator))


class BaseTriviaView(HomeAssistantView):
    requires_auth = False

    def __init__(self, coordinator: TriviaGameCoordinator) -> None:
        self.coordinator = coordinator


class TriviaStateView(BaseTriviaView):
    url = f"/api/{DOMAIN}/state"
    name = f"api:{DOMAIN}:state"

    async def get(self, request):
        return self.json({"ok": True, "state": self.coordinator.as_dict()})


class TriviaJoinQrView(BaseTriviaView):
    url = f"/api/{DOMAIN}/join_qr.svg"
    name = f"api:{DOMAIN}:join_qr"

    async def get(self, request):
        qr = segno.make(self.coordinator.join_url)
        buf = BytesIO()
        qr.save(buf, kind="svg", scale=6, border=2)
        return web.Response(body=buf.getvalue(), content_type="image/svg+xml")


class TriviaWsView(BaseTriviaView):
    url = f"/api/{DOMAIN}/ws"
    name = f"api:{DOMAIN}:ws"

    async def get(self, request):
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        await self.coordinator.async_register_socket(ws)
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT and msg.data == "ping":
                    await ws.send_json({"event": "pong"})
        finally:
            await self.coordinator.async_unregister_socket(ws)
        return ws
