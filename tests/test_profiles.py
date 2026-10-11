from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from profiles import (
    RuleProfile,
    RuleProfileStore,
    create_default_profile,
    create_dani_profile,
)
from rules_engine import Rule


class RuleProfileTests(unittest.TestCase):
    def test_default_profile_contains_requested_event_rules(self) -> None:
        profile = create_default_profile()
        rules_by_name = {rule.name: rule for rule in profile.rules}

        self.assertEqual(profile.name, "default")
        self.assertEqual(
            rules_by_name["Seguir: creeper"].event_type,
            "follow",
        )
        self.assertNotIn("ignited:true", rules_by_name["Seguir: creeper"].action)
        self.assertNotIn(
            "powered:true",
            rules_by_name["Corazón con dedos: creeper"].action,
        )
        self.assertEqual(
            rules_by_name["Cada 200 likes: zombie"].like_threshold,
            200,
        )
        self.assertEqual(
            rules_by_name["Capibara: 30 rayos"].repeat_count,
            30,
        )
        self.assertTrue(
            rules_by_name["Rosa: TNT con mecha de 40 ticks"].repeat_by_amount
        )
        self.assertIn("\n", rules_by_name["Dona: subir 100 bloques y dar agua"].action)
        self.assertEqual(create_dani_profile().name, "default")

    def test_first_load_adds_default_and_preserves_legacy_rules(self) -> None:
        legacy = Rule.create("Regla antigua", "comment", {}, "say {text}")
        with tempfile.TemporaryDirectory() as directory:
            store = RuleProfileStore(Path(directory) / "profiles.json")

            profiles = store.load([legacy])

            self.assertEqual(
                [profile.name for profile in profiles],
                ["default", "Personalizado"],
            )
            self.assertEqual(profiles[1].rules[0], legacy)
            self.assertEqual(store.load()[0].name, "default")

    def test_legacy_dani_profile_is_renamed_and_creepers_are_disarmed(self) -> None:
        old_rule = Rule.create(
            "Creeper legado",
            "follow",
            {},
            "summon minecraft:creeper ~ ~ ~ "
            "{powered:true,Fuse:10,ignited:true}",
        )
        with tempfile.TemporaryDirectory() as directory:
            store = RuleProfileStore(Path(directory) / "profiles.json")
            store.save([RuleProfile("dani", [old_rule])])

            profiles = store.load()

            self.assertEqual(profiles[0].name, "default")
            self.assertEqual(
                profiles[0].rules[0].action,
                "summon minecraft:creeper ~ ~ ~ "
                "{powered:false,ignited:false}",
            )
            self.assertEqual(store.load()[0].name, "default")

    def test_legacy_dani_is_not_merged_over_an_existing_default(self) -> None:
        default_rule = Rule.create("Default", "follow", {}, "say default")
        dani_rule = Rule.create("Dani", "follow", {}, "say dani")
        with tempfile.TemporaryDirectory() as directory:
            store = RuleProfileStore(Path(directory) / "profiles.json")
            store.save([
                RuleProfile("default", [default_rule]),
                RuleProfile("dani", [dani_rule]),
            ])

            profiles = store.load()

            self.assertEqual([profile.name for profile in profiles], [
                "default",
                "dani",
            ])
            self.assertEqual(profiles[0].rules, [default_rule])
            self.assertEqual(profiles[1].rules, [dani_rule])

    def test_store_rejects_duplicate_profile_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RuleProfileStore(Path(directory) / "profiles.json")

            with self.assertRaisesRegex(ValueError, "únicos"):
                store.save([
                    RuleProfile("Default", []),
                    RuleProfile("default", []),
                ])


if __name__ == "__main__":
    unittest.main()
