# -*- coding: utf-8 -*-
"""Тесты RepoRPG. Запуск: python -m unittest discover -s tests -v

Тесты работают офлайн: сеть не используется.
"""

import json
import sys
import tempfile
import subprocess
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rpg  # noqa: E402


def make_user(**over):
    user = {
        "login": "tester",
        "name": "Test <script>User</script>",
        "avatar_url": "https://avatars.githubusercontent.com/u/1?v=4",
        "followers": 120,
        "public_repos": 12,
        "created_at": "2013-05-01T00:00:00Z",
    }
    user.update(over)
    return user


def make_repos(languages, stars=0, forks=0):
    repos = []
    for i, lang in enumerate(languages):
        repos.append({
            "language": lang,
            "stargazers_count": stars if i == 0 else 0,
            "forks_count": forks if i == 0 else 0,
        })
    return repos


class LevelAndRarityTest(unittest.TestCase):
    def test_level_grows_and_caps(self):
        self.assertEqual(rpg.level_for(0), 1)
        self.assertEqual(rpg.level_for(4), 1)      # 1 + (2//3)
        self.assertEqual(rpg.level_for(9), 2)      # 1 + (3//3)
        self.assertGreater(rpg.level_for(10000), rpg.level_for(100))
        self.assertEqual(rpg.level_for(10**9), rpg.MAX_LEVEL)

    def test_rarity_boundaries(self):
        self.assertEqual(rpg.rarity_for(0)[0], "COMMON")
        self.assertEqual(rpg.rarity_for(501)[0], "RARE")
        self.assertEqual(rpg.rarity_for(3001)[0], "EPIC")
        self.assertEqual(rpg.rarity_for(20001)[0], "LEGENDARY")


class AnalyzeTest(unittest.TestCase):
    def test_class_from_top_language(self):
        data = rpg.analyze(make_user(), make_repos(["C", "C", "Shell"]), "tester")
        self.assertEqual(data["top_lang"], "C")
        self.assertEqual(data["class_name"], "Kernel Necromancer")

    def test_unknown_language_fallback(self):
        data = rpg.analyze(make_user(), make_repos(["Brainfuck"]), "tester")
        self.assertEqual(data["class_name"], "Code Wanderer")

    def test_luk_is_deterministic_and_bounded(self):
        a = rpg.analyze(make_user(), [], "tester")["stats"]["LUK"]
        b = rpg.analyze(make_user(), [], "tester")["stats"]["LUK"]
        self.assertEqual(a, b)
        self.assertTrue(10 <= a <= 98)

    def test_xp_and_achievements(self):
        user = make_user(followers=100, public_repos=40, created_at="2010-01-01T00:00:00Z")
        data = rpg.analyze(user, make_repos(["C", "Go", "Rust", "Python", "Shell"],
                                           stars=100, forks=100), "tester")
        for ach in ("Dinosaur", "Star Collector", "Polyglot", "Popular",
                    "Prolific", "Fork King"):
            self.assertIn(ach, data["achievements"])
        self.assertEqual(data["xp"], 100 * 20 + 40 * 10 + 100 * 5 + 100 * 2)

    def test_newcomer_gets_default_achievement(self):
        user = make_user(followers=0, public_repos=1, created_at="2024-01-01T00:00:00Z")
        data = rpg.analyze(user, make_repos(["Python"]), "tester")
        self.assertEqual(data["achievements"], ["New Adventurer"])


class SvgTest(unittest.TestCase):
    def _svg(self, **kwargs):
        user = kwargs.pop("user", make_user())
        repos = kwargs.pop("repos", make_repos(["Python", "Rust"]))
        data = rpg.analyze(user, repos, "tester")
        return rpg.generate_svg(user, data, "tester", **kwargs)

    def test_svg_is_valid_xml(self):
        ET.fromstring(self._svg())  # бросит исключение, если XML битый

    def test_contains_core_fields(self):
        svg = self._svg()
        self.assertIn("@tester", svg)
        self.assertIn("Data Mage", svg)
        self.assertIn("REPO RPG", svg)

    def test_escapes_injection(self):
        svg = self._svg()
        self.assertNotIn("<script>", svg)
        self.assertIn("&lt;script&gt;", svg)

    def test_placeholder_avatar_when_missing(self):
        svg = self._svg(user=make_user(avatar_url=""))
        self.assertNotIn("<image", svg)
        self.assertIn(">T<", svg)  # первая буква логина "tester"

    def test_theme_is_applied(self):
        self.assertIn("#ffffff", self._svg(theme_name="light"))


class HelperTest(unittest.TestCase):
    def test_wrap_shortens_long_text(self):
        lines = rpg._wrap("word " * 40, 20, max_lines=2)
        self.assertLessEqual(len(lines), 2)
        self.assertTrue(lines[-1].endswith("…"))

    def test_esc(self):
        self.assertEqual(rpg.esc('a & "b"'), "a &amp; &quot;b&quot;")
        self.assertEqual(rpg.esc(None), "")


class FixtureTest(unittest.TestCase):
    def test_load_fixture(self):
        payload = {"user": make_user(), "repos": make_repos(["Go"]),
                   "avatar_b64": "AAAA", "avatar_mime": "image/png"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            user, repos, avatar = rpg.load_fixture(str(path))
        self.assertEqual(user["login"], "tester")
        self.assertEqual(len(repos), 1)
        self.assertTrue(avatar.startswith("data:image/png;base64,"))

    def test_terminal_output(self):
        data = rpg.analyze(make_user(), make_repos(["Python"]), "tester")
        text = rpg.render_terminal("tester", data)
        self.assertIn("@tester", text)
        self.assertIn("HP:", text)


class StdoutCliTest(unittest.TestCase):
    def test_file_output_still_writes_svg(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "profile.json"
            fixture.write_text(json.dumps({"user": make_user(), "repos": []}), encoding="utf-8")
            output = Path(tmp) / "nested/card.svg"
            result = subprocess.run([sys.executable, str(Path(rpg.__file__).resolve()),
                                     "-u", "tester", "--from-json", str(fixture),
                                     "-o", str(output), "--quiet"], cwd=tmp,
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            ET.fromstring(output.read_text(encoding="utf-8"))
            self.assertIn("Saved to", result.stdout)

    def test_stdout_output_is_svg_in_normal_and_quiet_modes(self):
        script = Path(rpg.__file__).resolve()
        for quiet in (False, True):
            with self.subTest(quiet=quiet), tempfile.TemporaryDirectory() as tmp:
                fixture = Path(tmp) / "profile.json"
                fixture.write_text(json.dumps({"user": make_user(), "repos": make_repos(["Python"])}), encoding="utf-8")
                args = [sys.executable, str(script), "-u", "tester", "--from-json", str(fixture), "--output", "-"]
                if quiet:
                    args.append("--quiet")
                result = subprocess.run(args, cwd=tmp, capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.startswith("<svg"), result.stdout[:100])
                ET.fromstring(result.stdout)
                self.assertFalse((Path(tmp) / "-").exists())
                if quiet:
                    self.assertEqual(result.stderr, "")
                else:
                    self.assertIn("Fetching @tester", result.stderr)


if __name__ == "__main__":
    unittest.main()
