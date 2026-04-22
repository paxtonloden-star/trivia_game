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
    hass.http.register_view(TriviaHostActionView(coordinator))
    hass.http.register_view(TriviaJoinView(coordinator))
    hass.http.register_view(TriviaSubmitAnswerView(coordinator))


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


class TriviaJoinView(BaseTriviaView):
    url = f"/api/{DOMAIN}/join"
    name = f"api:{DOMAIN}:join"

    async def post(self, request):
        payload = await request.json()
        await self.coordinator.async_join_player(
            name=str(payload.get("name") or "").strip(),
            picture=str(payload.get("picture") or "").strip(),
        )
        return self.json({"ok": True, "state": self.coordinator.as_dict()})


class TriviaSubmitAnswerView(BaseTriviaView):
    url = f"/api/{DOMAIN}/submit_answer"
    name = f"api:{DOMAIN}:submit_answer"

    async def post(self, request):
        payload = await request.json()
        await self.coordinator.async_submit_answer(
            player_name=str(payload.get("player_name") or "").strip(),
            choice_index=int(payload.get("choice_index", -1)),
        )
        return self.json({"ok": True, "state": self.coordinator.as_dict()})


class TriviaHostActionView(BaseTriviaView):
    url = f"/api/{DOMAIN}/host_action"
    name = f"api:{DOMAIN}:host_action"

    async def post(self, request):
        payload = await request.json()
        action = str(payload.get("action") or "").strip()

        if action == "set_settings":
            await self.coordinator.async_set_settings(
                answer_seconds=payload.get("answer_seconds"),
                reveal_seconds=payload.get("reveal_seconds"),
                auto_next=payload.get("auto_next"),
            )
        elif action == "set_question":
            await self.coordinator.async_set_question(payload)
        elif action == "start_round":
            await self.coordinator.async_start_round()
        elif action == "grade_round":
            await self.coordinator.async_grade_round()
        elif action == "reset_scores":
            await self.coordinator.async_reset_scores()
        elif action == "clear_round":
            await self.coordinator.async_clear_round()
        elif action == "remove_player":
            await self.coordinator.async_remove_player(str(payload.get("name") or "").strip())
        else:
            raise web.HTTPBadRequest(text=f"Unknown action: {action}")

        return self.json({"ok": True, "state": self.coordinator.as_dict()})
