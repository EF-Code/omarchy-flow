#!/usr/bin/env python3
"""
Omarchy Flow — Speech Dictation & AI Transcription Backend Engine
Handles audio recording, VAD, local Whisper / Gemini Cloud transcription,
state coordination, and IPC signaling to the Quickshell HUD pill and Omarchy bar.
"""

import os
import sys
import re
import time
import json
import copy
import glob
import contextlib
import fcntl
import signal
import stat
import subprocess
import datetime
import tempfile
import warnings
import shutil
import importlib.util

# Dynamically discover and include virtual environment site-packages (e.g. ~/.venv)
def _ensure_venv_packages():
    candidates = [
        os.environ.get("VIRTUAL_ENV"),
        os.path.expanduser("~/.venv"),
        os.path.expanduser("~/.local/share/venvs/default"),
    ]
    # Insert lower-priority locations first so the active environment remains
    # first on sys.path when more than one local environment exists.
    for cand in reversed(candidates):
        if not cand:
            continue
        # Search for site-packages inside candidates
        site_patterns = [
            os.path.join(cand, "lib", "python*", "site-packages"),
            os.path.join(cand, "lib64", "python*", "site-packages"),
        ]
        for pattern in site_patterns:
            for site_dir in glob.glob(pattern):
                if os.path.isdir(site_dir) and site_dir not in sys.path:
                    sys.path.insert(0, site_dir)

_ensure_venv_packages()

# Suppress google-genai AFC warnings
warnings.filterwarnings("ignore", category=UserWarning)

def _xdg_home(variable, fallback):
    value = os.environ.get(variable) or fallback
    expanded = os.path.expanduser(value)
    if not os.path.isabs(expanded):
        expanded = os.path.expanduser(fallback)
    return os.path.abspath(expanded)


def _runtime_home():
    configured = os.environ.get("XDG_RUNTIME_DIR")
    if configured:
        expanded = os.path.expanduser(configured)
        if os.path.isabs(expanded):
            return os.path.abspath(expanded)
    # A shared /tmp directory would allow another local user to read or
    # replace recordings. Keep the fallback user-scoped and private.
    return os.path.join(tempfile.gettempdir(), f"omarchy-flow-{os.getuid()}")


def _ensure_private_dir(path):
    if os.path.islink(path):
        raise OSError(f"refusing symlink directory: {path}")
    os.makedirs(path, mode=0o700, exist_ok=True)
    try:
        if os.stat(path).st_uid == os.getuid():
            os.chmod(path, 0o700)
    except OSError:
        pass


# XDG Standard Directories
XDG_CONFIG_HOME = _xdg_home("XDG_CONFIG_HOME", "~/.config")
XDG_RUNTIME_DIR = _runtime_home()
XDG_STATE_HOME = _xdg_home("XDG_STATE_HOME", "~/.local/state")

CONFIG_DIR = os.path.join(XDG_CONFIG_HOME, "omarchy-flow")
LEGACY_CONFIG_DIR = os.path.join(XDG_CONFIG_HOME, "gemini-pill")
RUNTIME_DIR = os.path.join(XDG_RUNTIME_DIR, "omarchy-flow")
STATE_DIR = os.path.join(XDG_STATE_HOME, "omarchy-flow")

LOG_FILE = os.path.join(STATE_DIR, "flow.log")
TEMP_AUDIO = os.path.join(RUNTIME_DIR, "recording.wav")
PID_FILE = os.path.join(RUNTIME_DIR, "recording.pid")
STATE_FILE = os.path.join(RUNTIME_DIR, "state.json")
LOCK_FILE = os.path.join(RUNTIME_DIR, "operation.lock")
MODEL_FILE = os.path.join(CONFIG_DIR, "selected_model.txt")
LEGACY_MODEL_FILE = os.path.join(LEGACY_CONFIG_DIR, "selected_model.txt")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")

# Legacy compatibility files. They are only read/written when they are owned
# by the current user and are never followed as symlinks.
LEGACY_RUNTIME_DIR = tempfile.gettempdir()
LEGACY_TEMP_AUDIO = os.path.join(LEGACY_RUNTIME_DIR, "gemini_dictation.wav")
LEGACY_PID_FILE = os.path.join(LEGACY_RUNTIME_DIR, "gemini_dictation.pid")
LEGACY_STATE_FILE = os.path.join(LEGACY_RUNTIME_DIR, "gemini_dictation.state")

LOCAL_MODEL_ID = "whisper-base.en"
LOCAL_VOXTYPE_MODEL = "base.en"

SUPPORTED_MODELS = [
    {"id": LOCAL_MODEL_ID, "name": "Local Whisper (base.en)", "desc": "Local • Offline", "provider": "local"},
    {"id": "gemini-3.5-transcribe", "name": "Gemini 3.5 Transcribe", "desc": "Cloud • Dedicated transcription", "provider": "gemini"},
    {"id": "gemini-3.7-flash", "name": "Gemini 3.7 Flash", "desc": "Cloud • Speech transcription", "provider": "gemini"},
]

DEFAULT_MODEL_ID = SUPPORTED_MODELS[0]["id"]
SUPPORTED_MODEL_IDS = frozenset(model["id"] for model in SUPPORTED_MODELS)

DEFAULT_SETTINGS = {
    "toggle_action": "transcribe",
    "audio_source": "default",
    "copy_to_clipboard": True,
    "hud_enabled": True,
    "hud_position": "bottom",
    "waveform_enabled": True,
    "hotkeys": {
        "toggle": "SUPER + ALT + V",
        "toggle_submit": "SUPER + ALT + SHIFT + V",
        "push_to_talk": "F6",
        "pause": "SUPER + ALT + P",
        "cancel": "SUPER + ALT + C",
    },
}

