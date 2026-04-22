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
        self.tts_config: dict[str, Any] = {
            "enabled": False,
            "provider_entity": "",
            "speaker_targets": [],
            "language": "en-US",
            "voice": "",
            "announce_question": True,
            "announce_result": True,
            "start_timer_after_tts": True,
            "speech_rate_wpm": 155,
        }
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
        self.tts_config = {**self.tts_config, **dict(saved.get("tts_config", {}))}
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
                "tts_config": self.tts_config,
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
            "tts": dict(self.tts_config),
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
        elif picture is not None:
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

    async def async_set_tts_settings(
        self,
        *,
        enabled: bool | None = None,
        provider_entity: str | None = None,
        speaker_targets: list[str] | None = None,
        language: str | None = None,
        voice: str | None = None,
        announce_question: bool | None = None,
        announce_result: bool | None = None,
        start_timer_after_tts: bool | None = None,
        speech_rate_wpm: int | None = None,
    ) -> None:
        if enabled is not None:
            self.tts_config["enabled"] = bool(enabled)
        if provider_entity is not None:
            self.tts_config["provider_entity"] = str(provider_entity).strip()
        if speaker_targets is not None:
            self.tts_config["speaker_targets"] = [str(item).strip() for item in speaker_targets if str(item).strip()]
        if language is not None:
            self.tts_config["language"] = str(language).strip() or "en-US"
        if voice is not None:
            self.tts_config["voice"] = str(voice).strip()
        if announce_question is not None:
            self.tts_config["announce_question"] = bool(announce_question)
        if announce_result is not None:
            self.tts_config["announce_result"] = bool(announce_result)
        if start_timer_after_tts is not None:
            self.tts_config["start_timer_after_tts"] = bool(start_timer_after_tts)
        if speech_rate_wpm is not None:
            self.tts_config["speech_rate_wpm"] = max(80, min(260, int(speech_rate_wpm)))
        await self.async_save()

    async def async_available_tts_providers(self) -> list[dict[str, str]]:
        providers: list[dict[str, str]] = []
        try:
            for state in self.hass.states.async_all():
                entity_id = str(getattr(state, "entity_id", "") or "")
                if entity_id.startswith("tts."):
                    providers.append({"entity_id": entity_id, "name": state.attributes.get("friendly_name", entity_id)})
        except Exception:
            providers = []
        current = str(self.tts_config.get("provider_entity") or "").strip()
        if current and not any(item["entity_id"] == current for item in providers):
            providers.append({"entity_id": current, "name": f"{current} (current)"})
        providers.sort(key=lambda item: item["name"].lower())
        return providers

    async def async_available_speakers(self) -> list[dict[str, str]]:
        speakers: list[dict[str, str]] = []
        try:
            for state in self.hass.states.async_all():
                entity_id = str(getattr(state, "entity_id", "") or "")
                if entity_id.startswith("media_player."):
                    speakers.append({"entity_id": entity_id, "name": state.attributes.get("friendly_name", entity_id)})
        except Exception:
            speakers = []
        for entity_id in [str(item).strip() for item in self.tts_config.get("speaker_targets", []) if str(item).strip()]:
            if not any(item["entity_id"] == entity_id for item in speakers):
                speakers.append({"entity_id": entity_id, "name": f"{entity_id} (current)"})
        speakers.sort(key=lambda item: item["name"].lower())
        return speakers

    async def async_speak_text(self, message: str) -> float:
        if not self.tts_config.get("enabled"):
            return 0.0
        provider_entity = str(self.tts_config.get("provider_entity") or "").strip()
        speaker_targets = [str(item).strip() for item in self.tts_config.get("speaker_targets", []) if str(item).strip()]
        if not provider_entity or not speaker_targets or not str(message or "").strip():
            return 0.0
        estimated_seconds = (len(str(message).split()) / max(80, int(self.tts_config.get("speech_rate_wpm", 155)))) * 60.0
        estimated_seconds = max(0.0, min(20.0, estimated_seconds))
        services = getattr(self.hass, "services", None)
        if services and hasattr(services, "async_call"):
            for target in speaker_targets:
                try:
                    await services.async_call(
                        "tts",
                        "speak",
                        {
                            "entity_id": provider_entity,
                            "media_player_entity_id": target,
                            "message": message,
                            "language": self.tts_config.get("language") or "en-US",
                            "options": {"voice": self.tts_config.get("voice") or ""},
                        },
                        blocking=False,
                    )
                except Exception:
                    continue
        return estimated_seconds

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
        self.timer_ends_at = None
        await self.async_save()
        if self.tts_config.get("enabled") and self.tts_config.get("announce_question", True):
            message = self._question_announcement(self.question)
            delay = await self.async_speak_text(message)
            if self.tts_config.get("start_timer_after_tts", True) and delay > 0:
                await asyncio.sleep(delay)
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
        if self.tts_config.get("enabled") and self.tts_config.get("announce_result", True):
            await self.async_speak_text(self._result_announcement(self.last_result))

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

    def _question_announcement(self, question: dict[str, Any]) -> str:
        choices = [str(choice).strip() for choice in question.get("choices", []) if str(choice).strip()]
        choices_text = " ".join(f"{chr(65 + idx)}. {choice}." for idx, choice in enumerate(choices[:6]))
        category = str(question.get("category") or "").strip()
        prefix = f"Category {category}. " if category else ""
        return f"{prefix}{question.get('question', '')} {choices_text}".strip()

    def _result_announcement(self, result: dict[str, Any]) -> str:
        correct_answer = str(result.get("correct_answer") or "").strip()
        winners = [str(item).strip() for item in result.get("correct_players", []) if str(item).strip()]
        explanation = str(result.get("explanation") or "").strip()
        winners_text = f"Winners: {', '.join(winners)}." if winners else "Nobody got it right."
        return f"The correct answer is {correct_answer}. {winners_text} {explanation}".strip()

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
