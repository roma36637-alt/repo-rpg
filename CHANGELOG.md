# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-11-25

### Added

- `rpg` CLI: turn a GitHub profile into an RPG character card as an SVG.
- `-u / --username`, `-o / --output`, `--theme dark|light`, `--no-avatar`.
- `--from-json FILE` offline mode: build a card from saved profile data with no
  network access (used by the test suite).
- `--token` and `GITHUB_TOKEN` / `GH_TOKEN` environment variables for the API.
- GitHub Action that regenerates the card on a schedule and commits it.
- 16 offline tests, plus CI on Python 3.9 and 3.12.

[Unreleased]: https://github.com/roma36637-alt/repo-rpg/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/roma36637-alt/repo-rpg/releases/tag/v1.0.0
