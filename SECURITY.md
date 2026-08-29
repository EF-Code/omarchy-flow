# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
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
  checks.
- Temporary recordings are removed after cancellation and after transcription.
  Transcribed text is not written to the Flow log. The legacy `/tmp` files are
  retained only for compatibility and are also created privately when possible.
- Prefer the environment or GNOME Keyring for Gemini credentials. File-based
  credentials are accepted only when owned by the current user and not
  readable by group or other users.
