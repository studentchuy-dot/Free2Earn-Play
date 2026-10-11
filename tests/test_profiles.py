from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from profiles import RuleProfile, RuleProfileStore, create_dani_profile
from rules_engine import Rule


class RuleProfileTests(unittest.TestCase):
    def test_dani_profile_contains_requested_event_rules(self) -> None:
        profile = create_dani_profile()
        rules_by_name = {rule.name: rule for rule in profile.rules}

        self.assertEqual(profile.name, "dani")
        self.assertEqual(
            rules_by_name["Seguir: creeper cargado"].event_type,
            "follow",
        )
        self.assertIn("Fuse:10", rules_by_name["Seguir: creeper cargado"].action)
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

    def test_first_load_adds_dani_and_preserves_legacy_rules(self) -> None:
        legacy = Rule.create("Regla antigua", "comment", {}, "say {text}")
        with tempfile.TemporaryDirectory() as directory:
            store = RuleProfileStore(Path(directory) / "profiles.json")

            profiles = store.load([legacy])

            self.assertEqual([profile.name for profile in profiles], [
                "dani",
                "Personalizado",
            ])
            self.assertEqual(profiles[1].rules[0], legacy)
            self.assertEqual(store.load()[0].name, "dani")

    def test_store_rejects_duplicate_profile_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RuleProfileStore(Path(directory) / "profiles.json")

            with self.assertRaisesRegex(ValueError, "únicos"):
                store.save([
                    RuleProfile("Dani", []),
                    RuleProfile("dani", []),
                ])


if __name__ == "__main__":
    unittest.main()
