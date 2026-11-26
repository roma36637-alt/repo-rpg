#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RepoRPG — превращает профиль GitHub в карточку RPG-персонажа (SVG).

Примеры запуска:
    # обычный режим (нужен интернет)
    python rpg.py -u torvalds -o card.svg

    # офлайн-режим на готовых данных — работает без сети и без токена
    python rpg.py -u torvalds --from-json examples/torvalds.json -o card.svg

    # с токеном, чтобы не упереться в лимит API (или переменная GITHUB_TOKEN)
    python rpg.py -u torvalds --token ghp_xxx

Зависимостей нет: используется только стандартная библиотека Python 3.9+.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from html import escape
from pathlib import Path

__version__ = "1.0.0"

API = "https://api.github.com"
USER_AGENT = f"RepoRPG/{__version__}"
MAX_LEVEL = 99
MAX_REPO_PAGES = 10  # до 1000 репозиториев, защита от бесконечной пагинации

# Язык -> RPG-класс
CLASSES = {
    "Python": "Data Mage",
    "JavaScript": "Frontend Rogue",
    "TypeScript": "Type Wizard",
    "Rust": "Memory Paladin",
    "Go": "Cloud Samurai",
    "Java": "Enterprise Orc",
    "Kotlin": "Android Bard",
    "Swift": "iOS Elf",
    "C": "Kernel Necromancer",
    "C++": "Memory Barbarian",
    "C#": "Unity Knight",
    "PHP": "Legacy Sorcerer",
    "Ruby": "Startup Bard",
    "HTML": "Pixel Artist",
    "CSS": "Style Alchemist",
    "Jupyter Notebook": "AI Oracle",
    "Shell": "Terminal Hacker",
    "Dart": "Flutter Monk",
    "R": "Stat Druid",
    "Vue": "Reactivity Ranger",
    "Svelte": "Compiler Assassin",
    "Lua": "Script Shaman",
    "Perl": "Regex Wizard",
    "Scala": "Big Data Warlock",
    "Haskell": "Lambda Mystic",
    "Elixir": "Concurrency Druid",
    "Zig": "Memory Smith",
    "Assembly": "Silicon Whisperer",
    "PowerShell": "Sysadmin Paladin",
    "Makefile": "Build Alchemist",
}

ACHIEVEMENT_EMOJI = {
    "Dinosaur": "🦕",
    "Star Collector": "⭐",
    "Polyglot": "🌍",
    "Popular": "❤️",
    "Prolific": "📚",
    "Fork King": "🍴",
    "New Adventurer": "🌱",
}

RARITIES = (
    (20000, "LEGENDARY", "#f0b72f"),
    (3000, "EPIC", "#c678dd"),
    (500, "RARE", "#4da6ff"),
    (0, "COMMON", "#9e9e9e"),
)

THEMES = {
    "dark": {
        "bg1": "#161b22", "bg2": "#0d1117", "text": "#ffffff",
        "muted": "#8b949e", "subtext": "#c9d1d9", "panel": "#21262d",
        "track": "#21262d",
    },
    "light": {
        "bg1": "#ffffff", "bg2": "#f6f8fa", "text": "#1f2328",
        "muted": "#57606a", "subtext": "#2f363d", "panel": "#eaeef2",
        "track": "#d0d7de",
    },
}

STAT_COLORS = {
    "HP": "#ff5f56", "ATK": "#ffbd2e", "DEF": "#27c93f",
    "INT": "#4da6ff", "LUK": "#c678dd",
}


# --------------------------------------------------------------------------- #
# Утилиты
# --------------------------------------------------------------------------- #
def esc(value) -> str:
    """Безопасно экранирует значения для SVG/XML."""
    return escape(str(value if value is not None else ""), quote=True)


def build_headers(token: str | None = None) -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _http_get(url: str, token: str | None = None, timeout: float = 15.0):
    """Возвращает (bytes, content_type). Понятно ругается на типовые ошибки."""
    request = urllib.request.Request(url, headers=build_headers(token))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(), response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise SystemExit(f"✗ GitHub: не найдено ({url}). Проверьте ник.")
        if error.code in (401, 403) and error.headers.get("X-RateLimit-Remaining") == "0":
            reset = error.headers.get("X-RateLimit-Reset", "?")
            raise SystemExit(
                "✗ Лимит GitHub API исчерпан. Подождите или передайте "
                f"--token (сброс в Unix-времени {reset})."
            )
        raise SystemExit(f"✗ GitHub API: HTTP {error.code} ({url}).")
    except urllib.error.URLError as error:
        raise SystemExit(f"✗ Нет соединения с GitHub: {error.reason}. "
                         f"Попробуйте офлайн-режим --from-json.")