HOTKEY_MODIFIERS = {
    "SUPER": "SUPER",
    "META": "SUPER",
    "WIN": "SUPER",
    "MOD4": "SUPER",
    "CTRL": "CTRL",
    "CONTROL": "CTRL",
    "ALT": "ALT",
    "SHIFT": "SHIFT",
}
HOTKEY_MODMASKS = {"SHIFT": 1, "CTRL": 4, "ALT": 8, "SUPER": 64}
HOTKEY_IDS = (
    "toggle",
    "toggle_submit",
    "push_to_talk",
    "pause",
    "cancel",
)
HOTKEY_MARKER_START = "-- >>> omarchy-flow managed hotkeys >>>"
HOTKEY_MARKER_END = "-- <<< omarchy-flow managed hotkeys <<<"

for directory in [CONFIG_DIR, RUNTIME_DIR, STATE_DIR]:
    try:
        _ensure_private_dir(directory)
    except OSError:
        # Individual operations report failures through their normal error
        # paths. Importing the module must remain safe in a read-only setup.
        pass


def _owned_path(path, allow_symlink=False):
    try:
        info = os.lstat(path)
    except OSError:
        return None
    if info.st_uid != os.getuid():
        return None
    if stat.S_ISLNK(info.st_mode) and not allow_symlink:
        return None
    if not (stat.S_ISREG(info.st_mode) or (allow_symlink and stat.S_ISLNK(info.st_mode))):
        return None
    return info


def _read_owned_text(path):
    if _owned_path(path) is None:
        return None
    fd = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode):
            return None
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = None
            return handle.read()
    except (OSError, UnicodeError):
        return None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def _remove_owned_path(path):
    # Unlinking a symlink itself is safe, while following one is not. This is
    # intentionally limited to files owned by this user.
    if _owned_path(path, allow_symlink=True) is None:
        return False
    try:
        os.unlink(path)
        return True
    except OSError:
        return False


def _write_private_text(path, content):
    parent = os.path.dirname(path) or "."
    if not os.path.isdir(parent) or os.path.islink(parent):
        raise OSError(f"private parent directory unavailable: {parent}")

    temporary_path = None
    try:
        fd, temporary_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(path)}.", dir=parent
        )
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        # Replacing the final path also replaces an attacker-created symlink;
        # no write ever follows that symlink.
        os.replace(temporary_path, path)
        temporary_path = None
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if temporary_path:
            _remove_owned_path(temporary_path)


def _coerce_bool(value, fallback):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return fallback


def _normalise_audio_source(value):
    if value is None:
        return None
    source = str(value).strip()
    if source == "default":
        return source
    if not source or len(source) > 255 or not re.fullmatch(r"[A-Za-z0-9_.:@%/-]+", source):
        return None
    return source


def _normalise_hotkey(value):
    raw = str(value or "").strip().upper()
    if not raw:
        return ""

    parts = [part.strip() for part in raw.split("+")]
    if not parts or any(not part for part in parts):
        return None

    modifiers = []
    for part in parts[:-1]:
        modifier = HOTKEY_MODIFIERS.get(part)
        if modifier is None or modifier in modifiers:
            return None
        modifiers.append(modifier)

    key = parts[-1]
    if key in HOTKEY_MODIFIERS or not re.fullmatch(r"[A-Z0-9][A-Z0-9:_-]*", key):
        return None

    ordered_modifiers = [
        modifier for modifier in ("SUPER", "CTRL", "ALT", "SHIFT") if modifier in modifiers
    ]
    return " + ".join(ordered_modifiers + [key])


def _normalise_settings(raw):
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    if not isinstance(raw, dict):
        return settings

    toggle_action = str(raw.get("toggle_action", settings["toggle_action"])).strip().lower()
    if toggle_action in {"transcribe", "submit"}:
        settings["toggle_action"] = toggle_action

    audio_source = _normalise_audio_source(raw.get("audio_source", settings["audio_source"]))
    if audio_source:
        settings["audio_source"] = audio_source

    for key in ["copy_to_clipboard", "hud_enabled", "waveform_enabled"]:
        settings[key] = _coerce_bool(raw.get(key), settings[key])

    hud_position = str(raw.get("hud_position", settings["hud_position"])).strip().lower()
    if hud_position in {"top", "bottom"}:
        settings["hud_position"] = hud_position

    raw_hotkeys = raw.get("hotkeys")
    if isinstance(raw_hotkeys, dict):
        for hotkey_id in HOTKEY_IDS:
            if hotkey_id not in raw_hotkeys:
                continue
            normalised = _normalise_hotkey(raw_hotkeys[hotkey_id])
            if normalised is not None:
                settings["hotkeys"][hotkey_id] = normalised

    return settings


def get_settings():
    raw = _read_owned_text(SETTINGS_FILE)
    if raw is None:
        return copy.deepcopy(DEFAULT_SETTINGS)
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        log("Ignoring invalid settings file")
        return copy.deepcopy(DEFAULT_SETTINGS)
    return _normalise_settings(parsed)


def _write_settings(settings):
    _ensure_private_dir(CONFIG_DIR)
    _write_private_text(SETTINGS_FILE, json.dumps(_normalise_settings(settings), separators=(",", ":")))


