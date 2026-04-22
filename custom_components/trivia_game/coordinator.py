from __future__ import annotations

import asyncio
import secrets
import string
import time
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
        self.question_queue: list[dict[str, Any]] = []
        self.custom_packs: dict[str, dict[str, Any]] = {}
        self.answer_seconds = DEFAULT_ANSWER_SECONDS
        self.reveal_seconds = DEFAULT_REVEAL_SECONDS
        self.auto_next = DEFAULT_AUTO_NEXT
        self.state = "idle"
        self.current_answers: dict[str, int] = {}
        self.timer_ends_at: float | None = None
        self.round_number = 0
        self.last_result: dict[str, Any] = {}
        self._sockets: set[web.WebSocketResponse] = set()
        self._round_task: asyncio.Task | None = None
        self.data = self.as_dict()

    async def async_load(self) -> None:
        saved = await self.store.async_load() or {}
        self.base_url = str(saved.get("base_url", "")).rstrip("/")
        self.join_code = saved.get("join_code") or self._generate_join_code()
        self.players = list(saved.get("players", []))
        self.question = dict(saved.get("question", {}))
        self.question_queue = [dict(item) for item in saved.get("question_queue", []) if isinstance(item, dict)]
        saved_packs = dict(saved.get("custom_packs", {}))
        self.custom_packs = {
            str(slug): {
                "slug": str(pack.get("slug") or slug),
                "name": str(pack.get("name") or slug),
                "description": str(pack.get("description") or ""),
                "questions": [self._normalize_question(item) for item in pack.get("questions", []) if self._is_question_like(item)],
            }
            for slug, pack in saved_packs.items()
            if isinstance(pack, dict)
        }
        self.answer_seconds = int(saved.get("answer_seconds", DEFAULT_ANSWER_SECONDS))
        self.reveal_seconds = int(saved.get("reveal_seconds", DEFAULT_REVEAL_SECONDS))
        self.auto_next = bool(saved.get("auto_next", DEFAULT_AUTO_NEXT))
        self.state = str(saved.get("state", "idle"))
        self.current_answers = {str(k): int(v) for k, v in dict(saved.get("current_answers", {})).items()}
        timer_ends_at = saved.get("timer_ends_at")
        self.timer_ends_at = float(timer_ends_at) if timer_ends_at else None
        self.round_number = int(saved.get("round_number", 0))
        self.last_result = dict(saved.get("last_result", {}))
        self.data = self.as_dict()
        self._sync_round_task()

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
                "question_queue": self.question_queue,
                "custom_packs": self.custom_packs,
                "answer_seconds": self.answer_seconds,
                "reveal_seconds": self.reveal_seconds,
                "auto_next": self.auto_next,
                "state": self.state,
                "current_answers": self.current_answers,
                "timer_ends_at": self.timer_ends_at,
                "round_number": self.round_number,
                "last_result": self.last_result,
            }
        )
        self._sync_round_task()
        await self.async_broadcast_state()

    def as_dict(self) -> dict[str, Any]:
        return {
            "join_code": self.join_code,
            "join_url": self.join_url,
            "qr_url": f"/api/{DOMAIN}/join_qr.svg",
            "players": self.players,
            "question": self.question,
            "question_queue": self.question_queue,
            "queue_count": len(self.question_queue),
            "custom_packs": self._pack_summaries(),
            "answer_seconds": self.answer_seconds,
            "reveal_seconds": self.reveal_seconds,
            "auto_next": self.auto_next,
            "state": self.state,
            "current_answers": self.current_answers,
            "timer_ends_at": self.timer_ends_at,
            "round_number": self.round_number,
            "last_result": self.last_result,
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

    async def async_join_player(self, name: str, picture: str = "") -> dict[str, Any]:
        clean = str(name or "").strip()
        if not clean:
            raise ValueError("Player name is required")
        existing = self._find_player(clean)
        if existing is None:
            self.players.append({"name": clean, "score": 0, "picture": str(picture or "").strip()})
        elif picture:
            existing["picture"] = str(picture).strip()
        await self.async_save()
        return self.as_dict()

    async def async_remove_player(self, name: str) -> None:
        clean = str(name or "").strip().lower()
        self.players = [player for player in self.players if str(player.get("name", "")).strip().lower() != clean]
        self.current_answers = {
            player_name: answer for player_name, answer in self.current_answers.items() if player_name.strip().lower() != clean
        }
        await self.async_save()

    async def async_set_settings(self, answer_seconds: int | None = None, reveal_seconds: int | None = None, auto_next: bool | None = None) -> None:
        if answer_seconds is not None:
            self.answer_seconds = max(3, int(answer_seconds))
        if reveal_seconds is not None:
            self.reveal_seconds = max(1, int(reveal_seconds))
        if auto_next is not None:
            self.auto_next = bool(auto_next)
        await self.async_save()

    async def async_set_question(self, payload: dict[str, Any]) -> None:
        self.question = self._normalize_question(payload)
        self.last_result = {}
        await self.async_save()

    async def async_import_pack(self, payload: dict[str, Any]) -> dict[str, Any]:
        slug = self._slugify(str(payload.get("slug") or payload.get("name") or "").strip())
        if not slug:
            raise ValueError("Pack name is required")
        name = str(payload.get("name") or slug.replace("_", " ").title()).strip()
        description = str(payload.get("description") or "").strip()
        questions = [
            self._normalize_question(item)
            for item in payload.get("questions", [])
            if self._is_question_like(item)
        ]
        if not questions:
            raise ValueError("Pack must contain at least one valid question")
        self.custom_packs[slug] = {
            "slug": slug,
            "name": name,
            "description": description,
            "questions": questions,
        }
        await self.async_save()
        return {"slug": slug, "name": name, "description": description, "question_count": len(questions)}

    async def async_load_pack_to_queue(self, slug: str, count: int | None = None, replace_queue: bool = False) -> None:
        clean_slug = self._slugify(slug)
        pack = self.custom_packs.get(clean_slug)
        if not pack:
            raise ValueError("Unknown pack")
        questions = [dict(item) for item in pack.get("questions", [])]
        limit = max(1, int(count or len(questions)))
        batch = questions[:limit]
        if replace_queue:
            self.question_queue = batch
        else:
            self.question_queue.extend(batch)
        if not self.question.get("question") and self.question_queue:
            self.question = dict(self.question_queue.pop(0))
        await self.async_save()

    async def async_queue_question(self, payload: dict[str, Any]) -> None:
        self.question_queue.append(self._normalize_question(payload))
        await self.async_save()

    async def async_next_question(self) -> None:
        self._cancel_round_task()
        self.state = "idle"
        self.current_answers = {}
        self.timer_ends_at = None
        self.last_result = {}
        if self.question_queue:
            self.question = dict(self.question_queue.pop(0))
        else:
            self.question = {}
        await self.async_save()

    async def async_start_round(self) -> None:
        if not self.question.get("question"):
            if self.question_queue:
                self.question = dict(self.question_queue.pop(0))
            else:
                raise ValueError("Set or queue a question first")
        self.state = "submitting"
        self.round_number += 1
        self.current_answers = {}
        self.last_result = {}
        self.timer_ends_at = time.time() + max(3, int(self.answer_seconds))
        await self.async_save()

    async def async_submit_answer(self, player_name: str, choice_index: int) -> None:
        if self.state != "submitting":
            raise ValueError("Round is not open")
        player = self._find_player(player_name)
        if player is None:
            raise ValueError("Unknown player")
        choices = list(self.question.get("choices", []))
        if choice_index < 0 or choice_index >= len(choices):
            raise ValueError("Invalid answer choice")
        self.current_answers[str(player["name"])] = int(choice_index)
        if self.players and len(self.current_answers) >= len(self.players):
            await self.async_grade_round()
            return
        await self.async_save()

    async def async_grade_round(self) -> None:
        if not self.question.get("question"):
            raise ValueError("No active question")
        correct_index = int(self.question.get("correct_index", 0))
        correct_players: list[str] = []
        results: list[dict[str, Any]] = []
        for player in self.players:
            name = str(player.get("name", ""))
            answer_index = self.current_answers.get(name)
            answer_text = None
            if answer_index is not None and 0 <= answer_index < len(self.question.get("choices", [])):
                answer_text = self.question["choices"][answer_index]
            is_correct = answer_index == correct_index
            if is_correct:
                player["score"] = int(player.get("score", 0)) + 1
                correct_players.append(name)
            results.append({
                "player": name,
                "answer_index": answer_index,
                "answer": answer_text,
                "correct": is_correct,
            })
        self.state = "results"
        self.timer_ends_at = None
        self.last_result = {
            "correct_players": correct_players,
            "correct_answer": self.question.get("correct_answer"),
            "explanation": self.question.get("explanation", ""),
            "results": results,
            "hold_for_manual_next": not bool(correct_players),
        }
        await self.async_save()

    async def async_reset_scores(self) -> None:
        for player in self.players:
            player["score"] = 0
        self.last_result = {}
        await self.async_save()

    async def async_clear_round(self) -> None:
        self._cancel_round_task()
        self.state = "idle"
        self.current_answers = {}
        self.timer_ends_at = None
        self.last_result = {}
        await self.async_save()

    def _find_player(self, name: str) -> dict[str, Any] | None:
        clean = str(name or "").strip().lower()
        for player in self.players:
            if str(player.get("name", "")).strip().lower() == clean:
                return player
        return None

    def _cancel_round_task(self) -> None:
        task = self._round_task
        if task and not task.done():
            task.cancel()
        self._round_task = None

    def _sync_round_task(self) -> None:
        self._cancel_round_task()
        if self.state == "submitting" and self.timer_ends_at:
            self._round_task = self.hass.async_create_task(self._async_wait_for_timeout(self.round_number, self.timer_ends_at))
        elif (
            self.state == "results"
            and self.auto_next
            and self.reveal_seconds > 0
            and not bool(self.last_result.get("hold_for_manual_next"))
        ):
            self._round_task = self.hass.async_create_task(self._async_wait_for_next_round(self.round_number, self.reveal_seconds))

    async def _async_wait_for_timeout(self, round_number: int, timer_ends_at: float) -> None:
        try:
            await asyncio.sleep(max(0.0, timer_ends_at - time.time()))
            if self.state == "submitting" and self.round_number == round_number:
                await self.async_grade_round()
        except asyncio.CancelledError:
            raise
        finally:
            if asyncio.current_task() is self._round_task:
                self._round_task = None

    async def _async_wait_for_next_round(self, round_number: int, seconds: int) -> None:
        try:
            await asyncio.sleep(max(0, int(seconds)))
            if self.state == "results" and self.round_number == round_number and not bool(self.last_result.get("hold_for_manual_next")):
                if self.question_queue:
                    await self.async_next_question()
                else:
                    await self.async_clear_round()
        except asyncio.CancelledError:
            raise
        finally:
            if asyncio.current_task() is self._round_task:
                self._round_task = None

    def _is_question_like(self, value: Any) -> bool:
        return isinstance(value, dict) and bool(str(value.get("question") or "").strip())

    def _normalize_question(self, payload: dict[str, Any]) -> dict[str, Any]:
        question_text = str(payload.get("question") or "").strip()
        choices = [str(choice).strip() for choice in payload.get("choices", []) if str(choice).strip()]
        if not question_text:
            raise ValueError("Question text is required")
        if len(choices) < 2:
            raise ValueError("At least two answers are required")
        correct_index = int(payload.get("correct_index", 0))
        if correct_index < 0 or correct_index >= len(choices):
            raise ValueError("Correct answer is out of range")
        return {
            "question": question_text,
            "choices": choices,
            "correct_index": correct_index,
            "correct_answer": choices[correct_index],
            "category": str(payload.get("category") or "").strip(),
            "explanation": str(payload.get("explanation") or "").strip(),
        }

    def _slugify(self, value: str) -> str:
        clean = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "").strip())
        while "__" in clean:
            clean = clean.replace("__", "_")
        return clean.strip("_")[:64]

    def _pack_summaries(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for slug, pack in self.custom_packs.items():
            summaries.append({
                "slug": slug,
                "name": str(pack.get("name") or slug),
                "description": str(pack.get("description") or ""),
                "question_count": len(pack.get("questions", [])),
            })
        summaries.sort(key=lambda item: item["name"].lower())
        return summaries

    def _generate_join_code(self) -> str:
        return "".join(secrets.choice(_ALPHABET) for _ in range(6))
