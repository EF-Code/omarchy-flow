#!/usr/bin/env python3
"""Unit tests for the Omarchy Flow backend and command dispatcher."""

import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


warnings.simplefilter("ignore", DeprecationWarning)


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

spec = importlib.util.spec_from_file_location(
    "flow_backend", REPO_ROOT / "scripts" / "gemini-dictate.py"
)
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


def file_mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


class TestFlowBackend(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.config_home = root / "config"
        self.runtime_home = root / "runtime"
        self.state_home = root / "state"
        self.legacy_runtime = root / "legacy-runtime"
        for directory in [
            self.config_home,
            self.runtime_home,
            self.state_home,
            self.legacy_runtime,
        ]:
            directory.mkdir(mode=0o700)

        self.config_dir = self.config_home / "omarchy-flow"
        self.legacy_config_dir = self.config_home / "gemini-pill"
        self.config_dir.mkdir(mode=0o700)
        self.legacy_config_dir.mkdir(mode=0o700)

        self.backend_paths = {
            name: getattr(backend, name)
            for name in [
                "XDG_CONFIG_HOME",
                "XDG_RUNTIME_DIR",
                "XDG_STATE_HOME",
                "CONFIG_DIR",
                "LEGACY_CONFIG_DIR",
                "RUNTIME_DIR",
                "STATE_DIR",
                "LOG_FILE",
                "TEMP_AUDIO",
                "PID_FILE",
                "STATE_FILE",
                "LOCK_FILE",
                "MODEL_FILE",
                "LEGACY_MODEL_FILE",
                "SETTINGS_FILE",
                "LEGACY_RUNTIME_DIR",
                "LEGACY_TEMP_AUDIO",
                "LEGACY_PID_FILE",
                "LEGACY_STATE_FILE",
            ]
        }

        backend.XDG_CONFIG_HOME = str(self.config_home)
        backend.XDG_RUNTIME_DIR = str(self.runtime_home)
        backend.XDG_STATE_HOME = str(self.state_home)
        backend.CONFIG_DIR = str(self.config_dir)
        backend.LEGACY_CONFIG_DIR = str(self.legacy_config_dir)
        backend.RUNTIME_DIR = str(self.runtime_home / "omarchy-flow")
        backend.STATE_DIR = str(self.state_home / "omarchy-flow")
        Path(backend.RUNTIME_DIR).mkdir(mode=0o700)
        Path(backend.STATE_DIR).mkdir(mode=0o700)
        backend.LOG_FILE = str(Path(backend.STATE_DIR) / "flow.log")
        backend.TEMP_AUDIO = str(Path(backend.RUNTIME_DIR) / "recording.wav")
        backend.PID_FILE = str(Path(backend.RUNTIME_DIR) / "recording.pid")
        backend.STATE_FILE = str(Path(backend.RUNTIME_DIR) / "state.json")
        backend.LOCK_FILE = str(Path(backend.RUNTIME_DIR) / "operation.lock")
        backend.MODEL_FILE = str(self.config_dir / "selected_model.txt")
        backend.LEGACY_MODEL_FILE = str(self.legacy_config_dir / "selected_model.txt")
        backend.SETTINGS_FILE = str(self.config_dir / "settings.json")
        backend.LEGACY_RUNTIME_DIR = str(self.legacy_runtime)
        backend.LEGACY_TEMP_AUDIO = str(self.legacy_runtime / "gemini_dictation.wav")
        backend.LEGACY_PID_FILE = str(self.legacy_runtime / "gemini_dictation.pid")
        backend.LEGACY_STATE_FILE = str(self.legacy_runtime / "gemini_dictation.state")

        self.child_env = os.environ.copy()
        self.child_env.update(
            {
                "XDG_CONFIG_HOME": str(self.config_home),
                "XDG_RUNTIME_DIR": str(self.runtime_home),
                "XDG_STATE_HOME": str(self.state_home),
                "OMARCHY_FLOW_PYTHON": sys.executable,
            }
        )

    def tearDown(self):
        for name, value in self.backend_paths.items():
            setattr(backend, name, value)
        self.temp_dir.cleanup()

    def test_supported_models_list(self):
        model_ids = [model["id"] for model in backend.SUPPORTED_MODELS]
        self.assertEqual(len(model_ids), 3)
        self.assertEqual(
            model_ids,
            [
                "whisper-base.en",
                "gemini-3.5-transcribe",
                "gemini-3.7-flash",
            ],
        )

    def test_virtualenv_package_discovery_preserves_priority_order(self):
        original_path = list(sys.path)

        def fake_glob(pattern):
            if "active-env" in pattern:
                return ["/active-env/lib/python3.14/site-packages"]
            return []

        with patch.dict(os.environ, {"VIRTUAL_ENV": "/active-env"}), patch.object(
            backend.glob, "glob", side_effect=fake_glob
        ), patch.object(backend.os.path, "isdir", return_value=True):
            backend._ensure_venv_packages()

        self.assertEqual(sys.path[0], "/active-env/lib/python3.14/site-packages")
        sys.path[:] = original_path

    def test_get_and_set_selected_model(self):
        self.assertEqual(backend.get_selected_model(), "whisper-base.en")
        self.assertTrue(backend.set_selected_model("gemini-3.5-transcribe"))
        self.assertEqual(backend.get_selected_model(), "gemini-3.5-transcribe")
        self.assertEqual(Path(backend.MODEL_FILE).read_text().strip(), "gemini-3.5-transcribe")
        self.assertEqual(Path(backend.LEGACY_MODEL_FILE).read_text().strip(), "gemini-3.5-transcribe")
        self.assertEqual(file_mode(backend.MODEL_FILE), 0o600)

    def test_invalid_model_is_rejected_and_falls_back(self):
        self.assertFalse(backend.set_selected_model("not-a-real-model"))
        Path(backend.MODEL_FILE).write_text("not-a-real-model\n")
        os.chmod(backend.MODEL_FILE, 0o600)
        self.assertEqual(backend.get_selected_model(), "whisper-base.en")
        Path(backend.LEGACY_MODEL_FILE).write_text("removed-model\n")
        os.chmod(backend.LEGACY_MODEL_FILE, 0o600)
        self.assertEqual(backend.get_selected_model(), "whisper-base.en")

    def test_settings_defaults_and_persistence(self):
        settings = backend.get_settings()
        self.assertEqual(settings["toggle_action"], "transcribe")
        self.assertEqual(settings["audio_source"], "default")
        self.assertTrue(settings["copy_to_clipboard"])
        self.assertTrue(backend.set_setting("toggle_action", "submit"))
        self.assertTrue(backend.set_setting("copy_to_clipboard", "false"))
        self.assertTrue(backend.set_setting("hotkeys.toggle", "ctrl + shift + f6"))
        updated = backend.get_settings()
        self.assertEqual(updated["toggle_action"], "submit")
        self.assertFalse(updated["copy_to_clipboard"])
        self.assertEqual(updated["hotkeys"]["toggle"], "CTRL + SHIFT + F6")
        self.assertEqual(file_mode(backend.SETTINGS_FILE), 0o600)

    def test_settings_reject_invalid_values(self):
        original = backend.get_settings()
        self.assertFalse(backend.set_setting("toggle_action", "send-email"))
        self.assertFalse(backend.set_setting("audio_source", "source with spaces"))
        self.assertFalse(backend.set_setting("hud_position", "left"))
        self.assertFalse(backend.set_setting("hotkeys.toggle", "SUPER + SUPER + V"))
        self.assertEqual(backend.get_settings(), original)

    def test_audio_source_listing_filters_non_input_nodes(self):
        pactl_output = json.dumps([
            {
                "name": "speaker.monitor",
                "description": "Monitor",
                "properties": {"media.class": "Audio/Sink"},
            },
            {
                "name": "desk-mic",
                "description": "Desk microphone",
                "properties": {"media.class": "Audio/Source"},
            },
        ])
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout=pactl_output, stderr="")
        with patch("subprocess.run", return_value=result):
            sources = backend.list_audio_sources()
        self.assertEqual(sources, [
            {"id": "default", "name": "System default"},
            {"id": "desk-mic", "name": "Desk microphone"},
        ])

    def test_cloud_diagnostics_require_google_sdk(self):
        self.assertTrue(backend.set_selected_model("gemini-3.5-transcribe"))
        with patch.object(backend.shutil, "which", return_value="/usr/bin/tool"), patch.object(
            backend.importlib.util, "find_spec", return_value=None
        ), patch.object(backend, "get_gemini_api_key", return_value="configured-key"), patch.object(
            backend, "list_audio_sources", return_value=[{"id": "default", "name": "System default"}]
        ):
            report = backend.diagnostics()

        sdk_check = next(check for check in report["checks"] if check["id"] == "google-genai")
        self.assertFalse(sdk_check["ok"])
        self.assertFalse(report["ok"])

    def test_toggle_uses_saved_completion_action(self):
        self.assertTrue(backend.set_setting("toggle_action", "submit"))
        with patch.object(backend, "_active_recording_pids", return_value=[12345]), patch.object(
            backend, "_stop_recording", return_value=True
        ) as stop:
            self.assertTrue(backend.toggle_recording())
        stop.assert_called_once_with(auto_submit=True, pids=[12345])

    def test_apply_hotkeys_writes_managed_block(self):
        reload_ok = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        def fake_run(args, **kwargs):
            if args == ["hyprctl", "reload"] or args == ["hyprctl", "configerrors"]:
                return reload_ok
            raise AssertionError(f"unexpected subprocess call: {args}")

        with patch("subprocess.run", side_effect=fake_run):
            self.assertTrue(backend.apply_hotkeys({
                "toggle": "SUPER + ALT + F6",
                "toggle_submit": "",
                "push_to_talk": "F7",
                "pause": "SUPER + ALT + P",
                "cancel": "SUPER + ALT + C",
            }))

        bindings_path = Path(backend.XDG_CONFIG_HOME) / "hypr" / "bindings.lua"
        content = bindings_path.read_text()
        self.assertIn(backend.HOTKEY_MARKER_START, content)
        self.assertIn('o.bind("SUPER + ALT + F6"', content)
        self.assertIn('o.bind("F7", "Flow: Push to talk (release)"', content)
        self.assertIn(
            '"omarchy-shell io.github.ef-code.omarchy-flow.service toggle"', content
        )
        self.assertIn(
            '"omarchy-shell io.github.ef-code.omarchy-flow.service stop"', content
        )
        self.assertNotIn("quickshell ipc call", content)
        self.assertNotIn("toggleSubmit", content)
        self.assertEqual(backend.get_settings()["hotkeys"]["toggle_submit"], "")

    def test_get_current_state(self):
        state = backend.get_current_state()
        self.assertEqual(set(state), {"recording", "paused", "model"})
        self.assertFalse(state["recording"])
        self.assertFalse(state["paused"])

    def test_update_runtime_state(self):
        backend.update_runtime_state("recording", paused=True, pid=12345)
        data = json.loads(Path(backend.STATE_FILE).read_text())
        self.assertEqual(data["status"], "recording")
        self.assertTrue(data["paused"])
        self.assertEqual(data["pid"], 12345)
        self.assertEqual(file_mode(backend.STATE_FILE), 0o600)

    def test_legacy_pid_marker_failure_does_not_block_recording_state(self):
        original_write = backend._write_private_text

        def fail_legacy(path, content):
            if path == backend.LEGACY_PID_FILE:
                raise OSError("legacy path unavailable")
            return original_write(path, content)

        with patch.object(backend, "_write_private_text", side_effect=fail_legacy):
            backend._write_pid_markers(4242)

        self.assertEqual(Path(backend.PID_FILE).read_text().strip(), "4242")
        self.assertEqual(file_mode(backend.PID_FILE), 0o600)
        self.assertFalse(Path(backend.LEGACY_PID_FILE).exists())

    def test_api_key_lookup_env(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test_env_key_123456789"}):
            self.assertEqual(backend.get_gemini_api_key(), "test_env_key_123456789")

    def test_api_key_lookup_secure_file_only(self):
        key_file = Path(backend.CONFIG_DIR) / "gemini_api_key"
        key_file.write_text("test_file_key_987654321\n")
        os.chmod(key_file, 0o600)
        failed_lookup = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=""
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}), patch(
            "subprocess.run", return_value=failed_lookup
        ):
            self.assertEqual(backend.get_gemini_api_key(), "test_file_key_987654321")

        os.chmod(key_file, 0o644)
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}), patch(
            "subprocess.run", return_value=failed_lookup
        ):
            self.assertIsNone(backend.get_gemini_api_key())

    def test_is_recording_rejects_stale_and_pid_reuse_markers(self):
        Path(backend.PID_FILE).write_text("9999999\n")
        self.assertFalse(backend.is_recording())
        self.assertFalse(Path(backend.PID_FILE).exists())

        Path(backend.PID_FILE).write_text(f"{os.getpid()}\n")
        self.assertFalse(backend.is_recording())
        self.assertFalse(Path(backend.PID_FILE).exists())

    def test_cancel_recording_cleanup(self):
        for path in [
            backend.PID_FILE,
            backend.LEGACY_PID_FILE,
            backend.STATE_FILE,
            backend.LEGACY_STATE_FILE,
        ]:
            Path(path).write_text("9999999\n")
        for path in [backend.TEMP_AUDIO, backend.LEGACY_TEMP_AUDIO]:
            Path(path).write_bytes(b"dummy audio content")

        with patch.object(backend, "pill_ipc"):
            self.assertTrue(backend.cancel_recording())
        for path in [
            backend.PID_FILE,
            backend.LEGACY_PID_FILE,
            backend.STATE_FILE,
            backend.LEGACY_STATE_FILE,
            backend.TEMP_AUDIO,
            backend.LEGACY_TEMP_AUDIO,
        ]:
            self.assertFalse(Path(path).exists())

    def test_stop_without_recorder_cleans_orphaned_audio(self):
        Path(backend.TEMP_AUDIO).write_bytes(b"orphaned audio")
        with patch.object(backend, "pill_ipc"):
            self.assertFalse(backend.stop_recording())
        self.assertFalse(Path(backend.TEMP_AUDIO).exists())

    def test_flowctl_uses_isolated_xdg_state_and_validates_arguments(self):
        flowctl = REPO_ROOT / "scripts" / "flowctl"
        set_result = subprocess.run(
            [str(flowctl), "model", "gemini-3.7-flash"],
            env=self.child_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(set_result.returncode, 0, set_result.stderr)
        get_result = subprocess.run(
            [str(flowctl), "model"],
            env=self.child_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(get_result.returncode, 0, get_result.stderr)
        self.assertEqual(get_result.stdout.strip(), "gemini-3.7-flash")

        invalid = subprocess.run(
            [str(flowctl), "model", "unsupported", "extra"],
            env=self.child_env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(invalid.returncode, 0)

        unknown = subprocess.run(
            [str(flowctl), "not-a-command"],
            env=self.child_env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(unknown.returncode, 0)

    def test_extract_voxtype_text(self):
        output = (
            "\x1b[32mLoading model\x1b[0m\n"
            "Transcription completed in 0.42s\n"
            "  Hello, world.  \n"
        )
        self.assertEqual(backend._extract_voxtype_text(output), "Hello, world.")

    def test_local_transcription_checks_exit_code(self):
        success = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Transcription completed in 0.1s\nHello"
        )
        with patch("subprocess.run", return_value=success) as run:
            self.assertEqual(backend._transcribe_local("recording.wav"), "Hello")
        self.assertEqual(run.call_args.args[0], ["voxtype", "transcribe", "recording.wav"])

        failure = subprocess.CompletedProcess(args=[], returncode=1, stdout="")
        with patch("subprocess.run", return_value=failure):
            with self.assertRaises(RuntimeError):
                backend._transcribe_local("recording.wav")

    def test_dedicated_cloud_transcription_uses_file_upload(self):
        audio = Path(backend.TEMP_AUDIO)
        audio.write_bytes(b"RIFF test")
        interaction = SimpleNamespace(output_text="  Cloud result  ")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            with patch.object(
                backend, "get_gemini_api_key", return_value="api-key-123456789"
            ), patch("google.genai.Client") as client_type:
                client = client_type.return_value
                client.files.upload.return_value = SimpleNamespace(
                    name="uploaded-audio", uri="https://example.invalid/audio", mime_type="audio/wav"
                )
                client.interactions.create.return_value = interaction
                result = backend._transcribe_cloud(str(audio), "gemini-3.5-transcribe")

        self.assertEqual(result, "Cloud result")
        upload_call = client.files.upload.call_args
        self.assertEqual(upload_call.kwargs["file"], str(audio))
        self.assertEqual(upload_call.kwargs["config"].mime_type, "audio/wav")
        client.files.delete.assert_called_once_with(name="uploaded-audio")
        call = client.interactions.create.call_args
        self.assertEqual(call.kwargs["model"], "gemini-3.5-transcribe")
        self.assertEqual(
            call.kwargs["input"],
            [{"type": "audio", "uri": "https://example.invalid/audio", "mime_type": "audio/wav"}],
        )
        self.assertEqual(
            call.kwargs["generation_config"]["transcription_config"]["mode"],
            "smart",
        )

    def test_model_dispatch_rejects_unknown_model(self):
        with self.assertRaises(ValueError):
            backend._transcribe_audio("recording.wav", "unsupported-model")

    def test_transcribing_status_does_not_expose_model_name(self):
        Path(backend.TEMP_AUDIO).write_bytes(b"R" * 1200)
        with patch.object(backend, "_terminate_recorder", return_value=True), patch.object(
            backend, "get_selected_model", return_value="gemini-3.5-transcribe"
        ), patch.object(backend, "_transcribe_audio", return_value="hello"), patch.object(
            backend, "_inject_text", return_value=True
        ), patch.object(backend, "pill_ipc") as ipc:
            self.assertTrue(backend._stop_recording(pids=[4242]))

        ipc.assert_any_call("setTranscribing", "Transcribing...")
        self.assertFalse(
            any("gemini-3.5-transcribe" in str(call.args) for call in ipc.call_args_list)
        )

    def test_inject_text_checks_keyboard_commands(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args=args, returncode=0)

        with patch("subprocess.run", side_effect=fake_run), patch.object(backend.time, "sleep"):
            self.assertTrue(backend._inject_text("hello", auto_submit=True))

        self.assertEqual(
            [call[0] for call in calls],
            [
                ["wl-copy", "--sensitive"],
                ["wtype", "--", "hello"],
                ["wtype", "-k", "Return"],
            ],
        )
        self.assertEqual(calls[0][1]["input"], "hello")

        def wtype_failure(args, **kwargs):
            code = 1 if args[0] == "wtype" else 0
            return subprocess.CompletedProcess(args=args, returncode=code)

        with patch("subprocess.run", side_effect=wtype_failure):
            self.assertFalse(backend._inject_text("hello"))

    def test_start_recording_is_private_and_single_instance(self):
        process = SimpleNamespace(pid=4242, returncode=None, poll=lambda: None)
        with patch.object(
            backend, "_is_recorder_process", side_effect=lambda pid: pid == 4242
        ), patch.object(backend, "_process_start_ticks", return_value=1234), patch.object(
            backend, "pill_ipc"
        ), patch.object(backend.time, "sleep"), patch(
            "subprocess.Popen", return_value=process
        ) as popen:
            self.assertTrue(backend.start_recording())
            self.assertFalse(backend.start_recording())

        self.assertEqual(popen.call_count, 1)
        command = popen.call_args.args[0]
        self.assertEqual(
            command[command.index("-f") : command.index("-f") + 4],
            ["-f", "pulse", "-i", "default"],
        )
        self.assertEqual(popen.call_args.kwargs["umask"], 0o077)
        self.assertEqual(file_mode(backend.PID_FILE), 0o600)
        data = json.loads(Path(backend.STATE_FILE).read_text())
        self.assertEqual(data["pid"], 4242)
        self.assertEqual(data["start_ticks"], 1234)

    def test_qml_action_and_status_contracts(self):
        bar = (REPO_ROOT / "BarWidget.qml").read_text()
        pill = (REPO_ROOT / "Pill.qml").read_text()
        service = (REPO_ROOT / "Service.qml").read_text()
        settings = (REPO_ROOT / "SettingsView.qml").read_text()

        transcribe_button = bar[bar.index('text: "Transcribe"') :]
        self.assertIn('onClicked: root.closeAfterAction("stop")', transcribe_button[:500])
        self.assertIn('root.stateMode = "status"', pill)
        self.assertIn('if (root.stateMode === "status") return root.statusText', pill)
        self.assertIn("property var actionQueue", service)
        self.assertIn('return "queued"', service)
        self.assertIn("property var settingWriteQueue", settings)
        self.assertIn("root.settingWriteQueue.push(command)", settings)


if __name__ == "__main__":
    unittest.main(verbosity=2)
