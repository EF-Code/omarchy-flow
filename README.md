# Omarchy Flow

Omarchy Flow is a system-wide voice dictation plugin for Omarchy. It records
speech from a selected microphone, transcribes it with local Whisper or Google
Gemini, and types the result into the focused application.

| Dark application | Desktop |
| --- | --- |
| ![Omarchy Flow over a dark application](assets/preview-dark.png) | ![Omarchy Flow over the desktop](assets/preview-desktop.png) |

## Features

- A compact dictation pill with recording, pause, submit, and cancel controls
- Local English transcription with Voxtype and Whisper `base.en`
- Cloud transcription with two supported Google Gemini models
- A theme-adaptive bar widget with quick actions and settings
- Configurable microphone input, transcript handling, HUD position, and global shortcuts
- Dependency and microphone diagnostics from the settings panel
- API key lookup through Secret Service, a private configuration file, or the shell environment

## Requirements

Flow requires Omarchy with the current Quickshell-based shell. All
transcription modes require Python 3, `ffmpeg`, and `wtype`. Install `wl-copy`
if transcripts should also be copied to the clipboard.

The local model additionally requires Voxtype and its Whisper `base.en` model.
Gemini requires the `google-genai` Python package and a Gemini API key.

## Installation

```sh
omarchy plugin add https://github.com/EF-Code/omarchy-flow.git --enable
omarchy bar move io.github.ef-code.omarchy-flow --section right
```

The bar widget opens Flow's action menu with a left click. Right-clicking the
widget starts or stops dictation. Open **Settings** from the action menu to
choose a model, select a microphone, configure the pill, and install keyboard
shortcuts.

## Supported models

| Model ID | Provider | Operation |
| --- | --- | --- |
| `whisper-base.en` | Voxtype and Whisper | Local, offline English transcription with `base.en` |
| `gemini-3.5-transcribe` | Google Gemini API | Cloud transcription through the Interactions API |
| `gemini-3.7-flash` | Google Gemini API | Cloud transcription through content generation |

Flow accepts only these model IDs. Other Gemini models, API providers, and
local model IDs are not currently supported.

## Local Whisper setup

Install Voxtype and download the Whisper `base.en` model:

```sh
voxtype setup model
```

Choose the Whisper engine and `base.en`. Verify the installation with:

```sh
voxtype setup model --list
```

Open **Flow > Settings > Speech & behavior** and select **Local Whisper
(base.en)**. Flow requests `base.en` explicitly, regardless of the default
model configured in Voxtype. Audio processed by this mode remains on the
computer.

## Gemini setup

Flow uses the first suitable Python interpreter in this order:

1. `OMARCHY_FLOW_PYTHON`
2. The active virtual environment
3. A supported user virtual environment
4. `python3` on `PATH`

If needed, create a virtual environment and install the Google Gen AI SDK:

```sh
python3 -m venv "${HOME}/.venv"
"${HOME}/.venv/bin/python" -m pip install --upgrade google-genai
```

The recommended credential method is Secret Service, provided by tools such as
GNOME Keyring. This command prompts for the API key without placing it in shell
history:

```sh
secret-tool store --label="Omarchy Flow Gemini API key" service gemini account default
```

Flow also accepts a private key file:

```sh
FLOW_CONFIG="${XDG_CONFIG_HOME:-${HOME}/.config}/omarchy-flow"
install -d -m 700 "$FLOW_CONFIG"
install -m 600 /dev/null "$FLOW_CONFIG/gemini_api_key"
${EDITOR:-nano} "$FLOW_CONFIG/gemini_api_key"
```

The file must contain only the API key. Flow rejects key files that are
readable by the group or other users.

`GEMINI_API_KEY` is supported when it is already present in the environment of
the running Omarchy shell. Exporting it in a terminal after the shell starts
does not update the shell process, so Secret Service or the private file is
usually more reliable.

After selecting a Gemini model under **Speech & behavior**, open
**Diagnostics** and confirm that the Google Gen AI SDK and Gemini API key are
reported as ready. Flow does not write API keys or transcript text to its log.

## Keyboard shortcuts

Open **Flow > Settings > Keyboard shortcuts** to edit and apply the shortcuts.
Flow checks for conflicts, writes a marked block to the user's Hyprland Lua
bindings, reloads Hyprland, and restores the previous file if the new
configuration fails validation.

Shortcuts are not installed automatically. Existing Flow-managed shortcuts are
migrated to current IPC commands when the plugin starts.

The same configuration can be applied from a plugin checkout:

```sh
./scripts/flowctl apply-hotkeys
```

## Command-line interface

`scripts/flowctl` exposes the recording and configuration operations used by
the bar widget and keyboard shortcuts.

```sh
./scripts/flowctl toggle                  # Start or stop dictation
./scripts/flowctl toggle-submit           # Stop, type the transcript, and press Enter
./scripts/flowctl pause                   # Pause or resume recording
./scripts/flowctl cancel                  # Discard the active recording
./scripts/flowctl status                  # Print recording state as JSON
./scripts/flowctl list-models             # List supported models
./scripts/flowctl model                    # Print the selected model
./scripts/flowctl model whisper-base.en    # Select a model
./scripts/flowctl doctor                  # Check dependencies and configuration
./scripts/flowctl remove-hotkeys          # Remove Flow-managed shortcuts
```

The primary service IPC target is
`io.github.ef-code.omarchy-flow.service`. Compatibility targets remain
available for earlier Flow installations.

## Uninstallation

Remove Flow's managed shortcuts before removing the plugin. Use **Flow >
Settings > Keyboard shortcuts > Remove installed shortcuts**, or run:

```sh
"${XDG_CONFIG_HOME:-${HOME}/.config}/omarchy/plugins/io.github.ef-code.omarchy-flow/scripts/flowctl" remove-hotkeys
omarchy plugin remove io.github.ef-code.omarchy-flow
```

The shortcut cleanup removes only Flow's marked bindings. Omarchy's plugin
removal command does not run plugin-specific uninstall hooks.

## Development and validation

The main components are:

| Path | Purpose |
| --- | --- |
| `Pill.qml` | Layer-shell dictation pill |
| `BarWidget.qml` | Bar widget and action menu |
| `SettingsView.qml` | Plugin settings interface |
| `Service.qml` | Background service and IPC endpoint |
| `scripts/gemini-dictate.py` | Recording and transcription backend |
| `scripts/flowctl` | CLI and Hyprland shortcut target |
| `manifest.json` | Omarchy plugin metadata |

Run the repository validation suite with:

```sh
bash tests/run.sh
```

The suite checks the manifest, QML imports, backend state handling,
transcription dispatch, isolated configuration paths, CLI arguments, Python
syntax, portability, and shell scripts. It does not make a live Gemini request,
record microphone audio, or type into an application.

## License

[MIT](LICENSE) Copyright (c) EF-Code
