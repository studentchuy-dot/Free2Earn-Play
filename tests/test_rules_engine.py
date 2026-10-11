from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rules_engine import (
    Rule,
    RuleEngine,
    RuleStore,
    missing_event_fields,
    render_action_commands,
    render_action_template,
    sanitize_chat_text,
    render_tellraw_command,
)


class RuleEngineTests(unittest.TestCase):
    def test_rule_matches_event_type_and_exact_condition_case_insensitively(self) -> None:
        rule = Rule.create(
            "Regalo rosa",
            "gift",
            {"gift_name": "Rose"},
            "say Gracias",
        )
        self.assertTrue(
            rule.matches({"event": "gift", "gift_name": "rose"})
        )
        self.assertFalse(
            rule.matches({"event": "comment", "gift_name": "Rose"})
        )
        self.assertFalse(
            rule.matches({"event": "gift", "gift_name": "Heart"})
        )

    def test_engine_returns_only_enabled_matching_rules(self) -> None:
        enabled = Rule.create("Activa", "follow", {}, "say Hola")
        disabled = Rule.create(
            "Pausada", "follow", {}, "say Hola", enabled=False
        )
        engine = RuleEngine([enabled, disabled])
        self.assertEqual(
            engine.match_event({"event": "follow"}),
            [enabled],
        )

    def test_duplicate_event_id_only_triggers_once(self) -> None:
        rule = Rule.create("Comentario", "comment", {}, "say Hola")
        engine = RuleEngine([rule])
        event = {"event": "comment", "event_id": "evt-1"}
        self.assertEqual(engine.match_event(event), [rule])
        self.assertEqual(engine.match_event(event), [])

    def test_fallback_rule_only_matches_when_no_regular_rule_matches(self) -> None:
        known_gift = Rule.create(
            "Rosa", "gift", {"gift_name": "Rose"}, "say Rosa"
        )
        fallback = Rule.create(
            "Respaldo", "gift", {}, "summon minecraft:slime ~ ~ ~ {Size:4}"
        )
        engine = RuleEngine([known_gift])

        self.assertEqual(
            engine.match_event(
                {"event": "gift", "gift_name": "Rose"},
                fallback_rule=fallback,
            ),
            [known_gift],
        )
        self.assertEqual(
            engine.match_event(
                {"event": "gift", "gift_name": "Galaxy"},
                fallback_rule=fallback,
            ),
            [fallback],
        )
        self.assertEqual(
            engine.match_event(
                {"event": "comment", "text": "hello"},
                fallback_rule=fallback,
            ),
            [],
        )

    def test_like_threshold_accumulates_incremental_counts(self) -> None:
        rule = Rule.create(
            "Mobs por likes",
            "like",
            {},
            "summon {entity} ~ ~ ~",
            action_mode="blocks",
            action_kind="spawn",
            like_threshold=100,
            spawn_count=2,
            entity_id="minecraft:zombie",
        )
        engine = RuleEngine([rule])

        self.assertEqual(engine.consume_likes(rule, 35), 0)
        self.assertEqual(engine.consume_likes(rule, 70), 1)
        self.assertEqual(engine.consume_likes(rule, 195), 2)
        self.assertEqual(
            render_action_template(
                rule.action,
                {"entity": rule.entity_id},
            ),
            "summon minecraft:zombie ~ ~ ~",
        )

    def test_action_template_expands_event_values_and_removes_newlines(self) -> None:
        command = render_action_template(
            "say {usuario} envió {gift} x{amount}: {text} {diamond_count}",
            {
                "user": "Streamer",
                "gift_name": "Rose",
                "amount": 3,
                "text": "hola\nsegunda línea",
                "diamond_count": 1,
            },
        )

        self.assertEqual(
            command,
            "say Streamer envió Rose x3: hola segunda línea 1",
        )

    def test_template_supports_username_giftname_and_minecraft_player(self) -> None:
        self.assertEqual(
            render_action_template(
                "tellraw {player} {username} {giftname}",
                {
                    "player": "@a",
                    "user": "Dani",
                    "gift_name": "Rose",
                },
            ),
            "tellraw @a Dani Rose",
        )

    def test_tellraw_announcement_is_purple_and_escapes_event_text(self) -> None:
        command = render_tellraw_command(
            "@a",
            "{usuario} envió {gift_name} x{amount}",
            {
                "user": 'Dani "the streamer"',
                "gift_name": "Rose\\Gift",
                "amount": 2,
            },
            color="light_purple",
        )

        prefix, component_json = command.split(" ", 2)[1:]
        self.assertEqual(prefix, "@a")
        component = json.loads(component_json)
        self.assertEqual(
            component,
            {
                "text": 'Dani "the streamer" envió Rose\\Gift x2',
                "color": "light_purple",
            },
        )

    def test_tellraw_rejects_non_purple_colors(self) -> None:
        with self.assertRaisesRegex(ValueError, "color"):
            render_tellraw_command(
                "@a",
                "Hola",
                {},
                color="red",
            )

    def test_chat_text_removes_invisible_controls_but_keeps_unicode(self) -> None:
        self.assertEqual(
            sanitize_chat_text(" ¡Qué tal!\u202e\u200b\u0000🙂  "),
            "¡Qué tal! 🙂",
        )

    def test_event_schemas_require_comment_text_gift_name_and_amount(self) -> None:
        self.assertEqual(
            missing_event_fields({"event": "comment", "text": "hello"}),
            [],
        )
        self.assertEqual(
            missing_event_fields({"event": "gift", "gift_name": "Rose"}),
            ["amount"],
        )
        self.assertEqual(
            missing_event_fields({"event": "like", "count": 8}),
            [],
        )

    def test_multiline_action_becomes_separate_commands(self) -> None:
        self.assertEqual(
            render_action_commands(
                "tp {player} ~ ~100 ~\n\n"
                "give {player} minecraft:water_bucket 1",
                {"player": "@a"},
            ),
            [
                "tp @a ~ ~100 ~",
                "give @a minecraft:water_bucket 1",
            ],
        )

    def test_store_round_trips_rules_as_json(self) -> None:
        rule = Rule.create(
            "Saludar",
            "like",
            {},
            "summon {entity} ~ ~ ~",
            action_mode="blocks",
            action_kind="spawn",
            like_threshold=50,
            spawn_count=3,
            entity_id="minecraft:creeper",
            repeat_count=2,
            repeat_by_amount=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            store = RuleStore(Path(directory) / "rules.json")
            store.save([rule])
            self.assertEqual(store.load(), [rule])

    def test_store_rejects_non_boolean_gift_multiplier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            path.write_text(
                '[{"id":"r","name":"R","event_type":"gift",'
                '"conditions":{},"action":"say hello",'
                '"repeat_by_amount":"false"}]',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "repeat_by_amount"):
                RuleStore(path).load()

    def test_store_loads_legacy_rule_with_new_options_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            path.write_text(
                '[{"id":"old","name":"Old rule","event_type":"comment",'
                '"conditions":{},"action":"say hello","enabled":true}]',
                encoding="utf-8",
            )

            loaded = RuleStore(path).load()

            self.assertEqual(loaded[0].action_mode, "advanced")
            self.assertEqual(loaded[0].action_kind, "command")
            self.assertEqual(loaded[0].like_threshold, 100)
            self.assertEqual(loaded[0].repeat_count, 1)
            self.assertFalse(loaded[0].repeat_by_amount)

    def test_store_rejects_invalid_json_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lista JSON"):
                RuleStore(path).load()


if __name__ == "__main__":
    unittest.main()
