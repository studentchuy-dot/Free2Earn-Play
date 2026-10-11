"""Perfiles de reglas y perfil de ejemplo Dani."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rules_engine import Rule


@dataclass
class RuleProfile:
    name: str
    rules: list[Rule]


def _gift_rule(
    name: str,
    gift_name: str,
    action: str,
    *,
    repeat_count: int = 1,
    repeat_by_amount: bool = True,
) -> Rule:
    return Rule.create(
        name,
        "gift",
        {"gift_name": gift_name},
        action,
        action_mode="advanced",
        action_kind="command",
        repeat_count=repeat_count,
        repeat_by_amount=repeat_by_amount,
    )


def create_dani_profile() -> RuleProfile:
    """Return the editable default ruleset; automation itself remains paused."""
    player = "{player}"
    return RuleProfile(
        "dani",
        [
            Rule.create(
                "Seguir: creeper cargado",
                "follow",
                {},
                "execute as "
                + player
                + " at @s run summon minecraft:creeper ~ ~ ~ "
                "{powered:true,Fuse:10,ignited:true}",
            ),
            _gift_rule(
                "Rosa: TNT con mecha de 40 ticks",
                "Rose",
                "execute as "
                + player
                + " at @s run summon minecraft:tnt ~ ~ ~ {fuse:40}",
            ),
            _gift_rule(
                "GG: esqueleto con arco",
                "GG",
                "execute as "
                + player
                + " at @s run summon minecraft:skeleton ~ ~ ~ "
                '{HandItems:[{id:"minecraft:bow",count:1},{}]}',
            ),
            _gift_rule(
                "Popular: zombie con calabaza",
                "Popular",
                "execute as "
                + player
                + " at @s run summon minecraft:zombie ~ ~ ~ "
                '{ArmorItems:[{},{},{},{id:"minecraft:carved_pumpkin",count:1}]}',
            ),
            Rule.create(
                "Cada 200 likes: zombie",
                "like",
                {},
                "execute as "
                + player
                + " at @s run summon {entity} ~ ~ ~",
                action_mode="advanced",
                action_kind="spawn",
                like_threshold=200,
                entity_id="minecraft:zombie",
            ),
            _gift_rule(
                "Cono de helado: 3 abejas",
                "Ice Cream Cone",
                "execute as "
                + player
                + " at @s run summon minecraft:bee ~ ~ ~ {AngerTime:1200}",
                repeat_count=3,
            ),
            _gift_rule(
                "Quiéreme: tótem apilable hasta 16",
                "I Love You",
                f"give {player} minecraft:totem_of_undying"
                "[minecraft:max_stack_size=16] 1",
            ),
            _gift_rule(
                "Corazón con dedos: creeper cargado",
                "Finger Heart",
                "execute as "
                + player
                + " at @s run summon minecraft:creeper ~ ~ ~ "
                "{powered:true,Fuse:10,ignited:true}",
            ),
            _gift_rule(
                "Collar de amistad: pollo jinete",
                "Friendship Necklace",
                "execute as "
                + player
                + " at @s run summon minecraft:chicken ~ ~ ~ "
                '{Passengers:[{id:"minecraft:zombie",IsBaby:true}]}',
            ),
            _gift_rule(
                "Confeti: cuarto hueco 5x5 de TNT",
                "Confetti",
                "execute as "
                + player
                + " at @s run fill ~-2 ~ ~-2 ~2 ~4 ~2 "
                "minecraft:tnt outline",
            ),
            _gift_rule(
                "Dona: subir 100 bloques y dar agua",
                "Doughnut",
                "execute as "
                + player
                + " at @s run tp @s ~ ~100 ~\n"
                + f"give {player} minecraft:water_bucket 1",
            ),
            _gift_rule(
                "Amigos frutales: warden al frente",
                "Fruit Friends",
                "execute as "
                + player
                + " at @s run summon minecraft:warden ^ ^ ^1",
            ),
            _gift_rule(
                "Capibara: 30 rayos",
                "Capybara",
                "execute as "
                + player
                + " at @s run summon minecraft:lightning_bolt ~ ~ ~",
                repeat_count=30,
            ),
            _gift_rule(
                "Pistola de dinero: wither",
                "Money Gun",
                "execute as "
                + player
                + " at @s run summon minecraft:wither ~ ~ ~",
            ),
            _gift_rule(
                "Galaxia: dragón del End",
                "Galaxy",
                "execute as "
                + player
                + " at @s run summon minecraft:ender_dragon ~ ~ ~",
            ),
            _gift_rule(
                "Waterdrop: cubeta de agua",
                "Waterdrop",
                f"give {player} minecraft:water_bucket 1",
            ),
        ],
    )


class RuleProfileStore:
    """Persist rule profiles without changing the legacy rules.json file."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def load(self, legacy_rules: list[Rule] | None = None) -> list[RuleProfile]:
        if not self.path.exists():
            profiles = [create_dani_profile()]
            if legacy_rules:
                profiles.append(
                    RuleProfile(
                        "Personalizado",
                        [Rule.from_dict(asdict(rule)) for rule in legacy_rules],
                    )
                )
            self.save(profiles)
            return profiles

        try:
            payload: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"No se pudieron leer los perfiles: {exc}") from exc
        if not isinstance(payload, list):
            raise ValueError("El archivo de perfiles debe contener una lista JSON.")

        profiles: list[RuleProfile] = []
        names: set[str] = set()
        try:
            for item in payload:
                if not isinstance(item, dict):
                    raise ValueError("Cada perfil debe ser un objeto JSON.")
                name = str(item["name"]).strip()
                rules_data = item["rules"]
                if not name or name.casefold() in names:
                    raise ValueError("Los nombres de perfil deben ser únicos.")
                if not isinstance(rules_data, list):
                    raise ValueError("Las reglas de cada perfil deben ser una lista.")
                profiles.append(
                    RuleProfile(
                        name,
                        [Rule.from_dict(rule) for rule in rules_data],
                    )
                )
                names.add(name.casefold())
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"El archivo contiene un perfil no válido: {exc}") from exc
        if not profiles:
            raise ValueError("Debe existir al menos un perfil.")
        return profiles

    def save(self, profiles: list[RuleProfile]) -> None:
        if not profiles:
            raise ValueError("Debe existir al menos un perfil.")
        names = [profile.name.strip().casefold() for profile in profiles]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise ValueError("Los nombres de perfil deben ser únicos y no vacíos.")

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
                    [
                        {"name": profile.name, "rules": [asdict(rule) for rule in profile.rules]}
                        for profile in profiles
                    ],
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
