# Omarchy Flow 🌊

> System-wide voice dictation HUD pill and AI speech-to-text / speech-to-action engine for **Omarchy** (Hyprland + Quickshell + Wayland).

![Omarchy Flow Preview](assets/pill_restored.png)

---

## ✨ Features

- 🎙️ **Floating Glassmorphic HUD Pill**: High-performance Wayland layer HUD (`Quickshell.Wayland.WlrLayershell`) floating non-intrusively above active windows.
- 🌈 **Dynamic Audio Waveform**: Real-time 5-color animated equalizer visualizer for active voice recording.
- ⚡ **Focused Speech Models**: Switch between local Whisper `base.en` and the two supported Google Gemini transcription models.
- ⌨️ **System-Wide Keybindings**: Start, toggle, pause, or auto-submit dictation anywhere in your desktop environment.
- 🧩 **Omarchy Bar Widget**: Theme-adaptive Flow mark with live recording state, a full settings menu, and left/right click controls.
- ⚙️ **Settings Hub**: Configure the default model, toggle completion, clipboard behavior, audio input, HUD position, waveform visibility, global shortcuts, diagnostics, and privacy details.
- 🔒 **Secure Credential Resolution**: Automatic API key discovery from environment variables, Secret Service/GNOME Keyring, and private XDG config files.

## 📦 Install

```sh
omarchy plugin add https://github.com/EF-Code/omarchy-flow.git --enable
```

## ⚙️ Configure

```sh
# Place the widget in your bar
omarchy bar move io.github.ef-code.omarchy-flow --section right
```

Left-click the Flow mark to open the action menu. Choose **Settings** to
configure Flow without editing files. The settings hub includes editable
Hyprland shortcuts, a microphone source picker, a short microphone test,
dependency diagnostics, and HUD controls. Right-click remains the quick
recording action.

### Supported provider boundary

Flow currently supports only two transcription providers:

- **Local:** Voxtype running Whisper `base.en` entirely on the computer.
- **Cloud:** Google Gemini using `gemini-3.5-transcribe` or
  `gemini-3.7-flash`.

The model list is intentionally allowlisted. Arbitrary Gemini IDs, other API
providers, and custom local model IDs cannot be added through the settings
menu or configuration files yet; unsupported IDs are rejected.

### Configure local Whisper

Local transcription requires `ffmpeg`, `voxtype`, and `wtype`. `wl-copy` is
optional unless **Copy transcript to clipboard** is enabled.

Download the local model through Voxtype:

```sh
voxtype setup model
```

Choose the **Whisper** engine and the **base.en** model. Confirm that it is
available with:

```sh
voxtype setup model --list
```

Then open **Flow → Settings → Speech & behavior** and select
**Local Whisper (base.en)**. Flow explicitly requests Voxtype's `base.en`
model, so changing Voxtype's default model does not silently change the model
shown by Flow. Local audio never leaves the computer.

### Configure Gemini

Gemini transcription requires a current `google-genai` package in the Python
environment selected by `scripts/flowctl`. Flow checks, in order,
`OMARCHY_FLOW_PYTHON`, the active virtual environment, common user virtual
environments, and finally `python3`. If a user virtual environment does not
already exist, a typical setup is:

```sh
python3 -m venv "$HOME/.venv"
"$HOME/.venv/bin/python" -m pip install --upgrade google-genai
```

Store the API key in Secret Service/GNOME Keyring without putting it in shell
history:

```sh
secret-tool store --label="Omarchy Flow Gemini API key" service gemini account default
```

The command prompts for the key securely. As a file-based fallback:

```sh
FLOW_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy-flow"
install -d -m 700 "$FLOW_CONFIG"
install -m 600 /dev/null "$FLOW_CONFIG/gemini_api_key"
${EDITOR:-nano} "$FLOW_CONFIG/gemini_api_key"
```

Put only the API key in that file. Flow refuses group-readable or
world-readable key files.

`GEMINI_API_KEY` is also supported, but the variable must be present in the
environment of the running Omarchy shell. Exporting it in a terminal after the
shell has started does not update the shell process; the keyring or private
file is more reliable for desktop use.

