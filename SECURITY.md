# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.4.x   | :white_check_mark: |
| 0.3.x   | :white_check_mark: |
| < 0.3.0 | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability within Omarchy Flow, please do not open a public issue. Report it directly to the maintainers via GitHub Security Advisories.

## Security Notes

- Omarchy plugins run with the user's desktop privileges. Flow is intentionally
  unprivileged and never requires `sudo`, but its `wtype` integration can type
  into whichever Wayland window is focused.
- Configuration, runtime state, PID markers, and logs are written under XDG
  directories. New files are created with mode `600` and containing directories
  with mode `700`; stale recorder markers are removed after process-identity
  checks. All private reads/writes use held directory descriptors with
  `O_NOFOLLOW`/`O_NONBLOCK` and `fstat` owner/type/nlink validation, and are
  capped at `1 MiB` per read.
- Temporary recordings are removed after cancellation and after transcription.
  Recordings are created in an exclusively created private capture directory
  (`mkdtemp .cap-*` with `0o700`); a validated exclusive inode is held open and
  passed to ffmpeg via `/proc/self/fd`, so narrowly scoped overwrite mode never
  resolves a mutable predictable pathname. The capture is discovered via descriptor-validated `audio_path` and strict
  `20 MiB` ceilings. Transcribed text is not written to the Flow log and is
  truncated to `20k` chars / `64 KiB` before any clipboard/typing.
- Transcription uses a hard 90 s end-to-end deadline across credential lookup,
  upload, generation, and cleanup in a killable worker (`60 s` per-request
  `NETWORK_TIMEOUT_MS`, retries disabled); failed upload cleanup is retried in a
  bounded cleanup worker. `wl-copy`/`wtype` stdout/stderr go to `DEVNULL` to avoid
  unbounded QML collector growth. Logs are bounded at `512 KiB` with rotation
  (`flow.log.1..3`) and `1 KiB` message truncation.
- QML `Process`/`StdioCollector` jobs run behind a producer-side `16 KiB` cap
  with action-specific deadlines and matching per-job watchdogs (2-130 s),
  `Component.onDestruction` cleanup, and bounded `JSON.parse` (`8-16 KiB`) with
  cardinality caps (`32` items) and `Text.PlainText` rendering for externally
  derived strings.
- Prefer the environment or GNOME Keyring for Gemini credentials. File-based
  credentials are accepted only when owned by the current user and not
  readable by group or other users, and `pill_ipc` scrubs `LD_*`/`PYTHON*`
  from the child environment.
