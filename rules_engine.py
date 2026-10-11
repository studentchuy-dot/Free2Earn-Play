"""Modelo, persistencia y evaluación independiente de reglas de TikTok."""

from __future__ import annotations

import json
import json
import os
import re
import tempfile
import unicodedata
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

REQUIRED_EVENT_FIELDS = {
    "comment": ("text",),
    "gift": ("gift_name", "amount"),
    "like": ("count",),
}


@dataclass
class Rule:
    id: str
    name: str
    event_type: str
    conditions: dict[str, str]
    action: str
    enabled: bool = True
    action_mode: str = "advanced"
    action_kind: str = "command"
    like_threshold: int = 100
    spawn_count: int = 1
    entity_id: str = "minecraft:zombie"
    repeat_count: int = 1
    repeat_by_amount: bool = False

    @classmethod
    def create(
        cls,
        name: str,
        event_type: str,
        conditions: Mapping[str, str],
        action: str,
        enabled: bool = True,
        action_mode: str = "advanced",
        action_kind: str = "command",
        like_threshold: int = 100,
        spawn_count: int = 1,
        entity_id: str = "minecraft:zombie",
        repeat_count: int = 1,
        repeat_by_amount: bool = False,
    ) -> Rule:
        clean_name = name.strip()
        clean_action = action.strip()
        if not clean_name:
            raise ValueError("La regla necesita un nombre.")
        if not event_type.strip():
            raise ValueError("La regla necesita un tipo de evento.")
        if not clean_action:
            raise ValueError("La regla necesita un comando de Minecraft.")
        if action_mode not in {"blocks", "advanced"}:
            raise ValueError("El modo de acción debe ser blocks o advanced.")
        if action_kind not in {"chat", "spawn", "command"}:
            raise ValueError("El tipo de acción no es válido.")
        if not 1 <= like_threshold <= 1_000_000:
            raise ValueError("El umbral de likes debe estar entre 1 y 1 000 000.")
        if not 1 <= spawn_count <= 64:
            raise ValueError("La cantidad de entidades debe estar entre 1 y 64.")
        if not 1 <= repeat_count <= 64:
            raise ValueError("Las repeticiones deben estar entre 1 y 64.")
        if type(repeat_by_amount) is not bool:
            raise ValueError("repeat_by_amount debe ser booleano.")
        clean_entity_id = entity_id.strip()
        if action_kind == "spawn" and not re.fullmatch(
            r"[a-z0-9_.-]+:[a-z0-9_./-]+", clean_entity_id
        ):
            raise ValueError(
                "La entidad debe usar un identificador como minecraft:zombie."
            )
        clean_conditions = {
            str(key).strip(): str(value).strip()
            for key, value in conditions.items()
            if str(key).strip() and str(value).strip()
        }
        return cls(
            id=str(uuid4()),
            name=clean_name,
            event_type=event_type.strip().lower(),
            conditions=clean_conditions,
            action=clean_action,
            enabled=enabled,
            action_mode=action_mode,
            action_kind=action_kind,
            like_threshold=like_threshold,
            spawn_count=spawn_count,
            entity_id=clean_entity_id,
            repeat_count=repeat_count,
            repeat_by_amount=repeat_by_amount,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Rule:
        repeat_by_amount = data.get("repeat_by_amount", False)
        if type(repeat_by_amount) is not bool:
            raise ValueError(
                "Una regla guardada tiene repeat_by_amount no booleano."
            )
        rule = cls(
            id=str(data["id"]),
            name=str(data["name"]).strip(),
            event_type=str(data["event_type"]).strip().lower(),
            conditions={
                str(key): str(value)
                for key, value in dict(data.get("conditions", {})).items()
            },
            action=str(data["action"]).strip(),
            enabled=bool(data.get("enabled", True)),
            action_mode=str(data.get("action_mode", "advanced")),
            action_kind=str(data.get("action_kind", "command")),
            like_threshold=int(data.get("like_threshold", 100)),
            spawn_count=int(data.get("spawn_count", 1)),
            entity_id=str(data.get("entity_id", "minecraft:zombie")),
            repeat_count=int(data.get("repeat_count", 1)),
            repeat_by_amount=repeat_by_amount,
        )
        if not rule.id or not rule.name or not rule.event_type or not rule.action:
            raise ValueError("Una regla guardada tiene campos obligatorios vacíos.")
        if rule.action_mode not in {"blocks", "advanced"}:
            raise ValueError("Una regla guardada tiene un modo de acción no válido.")
        if rule.action_kind not in {"chat", "spawn", "command"}:
            raise ValueError("Una regla guardada tiene un tipo de acción no válido.")
        if not 1 <= rule.like_threshold <= 1_000_000:
            raise ValueError("Una regla guardada tiene un umbral de likes no válido.")
        if not 1 <= rule.spawn_count <= 64:
            raise ValueError("Una regla guardada tiene una cantidad de entidades no válida.")
        if not 1 <= rule.repeat_count <= 64:
            raise ValueError("Una regla guardada tiene repeticiones no válidas.")
        if rule.action_kind == "spawn" and not re.fullmatch(
            r"[a-z0-9_.-]+:[a-z0-9_./-]+", rule.entity_id
        ):
            raise ValueError("Una regla guardada tiene una entidad no válida.")
        return rule

    def matches(self, event: Mapping[str, Any]) -> bool:
        if not self.enabled or str(event.get("event", "")).lower() != self.event_type:
            return False
        return all(
            str(event.get(field_name, "")).casefold() == expected.casefold()
            for field_name, expected in self.conditions.items()
        )


def render_action_template(action: str, event: Mapping[str, Any]) -> str:
    """Rellena variables conocidas y evita saltos de línea en comandos."""
    values = {
        str(key): ("" if value is None else value)
        for key, value in event.items()
        if isinstance(key, str)
        and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
    }
    values.update({
        "usuario": event.get("user") or event.get("shortname") or "",
        "user": event.get("user") or event.get("shortname") or "",
        "username": event.get("user") or event.get("shortname") or "",
        "shortname": event.get("shortname") or "",
        "userid": event.get("userid") or "",
        "text": event.get("text") or "",
        "gift": event.get("gift_name") or event.get("type") or "",
        "giftname": event.get("gift_name") or event.get("type") or "",
        "gift_name": event.get("gift_name") or "",
        "amount": event.get("amount") or 0,
        "amout": event.get("amount") or 0,
        "type": event.get("type") or event.get("event") or "",
        "count": event.get("count") or event.get("amount") or 0,
        "entity": event.get("entity") or "",
        "player": event.get("player") or "@a",
    })
    rendered = re.sub(
        r"\{([A-Za-z_][A-Za-z0-9_]*)\}",
        lambda match: (
            str(values[match.group(1)])
            if match.group(1) in values
            else match.group(0)
        ),
        action,
    )
    safe_text = "".join(
        character if character >= " " and character != "\x7f" else " "
        for character in rendered
    )
    return re.sub(r"\s+", " ", safe_text).strip()


def render_action_commands(
    action: str, event: Mapping[str, Any]
) -> list[str]:
    """Render each non-empty input line as a separate Minecraft command."""
    return [
        command
        for line in action.splitlines()
        if (command := render_action_template(line, event))
    ]


def render_tellraw_command(
    target: str,
    template: str,
    event: Mapping[str, Any],
    *,
    color: str = "light_purple",
) -> str:
    """Render a safely JSON-escaped Minecraft chat message."""
    if color not in {"light_purple", "dark_purple"}:
        raise ValueError("El color del anuncio debe ser morado.")
    clean_target = target.strip()
    if not clean_target:
        raise ValueError("El anuncio necesita un selector objetivo.")
    message = sanitize_chat_text(render_action_template(template, event))
    if not message:
        raise ValueError("El mensaje del anuncio no puede estar vacío.")
    component = json.dumps(
        {"text": message, "color": color},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"tellraw {clean_target} {component}"


def sanitize_chat_text(text: str) -> str:
    """Remove control/format artifacts while preserving accents and emoji."""
    normalized = unicodedata.normalize("NFC", text)
    invisible_controls = {
        "\u061c",
        "\u200b",
        "\u200e",
        "\u200f",
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2060",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
        "\ufeff",
        "\ufffd",
    }
    visible_characters = []
    for character in normalized:
        if character in invisible_controls or unicodedata.category(character) in {
            "Cc",
            "Cs",
        }:
            visible_characters.append(" ")
        else:
            visible_characters.append(character)
    return re.sub(r"\s+", " ", "".join(visible_characters)).strip()


class RuleStore:
    """Guarda reglas en JSON mediante reemplazo atómico."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def load(self) -> list[Rule]:
        if not self.path.exists():
            return []
        try:
            with self.path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"No se pudieron leer las reglas: {exc}") from exc
        if not isinstance(payload, list):
            raise ValueError("El archivo de reglas debe contener una lista JSON.")
        try:
            return [Rule.from_dict(item) for item in payload]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"El archivo contiene una regla no válida: {exc}") from exc

    def save(self, rules: list[Rule]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as file:
                temp_path = Path(file.name)
                json.dump(
                    [asdict(rule) for rule in rules],
                    file,
                    ensure_ascii=False,
                    indent=2,
                )
                file.write("\n")
            os.replace(temp_path, self.path)
        except OSError:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise


class RuleEngine:
    """Devuelve reglas activas que coinciden con eventos JSON de TikTok."""

    def __init__(self, rules: list[Rule], seen_event_limit: int = 4096) -> None:
        if seen_event_limit < 1:
            raise ValueError("seen_event_limit debe ser mayor que cero.")
        self.rules = rules
        self._seen_ids: set[str] = set()
        self._seen_order: deque[str] = deque(maxlen=seen_event_limit)
        self._like_progress: dict[str, int] = {}

    def match_event(
        self,
        event: Mapping[str, Any],
        *,
        fallback_rule: Rule | None = None,
    ) -> list[Rule]:
        event_id = event.get("event_id")
        if event_id is not None:
            key = str(event_id)
            if key in self._seen_ids:
                return []
            if len(self._seen_order) == self._seen_order.maxlen:
                oldest = self._seen_order[0]
                self._seen_ids.discard(oldest)
            self._seen_order.append(key)
            self._seen_ids.add(key)
        matching_rules = [rule for rule in self.rules if rule.matches(event)]
        if matching_rules:
            return matching_rules
        if fallback_rule is not None and fallback_rule.matches(event):
            return [fallback_rule]
        return []

    def consume_likes(self, rule: Rule, amount: int) -> int:
        """Devuelve los umbrales completos cruzados por el incremento de likes."""
        if amount <= 0 or rule.like_threshold <= 0:
            return 0
        progress = self._like_progress.get(rule.id, 0) + amount
        crossed, self._like_progress[rule.id] = divmod(
            progress, rule.like_threshold
        )
        return crossed

    def reset_like_progress(self) -> None:
        self._like_progress.clear()


def missing_event_fields(event: Mapping[str, Any]) -> list[str]:
    """Return required TikTok event keys that are absent or blank."""
    event_type = str(event.get("event", "")).lower()
    return [
        field_name
        for field_name in REQUIRED_EVENT_FIELDS.get(event_type, ())
        if event.get(field_name) is None
        or (
            isinstance(event.get(field_name), str)
            and not str(event.get(field_name)).strip()
        )
    ]