def set_setting(key, value):
    settings = get_settings()
    if key == "toggle_action":
        normalised = str(value).strip().lower()
        if normalised not in {"transcribe", "submit"}:
            return False
        settings[key] = normalised
    elif key == "audio_source":
        normalised = _normalise_audio_source(value)
        if normalised is None:
            return False
        settings[key] = normalised
    elif key in {"copy_to_clipboard", "hud_enabled", "waveform_enabled"}:
        normalised = _coerce_bool(value, None)
        if normalised is None:
            return False
        settings[key] = normalised
    elif key == "hud_position":
        normalised = str(value).strip().lower()
        if normalised not in {"top", "bottom"}:
            return False
        settings[key] = normalised
    elif key.startswith("hotkeys."):
        hotkey_id = key.split(".", 1)[1]
        if hotkey_id not in HOTKEY_IDS:
            return False
        normalised = _normalise_hotkey(value)
        if normalised is None:
            return False
        settings["hotkeys"][hotkey_id] = normalised
    else:
        return False

    try:
        _write_settings(settings)
    except OSError as error:
        log(f"Error updating settings: {type(error).__name__}")
        return False
    return True


def reset_settings():
    try:
        bindings_path = _bindings_file()
        bindings_content = _read_owned_text(bindings_path) or ""
        if HOTKEY_MARKER_START in bindings_content and HOTKEY_MARKER_END in bindings_content:
            return apply_hotkeys(copy.deepcopy(DEFAULT_SETTINGS["hotkeys"]))
        _write_settings(DEFAULT_SETTINGS)
    except OSError as error:
        log(f"Error resetting settings: {type(error).__name__}")
        return False
    return True


