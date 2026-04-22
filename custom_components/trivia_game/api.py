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
    hass.http.register_view(TriviaBootstrapView(coordinator))
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


class TriviaBootstrapView(BaseTriviaView):
    url = f"/api/{DOMAIN}/bootstrap"
    name = f"api:{DOMAIN}:bootstrap"

    async def get(self, request):
        return self.json({
            "ok": True,
            "state": self.coordinator.as_dict(),
            "tts_providers": await self.coordinator.async_available_tts_providers(),
            "speaker_targets": await self.coordinator.async_available_speakers(),
        })


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
        elif action == "set_tts_settings":
            await self.coordinator.async_set_tts_settings(
                enabled=payload.get("enabled"),
                provider_entity=payload.get("provider_entity"),
                speaker_targets=payload.get("speaker_targets"),
                language=payload.get("language"),
                voice=payload.get("voice"),
                announce_question=payload.get("announce_question"),
                announce_result=payload.get("announce_result"),
                start_timer_after_tts=payload.get("start_timer_after_tts"),
                speech_rate_wpm=payload.get("speech_rate_wpm"),
            )
        elif action == "set_ai_settings":
            await self.coordinator.async_set_ai_settings(
                provider=payload.get("provider"),
                endpoint=payload.get("endpoint"),
                model=payload.get("model"),
                api_key=payload.get("api_key"),
                default_categories=payload.get("default_categories"),
                default_age_range=payload.get("default_age_range"),
                default_question_count=payload.get("default_question_count"),
            )
        elif action == "generate_ai_pack":
            await self.coordinator.async_generate_ai_pack(
                name=str(payload.get("name") or "").strip(),
                categories=payload.get("categories") or [],
                age_range=str(payload.get("age_range") or "").strip(),
                question_count=int(payload.get("question_count", 10)),
                queue_after_generate=bool(payload.get("queue_after_generate", False)),
            )
        elif action == "set_question":
            await self.coordinator.async_set_question(payload)
        elif action == "queue_question":
            await self.coordinator.async_queue_question(payload)
        elif action == "import_pack":
            await self.coordinator.async_import_pack(payload)
        elif action == "load_pack_to_queue":
            await self.coordinator.async_load_pack_to_queue(
                slug=str(payload.get("slug") or "").strip(),
                count=payload.get("count"),
                replace_queue=bool(payload.get("replace_queue", False)),
            )
        elif action == "next_question":
            await self.coordinator.async_next_question()
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
