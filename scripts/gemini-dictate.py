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
import glob
import contextlib
import fcntl
import signal
import stat
import subprocess
import datetime
import tempfile
import warnings

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

# Legacy compatibility files. They are only read/written when they are owned
# by the current user and are never followed as symlinks.
LEGACY_RUNTIME_DIR = tempfile.gettempdir()
LEGACY_TEMP_AUDIO = os.path.join(LEGACY_RUNTIME_DIR, "gemini_dictation.wav")
LEGACY_PID_FILE = os.path.join(LEGACY_RUNTIME_DIR, "gemini_dictation.pid")
LEGACY_STATE_FILE = os.path.join(LEGACY_RUNTIME_DIR, "gemini_dictation.state")

SUPPORTED_MODELS = [
    {"id": "whisper-base.en", "name": "Whisper base.en", "desc": "Local • Zero Latency", "provider": "local"},
    {"id": "gemini-3.5-transcribe", "name": "Gemini 3.5 Transcribe", "desc": "Dedicated Audio • Ultra Fast", "provider": "gemini"},
    {"id": "gemini-3.7-flash", "name": "Gemini 3.7 Flash", "desc": "Flagship • Reasoning", "provider": "gemini"},
]

DEFAULT_MODEL_ID = SUPPORTED_MODELS[0]["id"]
SUPPORTED_MODEL_IDS = frozenset(model["id"] for model in SUPPORTED_MODELS)

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
        if args[format_index + 1] != "pulse" or args[input_index + 1] != "default":
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
    written = set()
    try:
        for pid_path in [PID_FILE, LEGACY_PID_FILE]:
            absolute_path = os.path.abspath(pid_path)
            if absolute_path in written:
                continue
            _write_private_text(pid_path, f"{pid}\n")
            written.add(absolute_path)
    except OSError:
        for pid_path in [PID_FILE, LEGACY_PID_FILE]:
            _remove_owned_path(pid_path)
        raise


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
                "-f", "pulse", "-i", "default",
                "-ar", "16000", "-ac", "1",
                TEMP_AUDIO,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
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
        ["voxtype", "transcribe", target_audio],
        capture_output=True,
        text=True,
        timeout=30,
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
    if model_choice == "whisper-base.en":
        return _transcribe_local(target_audio)
    if model_choice in SUPPORTED_MODEL_IDS:
        return _transcribe_cloud(target_audio, model_choice)
    raise ValueError("unsupported model selection")


def _inject_text(text, auto_submit=False):
    clipboard_ok = False
    try:
        result = subprocess.run(
            ["wl-copy", "--sensitive"], input=text, text=True, check=False, timeout=5
        )
        clipboard_ok = result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        pass
    if not clipboard_ok:
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
    pill_ipc("setTranscribing", f"Transcribing ({model_choice})...")
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


def toggle_recording(auto_submit=False):
    with _operation_lock() as locked:
        if not locked:
            return False
        pids = _active_recording_pids()
        if pids:
            return _stop_recording(auto_submit=auto_submit, pids=pids)
        return _start_recording()


def _usage():
    return "Usage: gemini-dictate.py [start|stop|submit|pause|resume|cancel|toggle|toggle-submit|status|get-model|set-model <id>|list-models]"


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
        success = toggle_recording(auto_submit=False)
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
    elif action == "list-models":
        print(json.dumps(SUPPORTED_MODELS, indent=2))
        success = True
    else:
        print(_usage(), file=sys.stderr)
        sys.exit(1)

    if not success:
        sys.exit(1)