def list_audio_sources():
    sources = [{"id": "default", "name": "System default"}]
    try:
        result = subprocess.run(
            ["pactl", "-f", "json", "list", "sources"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            return sources
        parsed = json.loads(result.stdout or "[]")
    except (OSError, subprocess.SubprocessError, TypeError, ValueError):
        return sources

    if not isinstance(parsed, list):
        return sources
    seen = {"default"}
    for source in parsed:
        if not isinstance(source, dict):
            continue
        properties = source.get("properties")
        media_class = properties.get("media.class") if isinstance(properties, dict) else None
        if media_class and media_class != "Audio/Source":
            continue
        name = str(source.get("name") or "").strip()
        if not name or name in seen or _normalise_audio_source(name) is None:
            continue
        seen.add(name)
        description = str(source.get("description") or name).strip()
        sources.append({"id": name, "name": description})
    return sources


def _settings_hotkeys(overrides=None):
    settings = get_settings()
    hotkeys = dict(settings["hotkeys"])
    if overrides is not None:
        if not isinstance(overrides, dict):
            return None
        for hotkey_id in HOTKEY_IDS:
            if hotkey_id not in overrides:
                continue
            normalised = _normalise_hotkey(overrides[hotkey_id])
            if normalised is None:
                return None
            hotkeys[hotkey_id] = normalised

    assigned = [value for value in hotkeys.values() if value]
    if len(assigned) != len(set(assigned)):
        return None
    return hotkeys


def _bindings_file():
    return os.path.join(XDG_CONFIG_HOME, "hypr", "bindings.lua")


def _hotkey_modmask(shortcut):
    parts = [part.strip() for part in shortcut.split("+")]
    if not parts:
        return None, None
    mask = 0
    for modifier in parts[:-1]:
        if modifier not in HOTKEY_MODMASKS:
            return None, None
        mask |= HOTKEY_MODMASKS[modifier]
    return mask, parts[-1]


def _hotkey_conflicts(hotkeys):
    try:
        result = subprocess.run(
            ["hyprctl", "-j", "binds"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            return []
        bindings = json.loads(result.stdout or "[]")
    except (OSError, subprocess.SubprocessError, TypeError, ValueError):
        return []

    conflicts = []
    for hotkey_id, shortcut in hotkeys.items():
        if not shortcut:
            continue
        mask, key = _hotkey_modmask(shortcut)
        if mask is None:
            continue
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            if binding.get("modmask") != mask or str(binding.get("key", "")).upper() != key:
                continue
            description = str(binding.get("description") or "Unlabelled binding")
            if description.startswith("Flow:"):
                continue
            conflicts.append(
                {
                    "action": hotkey_id,
                    "shortcut": shortcut,
                    "description": description,
                    "release": binding.get("release") is True,
                }
            )
    return conflicts


def hotkeys_status():
    settings = get_settings()
    bindings_path = _bindings_file()
    content = _read_owned_text(bindings_path) or ""
    return {
        "installed": HOTKEY_MARKER_START in content and HOTKEY_MARKER_END in content,
        "hotkeys": settings["hotkeys"],
        "conflicts": _hotkey_conflicts(settings["hotkeys"]),
    }


def _lua_string(value):
    return json.dumps(str(value), ensure_ascii=False)


def _hotkey_block(hotkeys):
    commands = {
        "toggle": ("Flow: Toggle dictation", "toggle"),
        "toggle_submit": ("Flow: Dictate & submit", "toggleSubmit"),
        "pause": ("Flow: Pause / resume", "pause"),
        "cancel": ("Flow: Cancel recording", "cancel"),
    }
    lines = [
        HOTKEY_MARKER_START,
        "-- Managed by Omarchy Flow. Configure these in the Flow settings menu.",
    ]
    for hotkey_id in HOTKEY_IDS:
        shortcut = hotkeys.get(hotkey_id, "")
        if not shortcut:
            continue
        lines.append(f"hl.unbind({_lua_string(shortcut)})")
        if hotkey_id == "push_to_talk":
            lines.append(
                f'o.bind({_lua_string(shortcut)}, "Flow: Push to talk", '
                '"omarchy-shell io.github.ef-code.omarchy-flow.service start")'
            )
            lines.append(
                f'o.bind({_lua_string(shortcut)}, "Flow: Push to talk (release)", '
                '"omarchy-shell io.github.ef-code.omarchy-flow.service stop", '
                "{ release = true })"
            )
            continue
        description, action = commands[hotkey_id]
        lines.append(
            f'o.bind({_lua_string(shortcut)}, {_lua_string(description)}, '
            f'"omarchy-shell io.github.ef-code.omarchy-flow.service {action}")'
        )
    lines.append(HOTKEY_MARKER_END)
    return "\n".join(lines)


def _without_hotkey_block(content):
    pattern = re.compile(
        rf"(?ms)^{re.escape(HOTKEY_MARKER_START)}\n.*?^{re.escape(HOTKEY_MARKER_END)}\n?"
    )
    return pattern.sub("", content)


def _restore_bindings(path, previous):
    try:
        if previous is None:
            _remove_owned_path(path)
        else:
            _write_private_text(path, previous)
        subprocess.run(["hyprctl", "reload"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def apply_hotkeys(overrides=None):
    hotkeys = _settings_hotkeys(overrides)
    if hotkeys is None:
        return False

    bindings_path = _bindings_file()
    bindings_parent = os.path.dirname(bindings_path)
    if os.path.islink(bindings_parent):
        return False
    try:
        os.makedirs(bindings_parent, mode=0o700, exist_ok=True)
    except OSError:
        return False

    previous = _read_owned_text(bindings_path)
    if previous is None and os.path.lexists(bindings_path):
        return False
    base = previous or "-- Omarchy Flow managed bindings\n"
    new_content = _without_hotkey_block(base).rstrip() + "\n\n" + _hotkey_block(hotkeys) + "\n"
    old_settings = get_settings()

    try:
        candidate_settings = copy.deepcopy(old_settings)
        candidate_settings["hotkeys"] = hotkeys
        _write_settings(candidate_settings)
        _write_private_text(bindings_path, new_content)
        reload_result = subprocess.run(
            ["hyprctl", "reload"], capture_output=True, text=True, timeout=5
        )
        if reload_result.returncode != 0:
            raise RuntimeError("hyprctl reload failed")
        errors_result = subprocess.run(
            ["hyprctl", "configerrors"], capture_output=True, text=True, timeout=5
        )
        if errors_result.returncode != 0 or (errors_result.stdout + errors_result.stderr).strip():
            raise RuntimeError("Hyprland reported configuration errors")
    except (OSError, subprocess.SubprocessError, RuntimeError):
        _restore_bindings(bindings_path, previous)
        try:
            _write_settings(old_settings)
        except OSError:
            pass
        return False
    return True


def run_audio_test():
    if not shutil.which("ffmpeg"):
        return {"ok": False, "message": "ffmpeg is not installed"}
    try:
        _ensure_private_dir(RUNTIME_DIR)
        fd, target = tempfile.mkstemp(prefix=".audio-test-", suffix=".wav", dir=RUNTIME_DIR)
        os.close(fd)
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-f", "pulse",
                "-i", get_settings()["audio_source"], "-t", "0.5", "-ar", "16000",
                "-ac", "1", target,
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        size = os.path.getsize(target) if os.path.exists(target) else 0
        ok = result.returncode == 0 and size >= 1000
        return {"ok": ok, "message": "Microphone capture works" if ok else "Microphone capture failed"}
    except (OSError, subprocess.SubprocessError):
        return {"ok": False, "message": "Microphone capture failed"}
    finally:
        if "target" in locals():
            _remove_owned_path(target)


def diagnostics():
    settings = get_settings()
    selected_model = get_selected_model()
    checks = []

    def add_tool(tool, label, required):
        path = shutil.which(tool)
        checks.append({
            "id": tool,
            "label": label,
            "ok": bool(path),
            "detail": "Ready" if path else "Not found",
            "required": required,
        })

    add_tool("ffmpeg", "Audio recorder", True)
    add_tool("wtype", "Text insertion", True)
    add_tool("wl-copy", "Clipboard integration", False)
    if selected_model == "whisper-base.en":
        add_tool("voxtype", "Local Whisper", True)
    else:
        try:
            sdk_ready = importlib.util.find_spec("google.genai") is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            sdk_ready = False
        checks.append({
            "id": "google-genai",
            "label": "Google Gen AI SDK",
            "ok": sdk_ready,
            "detail": "Ready" if sdk_ready else "Not found",
            "required": True,
        })
        key_ready = bool(get_gemini_api_key())
        checks.append({
            "id": "gemini-api-key",
            "label": "Gemini API key",
            "ok": key_ready,
            "detail": "Configured" if key_ready else "Not configured",
            "required": True,
        })

    source_ids = {source["id"] for source in list_audio_sources()}
    source_ready = settings["audio_source"] == "default" or settings["audio_source"] in source_ids
    checks.append({
        "id": "audio-source",
        "label": "Audio input",
        "ok": source_ready,
        "detail": "System default" if settings["audio_source"] == "default" else settings["audio_source"],
        "required": True,
    })
    return {"ok": all(check["ok"] for check in checks if check["required"]), "checks": checks}

def log(msg):
    fd = None
    try:
        parent = os.path.dirname(LOG_FILE) or "."
        if not os.path.isdir(parent) or os.path.islink(parent):
            return
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(LOG_FILE, flags, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            fd = None
            handle.write(f"[{datetime.datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def _read_selected_model(path):
    raw = _read_owned_text(path)
    if raw is None:
        return None
    model_id = raw.strip()
    if model_id in SUPPORTED_MODEL_IDS:
        return model_id
    if model_id:
        log("Ignoring unsupported model selection")
    return None

def get_selected_model():
    for fpath in [MODEL_FILE, LEGACY_MODEL_FILE]:
        model_id = _read_selected_model(fpath)
        if model_id:
            return model_id
    return DEFAULT_MODEL_ID

def set_selected_model(model_id):
    model_id = str(model_id).strip()
    if model_id not in SUPPORTED_MODEL_IDS:
        log("Rejected unsupported model selection")
        return False
    try:
        _ensure_private_dir(CONFIG_DIR)
        _write_private_text(MODEL_FILE, model_id + "\n")
        if os.path.isdir(LEGACY_CONFIG_DIR) and not os.path.islink(LEGACY_CONFIG_DIR):
            try:
                _write_private_text(LEGACY_MODEL_FILE, model_id + "\n")
            except OSError as error:
                log(f"Could not mirror selected model to legacy config: {type(error).__name__}")
        log("Selected model updated")
        return True
    except Exception as e:
        log(f"Error updating selected model: {type(e).__name__}")
        return False


def _secret_from_value(value):
    value = str(value).strip()
    if not value:
        return None
    try:
        data = json.loads(value)
    except (TypeError, ValueError):
        data = None
    if isinstance(data, dict):
        token = data.get("token") or data.get("api_key") or data.get("access_token")
        if isinstance(token, str) and token.strip():
            return token.strip()
        if isinstance(token, dict):
            access_token = token.get("access_token")
            if isinstance(access_token, str) and access_token.strip():
                return access_token.strip()
    # Keyring entries are normally opaque strings. Do not print or log them.
    return value if len(value) > 10 else None


def _read_private_secret(path):
    info = _owned_path(path)
    if info is None or info.st_mode & 0o077:
        return None
    return _secret_from_value(_read_owned_text(path) or "")

def get_gemini_api_key():
    """Load a Gemini API key without logging or exposing its value."""
    env_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key

    lookups = [
        ["secret-tool", "lookup", "service", "gemini", "account", "default"],
        ["secret-tool", "lookup", "name", "GEMINI_API_KEY"],
        ["secret-tool", "lookup", "label", "GEMINI_API_KEY"],
        ["secret-tool", "lookup", "service", "gemini"],
    ]
    for args in lookups:
        try:
            res = subprocess.run(args, capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                key = _secret_from_value(res.stdout)
                if key:
                    return key
        except Exception:
            pass

    key_files = [
        os.path.join(CONFIG_DIR, "gemini_api_key"),
        os.path.join(XDG_CONFIG_HOME, "gemini", "api_key"),
        os.path.join(XDG_CONFIG_HOME, "omarchy", "gemini_api_key"),
    ]
    for kf in key_files:
        key = _read_private_secret(kf)
        if key:
            return key

    return None

def pill_ipc(action, *args):
    """Send one HUD IPC call, preferring the canonical namespaced target."""
    clean_env = os.environ.copy()
    clean_env.pop("LD_LIBRARY_PATH", None)

    targets = ["io.github.ef-code.omarchy-flow.pill", "geminipill"]
    config_paths = [
        os.path.join(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy"), "shell"),
        os.path.join(XDG_CONFIG_HOME, "gemini-pill", "shell.qml"),
        None,
    ]
    str_args = [str(a) for a in args]
    for cfg in config_paths:
        if cfg and not os.path.exists(cfg):
            continue
        for target in targets:
            cmd = ["quickshell", "ipc"]
            if cfg:
                cmd.extend(["-p", cfg])
            cmd.extend(["call", target, action, *str_args])
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, env=clean_env, timeout=1.0)
                if res.returncode == 0 and res.stdout.strip() == "ok":
                    return True
            except Exception:
                pass
    return False


def _read_pid(path):
    raw = _read_owned_text(path)
    if raw is None:
        return None
    try:
        pid = int(raw.strip())
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _process_cmdline(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            raw = handle.read()
        return [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]
    except (OSError, UnicodeError):
        return []


def _process_start_ticks(pid):
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as handle:
            stat_line = handle.read()
        closing_name = stat_line.rfind(")")
        if closing_name < 0:
            return None
        fields_after_name = stat_line[closing_name + 2 :].split()
        # /proc/<pid>/stat field 22 (starttime) is index 19 after field 2.
        return int(fields_after_name[19])
    except (OSError, ValueError, IndexError):
        return None


def _process_alive(pid):
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as handle:
            stat_line = handle.read()
        closing_name = stat_line.rfind(")")
        if closing_name >= 0 and stat_line[closing_name + 2 :].split()[0] == "Z":
            return False
    except (OSError, IndexError):
        pass
    return True


def _is_recorder_process(pid):
    if not _process_alive(pid):
        return False
    try:
        if os.stat(f"/proc/{pid}").st_uid != os.getuid():
            return False
    except OSError:
        return False

    args = _process_cmdline(pid)
    if not args or os.path.basename(args[0]) not in {"ffmpeg", "ffmpeg.bin"}:
        return False
    try:
        format_index = args.index("-f")
        input_index = args.index("-i")
        if args[format_index + 1] != "pulse" or not args[input_index + 1]:
            return False
    except (ValueError, IndexError):
        return False

    output_paths = {os.path.abspath(TEMP_AUDIO), os.path.abspath(LEGACY_TEMP_AUDIO)}
    return any(os.path.abspath(arg) in output_paths for arg in args[1:])


def _load_runtime_state():
    raw = _read_owned_text(STATE_FILE)
    if raw is None:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _valid_recording_pids():
    state = _load_runtime_state()
    expected_pid = state.get("pid")
    expected_ticks = state.get("start_ticks")
    valid = []

    for pid_path in [PID_FILE, LEGACY_PID_FILE]:
        pid = _read_pid(pid_path)
        if pid is None:
            if _owned_path(pid_path, allow_symlink=True) is not None:
                _remove_owned_path(pid_path)
            continue
        if pid in valid or not _is_recorder_process(pid):
            _remove_owned_path(pid_path)
            continue

        if expected_pid is not None:
            try:
                if int(expected_pid) != pid:
                    _remove_owned_path(pid_path)
                    continue
            except (TypeError, ValueError):
                _remove_owned_path(pid_path)
                continue
        if expected_ticks is not None:
            current_ticks = _process_start_ticks(pid)
            if current_ticks is None or str(current_ticks) != str(expected_ticks):
                _remove_owned_path(pid_path)
                continue
        valid.append(pid)
    return valid


def _clear_runtime_markers():
    for path in [PID_FILE, LEGACY_PID_FILE, STATE_FILE, LEGACY_STATE_FILE]:
        _remove_owned_path(path)


def _clear_audio_files():
    seen = set()
    for path in [TEMP_AUDIO, LEGACY_TEMP_AUDIO]:
        absolute_path = os.path.abspath(path)
        if absolute_path in seen:
            continue
        seen.add(absolute_path)
        _remove_owned_path(path)


@contextlib.contextmanager
def _operation_lock():
    fd = None
    try:
        parent = os.path.dirname(LOCK_FILE) or "."
        if not os.path.isdir(parent) or os.path.islink(parent):
            raise OSError(f"private lock directory unavailable: {parent}")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(LOCK_FILE, flags, 0o600)
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError as error:
        log(f"Unable to acquire operation lock: {type(error).__name__}")
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        yield False
        return

    try:
        yield True
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass


def is_recording():
    valid = _valid_recording_pids()
    if not valid:
        # A dead recorder must not leave a stale paused state behind.
        _remove_owned_path(STATE_FILE)
        _remove_owned_path(LEGACY_STATE_FILE)
    return bool(valid)

def get_current_state():
    rec = is_recording()
    paused = False
    if rec:
        paused = _load_runtime_state().get("paused") is True
    return {
        "recording": rec,
        "paused": paused,
        "model": get_selected_model(),
    }

def update_runtime_state(status, paused=False, pid=None, start_ticks=None):
    if start_ticks is None and pid:
        start_ticks = _process_start_ticks(pid)
    state_data = {
        "status": status,
        "paused": paused,
        "pid": pid,
        "start_ticks": start_ticks,
        "model": get_selected_model(),
        "timestamp": datetime.datetime.now().isoformat(),
    }
    try:
        _ensure_private_dir(RUNTIME_DIR)
        _write_private_text(STATE_FILE, json.dumps(state_data, separators=(",", ":")))
    except OSError as error:
        log(f"Error updating runtime state: {type(error).__name__}")
    try:
        _write_private_text(LEGACY_STATE_FILE, "paused" if paused else "recording")
    except OSError:
        # The legacy mirror is optional and may be unavailable on a hardened
        # /tmp; the XDG runtime state remains authoritative.
        pass

def _write_pid_markers(pid):
    # The private XDG marker is authoritative. The predictable legacy /tmp
    # marker is best-effort so another local user cannot block recording by
    # pre-creating that compatibility path in a sticky shared directory.
    _write_private_text(PID_FILE, f"{pid}\n")
    if os.path.abspath(PID_FILE) == os.path.abspath(LEGACY_PID_FILE):
        return
    try:
        _write_private_text(LEGACY_PID_FILE, f"{pid}\n")
    except OSError as error:
        log(f"Could not mirror recorder PID to legacy runtime: {type(error).__name__}")


def _mirror_legacy_audio():
    if os.path.abspath(TEMP_AUDIO) == os.path.abspath(LEGACY_TEMP_AUDIO):
        return
    _remove_owned_path(LEGACY_TEMP_AUDIO)
    try:
        # A hard link preserves compatibility without creating a symlink at a
        # predictable /tmp path. Failure is harmless; the XDG path is primary.
        os.link(TEMP_AUDIO, LEGACY_TEMP_AUDIO, follow_symlinks=False)
    except OSError:
        pass


def _start_recording():
    if is_recording():
        log("start called, but already recording")
        return False

    log("Starting audio recording")
    pill_ipc("setListening")
    _clear_audio_files()

    try:
        proc = subprocess.Popen(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "pulse", "-i", get_settings()["audio_source"],
                "-ar", "16000", "-ac", "1",
                TEMP_AUDIO,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            # ffmpeg creates the WAV itself. A private child umask ensures the
            # inode remains owner-only even when it is hard-linked to the
            # optional legacy compatibility path under /tmp.
            umask=0o077,
        )
        time.sleep(0.05)
        if proc.poll() is not None:
            log(f"ffmpeg failed to start with exit code {proc.returncode}")
            _clear_audio_files()
            pill_ipc("setStatus", "Mic Error")
            return False
    except Exception as error:
        log(f"Failed to spawn ffmpeg: {type(error).__name__}")
        pill_ipc("setStatus", "Recorder Error")
        return False

    try:
        _write_pid_markers(proc.pid)
        _mirror_legacy_audio()
        update_runtime_state("recording", paused=False, pid=proc.pid)
    except OSError as error:
        log(f"Failed to persist recording state: {type(error).__name__}")
        _terminate_recorder(proc.pid, signal.SIGTERM)
        _clear_runtime_markers()
        _clear_audio_files()
        pill_ipc("setStatus", "Recorder Error")
        return False

    log(f"Recording started with PID {proc.pid}")
    return True


def start_recording():
    with _operation_lock() as locked:
        return locked and _start_recording()


def _wait_for_process_exit(pid, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_alive(pid):
            return True
        time.sleep(0.05)
    return not _process_alive(pid)


def _terminate_recorder(pid, graceful_signal):
    if not _is_recorder_process(pid):
        return True
    try:
        # SIGCONT is required when the user paused the recorder with SIGSTOP.
        os.kill(pid, signal.SIGCONT)
        os.kill(pid, graceful_signal)
    except OSError:
        return not _process_alive(pid)

    if _wait_for_process_exit(pid, 1.0):
        return True

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    if _wait_for_process_exit(pid, 0.5):
        return True

    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    return _wait_for_process_exit(pid, 0.5)

def _active_recording_pids():
    return _valid_recording_pids()


def toggle_pause():
    with _operation_lock() as locked:
        if not locked:
            return False
        pids = _active_recording_pids()
        if not pids:
            log("toggle_pause called, but not recording")
            return False
        pid = pids[0]
        paused = _load_runtime_state().get("paused") is True
        try:
            os.kill(pid, signal.SIGCONT if paused else signal.SIGSTOP)
            update_runtime_state("recording" if paused else "paused", paused=not paused, pid=pid)
            pill_ipc("setResumed" if paused else "setPaused")
            log("Recording resumed" if paused else "Recording paused")
            return True
        except OSError as error:
            log(f"Error changing recording pause state: {type(error).__name__}")
            return False


def resume_recording():
    with _operation_lock() as locked:
        if not locked:
            return False
        pids = _active_recording_pids()
        if not pids:
            return False
        try:
            os.kill(pids[0], signal.SIGCONT)
            update_runtime_state("recording", paused=False, pid=pids[0])
            pill_ipc("setResumed")
            log("Recording resumed explicitly")
            return True
        except OSError as error:
            log(f"Error resuming recording: {type(error).__name__}")
            return False


def pause_recording():
    with _operation_lock() as locked:
        if not locked:
            return False
        pids = _active_recording_pids()
        if not pids:
            return False
        try:
            os.kill(pids[0], signal.SIGSTOP)
            update_runtime_state("paused", paused=True, pid=pids[0])
            pill_ipc("setPaused")
            log("Recording paused explicitly")
            return True
        except OSError as error:
            log(f"Error pausing recording: {type(error).__name__}")
            return False


def _cancel_recording(pids=None):
    log("Cancelling recording")
    pids = _active_recording_pids() if pids is None else pids
    for pid in pids:
        _terminate_recorder(pid, signal.SIGTERM)
    _clear_runtime_markers()
    _clear_audio_files()
    pill_ipc("hide")
    log("Recording cancelled and discarded")
    return True


def cancel_recording():
    with _operation_lock() as locked:
        return locked and _cancel_recording()


def _audio_target():
    for path in [TEMP_AUDIO, LEGACY_TEMP_AUDIO]:
        info = _owned_path(path)
        if info is None:
            continue
        try:
            if os.path.getsize(path) > 0:
                return path
        except OSError:
            pass
    return None


def _extract_voxtype_text(output):
    clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output or "")
    parts = re.split(r"Transcription completed in [^\n]+", clean, maxsplit=1)
    if len(parts) > 1 and parts[-1].strip():
        return parts[-1].strip()

    lines = []
    for line in clean.splitlines():
        value = line.strip()
        if not value:
            continue
        if re.match(r"^(Loading|Audio format|Processing)\b", value):
            continue
        if re.match(r"^(INFO|WARN|ERROR)(?:\s|:|$)", value):
            continue
        lines.append(value)
    return " ".join(lines).strip()


class MissingApiKeyError(RuntimeError):
    """Raised when a cloud model is selected without a configured API key."""


def _transcribe_local(target_audio):
    result = subprocess.run(
        ["voxtype", "--model", LOCAL_VOXTYPE_MODEL, "transcribe", target_audio],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError("voxtype returned a non-zero exit code")
    return _extract_voxtype_text(result.stdout)


def _transcribe_cloud(target_audio, model_choice):
    from google import genai
    from google.genai import types

    api_key = get_gemini_api_key()
    if not api_key:
        raise MissingApiKeyError

    client = genai.Client(api_key=api_key)
    if model_choice == "gemini-3.5-transcribe":
        # The dedicated transcribe model uses the Interactions API. The legacy
        # Generate Content endpoint can return a stopped candidate with no
        # parts for this model, which is indistinguishable from silence here.
        audio_file = client.files.upload(
            file=target_audio,
            config=types.UploadFileConfig(mime_type="audio/wav"),
        )
        try:
            interaction = client.interactions.create(
                model=model_choice,
                input=[
                    {
                        "type": "audio",
                        "uri": audio_file.uri,
                        "mime_type": "audio/wav",
                    }
                ],
                generation_config={
                    "transcription_config": {
                        "mode": "smart",
                    }
                },
            )
            return (getattr(interaction, "output_text", "") or "").strip()
        finally:
            uploaded_name = getattr(audio_file, "name", "")
            if uploaded_name:
                try:
                    client.files.delete(name=uploaded_name)
                except Exception as error:
                    log(f"Could not delete uploaded audio: {type(error).__name__}")
    else:
        with open(target_audio, "rb") as handle:
            audio_bytes = handle.read()
        response = client.models.generate_content(
            model=model_choice,
            contents=[
                types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"),
                "Transcribe this speech accurately. Clean up disfluencies, remove filler words like ums/ahs, format punctuation and capitalization properly. Return ONLY the transcribed text without quotes or explanations.",
            ],
        )
    return (response.text or "").strip()


def _transcribe_audio(target_audio, model_choice):
    if model_choice == LOCAL_MODEL_ID:
        return _transcribe_local(target_audio)
    if model_choice in SUPPORTED_MODEL_IDS:
        return _transcribe_cloud(target_audio, model_choice)
    raise ValueError("unsupported model selection")


def _inject_text(text, auto_submit=False):
    clipboard_ok = False
    copy_to_clipboard = get_settings()["copy_to_clipboard"]
    if copy_to_clipboard:
        try:
            result = subprocess.run(
                ["wl-copy", "--sensitive"], input=text, text=True, check=False, timeout=5
            )
            clipboard_ok = result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            pass
    if not clipboard_ok:
        if copy_to_clipboard:
            log("Clipboard copy failed; continuing with keyboard injection")

    try:
        typed = subprocess.run(["wtype", "--", text], check=False, timeout=5)
        if typed.returncode != 0:
            return False
    except (OSError, subprocess.SubprocessError):
        return False

    if auto_submit:
        time.sleep(0.08)
        try:
            submitted = subprocess.run(["wtype", "-k", "Return"], check=False, timeout=5)
            if submitted.returncode != 0:
                return False
            log("Auto-submit triggered")
        except (OSError, subprocess.SubprocessError):
            return False
    return True


def _stop_recording(auto_submit=False, pids=None):
    pids = _active_recording_pids() if pids is None else pids
    if not pids:
        log("stop called, but not recording")
        _clear_runtime_markers()
        _clear_audio_files()
        return False

    log(f"Stopping audio recording (auto_submit={auto_submit})")
    _clear_runtime_markers()
    for pid in pids:
        _terminate_recorder(pid, signal.SIGINT)

    model_choice = get_selected_model()
    log(f"Recording finalized; transcribing with model {model_choice}")
    pill_ipc("setTranscribing", "Transcribing...")
    target_audio = _audio_target()
    try:
        if target_audio is None or os.path.getsize(target_audio) < 1000:
            pill_ipc("setStatus", "Audio too short")
            log("Audio clip was too short or empty")
            return False

        try:
            text = _transcribe_audio(target_audio, model_choice)
        except MissingApiKeyError:
            log("Gemini API key not configured")
            pill_ipc("setStatus", "No API Key")
            return False
        except Exception as error:
            log(f"Transcription failed: {type(error).__name__}")
            pill_ipc("setStatus", "Transcription Error")
            return False

        if not text:
            pill_ipc("setStatus", "No speech detected")
            log("No speech detected")
            return False

        if not _inject_text(text, auto_submit=auto_submit):
            pill_ipc("setStatus", "Typing Error")
            log("Keyboard injection failed")
            return False

        pill_ipc("setDone")
        log("Text injected successfully")
        return True
    finally:
        # Recordings are sensitive and are not needed after transcription.
        _clear_audio_files()


def stop_recording(auto_submit=False):
    with _operation_lock() as locked:
        if not locked:
            return False
        return _stop_recording(auto_submit=auto_submit)


def toggle_recording(auto_submit=None):
    with _operation_lock() as locked:
        if not locked:
            return False
        pids = _active_recording_pids()
        if pids:
            if auto_submit is None:
                auto_submit = get_settings()["toggle_action"] == "submit"
            return _stop_recording(auto_submit=auto_submit, pids=pids)
        return _start_recording()


def _usage():
    return "Usage: gemini-dictate.py [start|stop|submit|pause|resume|cancel|toggle|toggle-submit|status|get-model|set-model <id>|list-models|settings]"


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "toggle"

    if action == "start":
        success = start_recording()
    elif action in ("stop", "done", "transcribe"):
        success = stop_recording(auto_submit=False)
    elif action in ("submit", "send"):
        success = stop_recording(auto_submit=True)
    elif action in ("pause", "toggle-pause"):
        success = toggle_pause()
    elif action == "resume":
        success = resume_recording()
    elif action == "cancel":
        success = cancel_recording()
    elif action == "toggle":
        success = toggle_recording()
    elif action == "toggle-submit":
        success = toggle_recording(auto_submit=True)
    elif action == "status":
        print(json.dumps(get_current_state(), separators=(",", ":")))
        success = True
    elif action == "get-model":
        print(get_selected_model())
        success = True
    elif action == "set-model":
        if len(sys.argv) != 3:
            print("Error: model id required", file=sys.stderr)
            sys.exit(1)
        if not set_selected_model(sys.argv[2]):
            print(f"Error: unsupported model id: {sys.argv[2]}", file=sys.stderr)
            sys.exit(1)
        print(get_selected_model())
        success = True
    elif action in ("settings", "get-settings"):
        print(json.dumps(get_settings(), separators=(",", ":")))
        success = True
    elif action == "set-setting":
        if len(sys.argv) != 4:
            print("Error: setting key and value required", file=sys.stderr)
            sys.exit(1)
        if not set_setting(sys.argv[2], sys.argv[3]):
            print(f"Error: invalid setting: {sys.argv[2]}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(get_settings(), separators=(",", ":")))
        success = True
    elif action == "reset-settings":
        if not reset_settings():
            print("Error: could not reset settings", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(get_settings(), separators=(",", ":")))
        success = True
    elif action == "list-audio-sources":
        print(json.dumps(list_audio_sources(), separators=(",", ":")))
        success = True
    elif action == "hotkeys-status":
        print(json.dumps(hotkeys_status(), separators=(",", ":")))
        success = True
    elif action == "apply-hotkeys":
        overrides = None
        if len(sys.argv) > 2:
            if len(sys.argv) != 3:
                print("Error: apply-hotkeys accepts one JSON object", file=sys.stderr)
                sys.exit(1)
            try:
                overrides = json.loads(sys.argv[2])
            except (TypeError, ValueError):
                print("Error: invalid hotkey JSON", file=sys.stderr)
                sys.exit(1)
        if not apply_hotkeys(overrides):
            print("Error: could not apply Flow hotkeys", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(hotkeys_status(), separators=(",", ":")))
        success = True
    elif action == "doctor":
        print(json.dumps(diagnostics(), separators=(",", ":")))
        success = True
    elif action == "test-audio":
        result = run_audio_test()
        print(json.dumps(result, separators=(",", ":")))
        success = result["ok"] is True
    elif action == "list-models":
        print(json.dumps(SUPPORTED_MODELS, indent=2))
        success = True
    else:
        print(_usage(), file=sys.stderr)
        sys.exit(1)

    if not success:
        sys.exit(1)
