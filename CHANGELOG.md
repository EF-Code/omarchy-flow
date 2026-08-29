# Changelog

All notable changes to **Omarchy Flow** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Expanded the bar menu into a settings hub for dictation behavior, audio
  input, privacy, HUD appearance, diagnostics, and project information.
- Added persistent preferences for toggle completion, clipboard copying,
  audio source, HUD position, and waveform visibility.
- Added editable Hyprland shortcut setup with conflict visibility, managed
  block installation, automatic reload, and rollback on configuration errors.

### Fixed
- Made settings dropdowns close reliably when the open trigger is tapped again.

## [0.3.0] - 2026-08-29

### Fixed
- Removed the bar widget's duplicate IPC registration and retained the legacy
  short service target from the single background service.
- Routed QML actions through the executable `flowctl` dispatcher with
  per-process busy guards and strict CLI argument validation.
- Hardened XDG/runtime state and recording markers, rejected unsupported model
  IDs, removed orphaned audio, and stopped writing transcript text to logs.
- Updated Gemini 3.5 Transcribe to use the documented Interactions API and
  explicit WAV input, fixing empty responses reported as "No speech detected".
- Reduced the model selector to `whisper-base.en`, `gemini-3.5-transcribe`, and
  `gemini-3.7-flash`.
- Isolated automated tests from live user configuration and expanded coverage
  for process identity, credentials, injection failures, and recorder races.

## [0.2.0] - 2026-08-29

### Added
- **Omarchy Overlay Integration**: Declared `overlay` kind in `manifest.json` pointing to `Pill.qml`.
- **Unified CLI (`flowctl`)**: Full desktop keybinding and scripting tool with `toggle`, `toggle-submit`, `pause`, `cancel`, `status`, and `model` commands.
- **XDG Directory Compliance**: Standardized configuration under `~/.config/omarchy-flow/` and runtime files under `$XDG_RUNTIME_DIR/omarchy-flow/`.
- **Model Expansion**: Added support for Gemini 3.5 Transcribe (dedicated ultra-fast audio transcription) and Gemini 3.7 Flash.
- **Automated Test Suite**: Added `tests/run.sh` and `tests/test_backend.py` covering schema validation, qmllint, backend state, and CLI commands.
- **Dynamic Virtual Environment Discovery**: Automatically locates Python site-packages in active virtual environments without hardcoded user paths.

### Changed
- Refactored `Pill.qml` root to `Item` with `PanelWindow` on `WlrLayer.Overlay`.
- Enhanced `BarWidget.qml` with background state polling and pause indicators.
- Expanded `Service.qml` IPC interface.

## [0.1.0] - 2026-08-29

### Added
- Initial proof-of-concept release with floating HUD pill and Gemini dictation backend.