Select either Gemini model in **Flow → Settings → Speech & behavior**, then
open **Diagnostics**. The Google Gen AI SDK and Gemini API key checks should
both show as ready. API keys and transcript text are never written to Flow's
log.

The headless service target is
`io.github.ef-code.omarchy-flow.service`; the short
`io.github.ef-code.omarchy-flow` target remains available for compatibility.
The HUD accepts both `io.github.ef-code.omarchy-flow.pill` and the legacy
`geminipill` target.

## 🗑️ Remove

If Flow shortcuts are installed, remove them first from
**Flow → Settings → Keyboard shortcuts → Remove installed shortcuts**. The CLI
equivalent is:

```sh
"${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/io.github.ef-code.omarchy-flow/scripts/flowctl" remove-hotkeys
omarchy plugin remove io.github.ef-code.omarchy-flow
```

This removes only Flow's marked bindings and preserves every unrelated
Hyprland shortcut. Omarchy's plugin remover does not run plugin-specific
uninstall hooks, so this cleanup must happen before removing the plugin folder.

---

## 🤖 Supported Models

| Model ID | Provider | Description |
| :--- | :--- | :--- |
| `whisper-base.en` | Local (Voxtype / Whisper) | Offline English transcription using the downloaded Voxtype `base.en` model. |
| `gemini-3.5-transcribe` | Google Gemini API | Dedicated cloud audio transcription through the Interactions API. |
| `gemini-3.7-flash` | Google Gemini API | Cloud speech transcription through Gemini content generation. |

---

## 🚀 Keyboard shortcuts

Open **Flow → Settings → Keyboard shortcuts**, edit the shortcuts if needed,
and choose **Apply shortcuts**. Flow writes a clearly marked managed block to
Omarchy's Hyprland Lua bindings, checks for conflicts, reloads Hyprland, and
rolls the change back if Hyprland reports a configuration error.

When Flow updates, it refreshes an existing Flow-managed block to the current
IPC commands. It does not install shortcuts automatically for users who have
not enabled them.

From a plugin checkout, the same saved shortcuts can be installed with:

```sh
./scripts/flowctl apply-hotkeys
```

---

## 🛠️ CLI Interface (`flowctl`)

Omarchy Flow includes a standalone CLI dispatcher for shell automation and scripts:

```sh
# Toggle voice dictation recording
./scripts/flowctl toggle

# Record and auto-submit (press Enter after typing)
./scripts/flowctl toggle-submit

# Pause / resume active recording
./scripts/flowctl pause

# Discard recording
./scripts/flowctl cancel

# Query current state (JSON)
./scripts/flowctl status

# Get or set active model
./scripts/flowctl model gemini-3.5-transcribe
./scripts/flowctl model whisper-base.en

# List all available models
./scripts/flowctl list-models

# Remove Flow's managed shortcuts before uninstalling
./scripts/flowctl remove-hotkeys
```

---

## 📂 Architecture

- **`Pill.qml`**: Floating liquid-glass HUD pill overlay (`WlrLayer.Overlay`).
- **`BarWidget.qml`**: Status bar widget with reactive status indicator.
- **`SettingsView.qml`**: Settings hub for behavior, shortcuts, audio/privacy, HUD, diagnostics, and about information.
- **`Service.qml`**: Background Quickshell service hosting the system IPC target.
- **`scripts/gemini-dictate.py`**: Audio recording, local VAD, Whisper / Gemini transcription engine.
- **`scripts/flowctl`**: Command-line dispatcher and Hyprland keybinding endpoint.
- **`manifest.json`**: Omarchy plugin manifest.

---

## 🧪 Testing & Validation

```sh
# Run full automated validation suite
bash tests/run.sh
```

The suite validates the manifest, installed Omarchy QML imports, backend state
and transcription dispatch, isolated XDG paths, CLI argument handling, Python
syntax, portability, and shell scripts. It does not start a real recorder,
send audio to Google, or type into the focused application.

---

## 📄 License

MIT © [EF-Code](https://github.com/EF-Code)