def _get_json(url: str, token: str | None = None) -> dict | list:
    raw, _ = _http_get(url, token)
    return json.loads(raw.decode("utf-8"))


# --------------------------------------------------------------------------- #
# Получение данных
# --------------------------------------------------------------------------- #
def fetch_profile(username: str, token: str | None = None) -> tuple[dict, list]:
    """Тянет профиль и все публичные репозитории (с пагинацией)."""
    user = _get_json(f"{API}/users/{username}", token)
    if not isinstance(user, dict):
        raise SystemExit("✗ Неожиданный ответ GitHub.")
    repos: list = []
    for page in range(1, MAX_REPO_PAGES + 1):
        chunk = _get_json(
            f"{API}/users/{username}/repos?per_page=100&page={page}&sort=updated",
            token,
        )
        if not isinstance(chunk, list) or not chunk:
            break
        repos.extend(chunk)
        if len(chunk) < 100:
            break
    return user, repos


def load_fixture(path: str) -> tuple[dict, list, str]:
    """Читает сохранённые данные для офлайн-режима.

    Ожидаемый формат: {"user": {...}, "repos": [...], "avatar_b64": "..."}.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    user = data.get("user") or data
    repos = data.get("repos", []) or []
    avatar_b64 = data.get("avatar_b64", "") or ""
    mime = data.get("avatar_mime", "image/png")
    avatar_uri = f"data:{mime};base64,{avatar_b64}" if avatar_b64 else ""
    return user, repos, avatar_uri


def fetch_avatar(user: dict, token: str | None = None) -> str:
    """Скачивает аватар и возвращает его как data-URI.

    Это важно: когда SVG вставлен в README через <img>, браузер не грузит
    внешние ресурсы внутри картинки. Поэтому аватар нужно встроить в файл.
    """
    url = user.get("avatar_url")
    if not url:
        return ""
    sep = "&" if "?" in url else "?"
    url = f"{url}{sep}s=200"
    try:
        raw, content_type = _http_get(url, token)
    except SystemExit:
        return ""
    mime = (content_type or "image/png").split(";")[0].strip()
    if not mime.startswith("image/"):
        mime = "image/png"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


# --------------------------------------------------------------------------- #
# Анализ
# --------------------------------------------------------------------------- #
def rarity_for(xp: int) -> tuple[str, str]:
    for threshold, name, color in RARITIES:
        if xp > threshold:
            return name, color
    return RARITIES[-1][1], RARITIES[-1][2]


def level_for(xp: int) -> int:
    if xp <= 0:
        return 1
    return min(MAX_LEVEL, 1 + int((xp ** 0.5) // 3))


def analyze(user: dict, repos: list, username: str) -> dict:
    lang_count: dict[str, int] = {}
    stars = forks = 0
    for repo in repos:
        if not isinstance(repo, dict):
            continue
        lang = repo.get("language")
        if lang:
            lang_count[lang] = lang_count.get(lang, 0) + 1
        stars += repo.get("stargazers_count") or 0
        forks += repo.get("forks_count") or 0

    top_langs = sorted(lang_count.items(), key=lambda kv: (-kv[1], kv[0]))[:4]
    top_lang = top_langs[0][0] if top_langs else "Unknown"
    class_name = CLASSES.get(top_lang, "Code Wanderer")

    followers = int(user.get("followers") or 0)
    public_repos = int(user.get("public_repos") or 0)

    xp = followers * 20 + public_repos * 10 + stars * 5 + forks * 2
    level = level_for(xp)
    rarity, rarity_color = rarity_for(xp)

    luk = int(hashlib.md5(username.encode("utf-8")).hexdigest(), 16) % 89 + 10

    stats = {
        "HP": min(99, 30 + public_repos),
        "ATK": min(99, 20 + stars),
        "DEF": min(99, 20 + followers),
        "INT": min(99, 30 + len(lang_count) * 10),
        "LUK": luk,
    }

    created = str(user.get("created_at") or "2020")
    year = int(created[:4]) if created[:4].isdigit() else 2020
    achievements = []
    if year < 2015:
        achievements.append("Dinosaur")
    if stars > 50:
        achievements.append("Star Collector")
    if len(lang_count) >= 5:
        achievements.append("Polyglot")
    if followers > 50:
        achievements.append("Popular")
    if public_repos > 30:
        achievements.append("Prolific")
    if forks > 50:
        achievements.append("Fork King")
    if not achievements:
        achievements.append("New Adventurer")

    return {
        "top_lang": top_lang,
        "top_langs": top_langs,
        "class_name": class_name,
        "level": level,
        "rarity": rarity,
        "rarity_color": rarity_color,
        "stats": stats,
        "stars": stars,
        "forks": forks,
        "followers": followers,
        "public_repos": public_repos,
        "achievements": achievements,
        "xp": xp,
        "lang_count": lang_count,
        "created_year": year,
    }


# --------------------------------------------------------------------------- #
# Отрисовка SVG
# --------------------------------------------------------------------------- #
def _wrap(text: str, width: int, max_lines: int = 2) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and len(" ".join(words)) > sum(len(x) for x in lines):
        lines[-1] = lines[-1][: max(0, width - 1)] + "…"
    return lines


def generate_svg(user: dict, data: dict, username: str, theme_name: str = "dark",
                 avatar_uri: str = "") -> str:
    theme = THEMES.get(theme_name, THEMES["dark"])
    color = data["rarity_color"]
    name = esc(user.get("name") or username)

    # Статистика: 5 полос со значением и подписью.
    stat_rows = ""
    for i, (key, value) in enumerate(data["stats"].items()):
        y = 142 + i * 40
        width = int(280 * value / 99)
        stat_rows += (
            f'<text x="350" y="{y + 12}" fill="{theme["muted"]}" '
            f'font-family="monospace" font-size="15" font-weight="bold">{key}</text>'
            f'<rect x="405" y="{y}" width="280" height="14" rx="7" fill="{theme["track"]}"/>'
            f'<rect x="405" y="{y}" width="{width}" height="14" rx="7" fill="{STAT_COLORS[key]}"/>'
            f'<text x="697" y="{y + 12}" fill="{theme["text"]}" '
            f'font-family="monospace" font-size="14" text-anchor="end">{value}</text>'
        )

    total_lang = sum(count for _, count in data["top_langs"]) or 1
    lang_text = "  ".join(
        f"{esc(lang)} {round(count / total_lang * 100)}%" for lang, count in data["top_langs"]
    ) or "No languages yet"
    lang_lines = _wrap(lang_text, 54, max_lines=2)
    lang_svg = "".join(
        f'<text x="350" y="{372 + i * 18}" fill="{theme["subtext"]}" '
        f'font-family="monospace" font-size="13">{esc(line)}</text>'
        for i, line in enumerate(lang_lines)
    )

    ach_text = "  ".join(
        f"{ACHIEVEMENT_EMOJI.get(a, '🏅')} {a}" for a in data["achievements"]
    )
    ach_lines = _wrap(ach_text, 52, max_lines=3)
    ach_svg = "".join(
        f'<text x="350" y="{427 + i * 18}" fill="{color}" '
        f'font-family="monospace" font-size="13">{esc(line)}</text>'
        for i, line in enumerate(ach_lines)
    )

    if avatar_uri:
        avatar_svg = (
            f'<image href="{avatar_uri}" x="40" y="90" width="140" height="140" '
            f'clip-path="url(#av)" preserveAspectRatio="xMidYMid slice"/>'
        )
    else:
        initial = esc((user.get("login") or username)[:1].upper())
        avatar_svg = (
            f'<rect x="40" y="90" width="140" height="140" rx="20" fill="{theme["panel"]}"/>'
            f'<text x="110" y="185" fill="{color}" font-family="monospace" '
            f'font-size="72" font-weight="bold" text-anchor="middle">{initial}</text>'
        )

    return f'''<svg width="800" height="480" viewBox="0 0 800 480"
     xmlns="http://www.w3.org/2000/svg" role="img"
     aria-label="RepoRPG card for {esc(username)}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{theme["bg1"]}"/>
      <stop offset="100%" stop-color="{theme["bg2"]}"/>
    </linearGradient>
    <clipPath id="av"><rect x="40" y="90" width="140" height="140" rx="20"/></clipPath>
  </defs>

  <rect x="5" y="5" width="790" height="470" rx="20"
        fill="url(#bg)" stroke="{color}" stroke-width="3"/>

  <text x="40" y="55" fill="{theme["text"]}" font-family="monospace"
        font-size="22" font-weight="bold">⚔ REPO RPG</text>
  <rect x="610" y="28" width="150" height="32" rx="16" fill="{color}"/>
  <text x="685" y="50" text-anchor="middle" fill="#0d1117" font-family="monospace"
        font-size="14" font-weight="bold">{data["rarity"]}</text>

  {avatar_svg}
  <rect x="40" y="90" width="140" height="140" rx="20" fill="none"
        stroke="{color}" stroke-width="2"/>

  <text x="40" y="262" fill="{theme["text"]}" font-family="monospace"
        font-size="24" font-weight="bold">@{esc(username)}</text>
  <text x="40" y="285" fill="{theme["muted"]}" font-family="monospace"
        font-size="14">{name}</text>

  <rect x="40" y="300" width="260" height="60" rx="12"
        fill="{theme["panel"]}" stroke="{color}" stroke-width="1"/>
  <text x="55" y="325" fill="{color}" font-family="monospace"
        font-size="16" font-weight="bold">{esc(data["class_name"])}</text>
  <text x="55" y="348" fill="{theme["muted"]}" font-family="monospace"
        font-size="13">Lv.{data["level"]}  •  {data["xp"]} XP  •  ★ {data["stars"]}</text>

  <text x="40" y="385" fill="{theme["muted"]}" font-family="monospace"
        font-size="12">TOP: {esc(data["top_lang"])}</text>
  <rect x="40" y="395" width="260" height="10" rx="5" fill="{theme["track"]}"/>
  <rect x="40" y="395" width="{120 + data["level"]}" height="10" rx="5" fill="{color}"/>

  <text x="350" y="112" fill="{theme["text"]}" font-family="monospace"
        font-size="18" font-weight="bold">STATS</text>
  {stat_rows}

  <text x="350" y="350" fill="{theme["text"]}" font-family="monospace"
        font-size="14" font-weight="bold">LANGUAGES</text>
  {lang_svg}

  <text x="350" y="405" fill="{theme["text"]}" font-family="monospace"
        font-size="14" font-weight="bold">ACHIEVEMENTS</text>
  {ach_svg}
</svg>
'''


def render_terminal(username: str, data: dict) -> str:
    lines = [
        "",
        f"⚔️  @{username} — {data['class_name']} "
        f"Lv.{data['level']} [{data['rarity']}]",
    ]
    for key, value in data["stats"].items():
        filled = value // 5
        bar = "█" * filled + "░" * (20 - filled)
        lines.append(f"  {key}: {bar} {value}")
    achievements = ", ".join(data["achievements"])
    lines.append(
        f"  Top: {data['top_lang']} | ★ {data['stars']} | "
        f"Repos: {data['public_repos']} | {achievements}"
    )
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rpg",
        description="RepoRPG — карточка RPG-персонажа из вашего профиля GitHub.",
    )
    parser.add_argument("-u", "--username", required=True, help="ник на GitHub")
    parser.add_argument("-o", "--output", default="card.svg", help="куда сохранить SVG (- для stdout)")
    parser.add_argument("--token", default=None,
                        help="GitHub-токен (или переменная GITHUB_TOKEN/GH_TOKEN)")
    parser.add_argument("--from-json", default=None, metavar="FILE",
                        help="офлайн-режим: взять данные из JSON вместо сети")
    parser.add_argument("--theme", choices=sorted(THEMES), default="dark",
                        help="тема карточки (по умолчанию dark)")
    parser.add_argument("--no-avatar", action="store_true",
                        help="не встраивать аватар (меньше файл)")
    parser.add_argument("--quiet", action="store_true", help="не печатать карточку")
    parser.add_argument("--version", action="version", version=f"RepoRPG {__version__}")
    return parser


def main(argv=None) -> int:
    configure_console()
    parser = build_parser()
    args = parser.parse_args(argv)

    token = args.token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    progress = sys.stderr if args.output == "-" else sys.stdout
    if not args.quiet:
        print(f"Fetching @{args.username}...", file=progress)

    if args.from_json:
        user, repos, avatar_uri = load_fixture(args.from_json)
        avatar_uri = "" if args.no_avatar else avatar_uri
    else:
        user, repos = fetch_profile(args.username, token)
        avatar_uri = "" if args.no_avatar else fetch_avatar(user, token)

    data = analyze(user, repos, args.username)

    if not args.quiet:
        print(render_terminal(args.username, data), file=progress)

    svg = generate_svg(user, data, args.username, args.theme, avatar_uri)
    if args.output == "-":
        sys.stdout.write(svg)
        return 0
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding="utf-8")
    print(f"Saved to {args.output} — вставьте в README!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
