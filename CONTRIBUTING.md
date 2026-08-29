# Contributing to Omarchy Flow

Thank you for contributing to Omarchy Flow!

## Development Guidelines

1. **Local First & Unprivileged**:
   - The plugin must never require `sudo`, `pkexec`, or elevated privileges.
   - Primary state must reside in standard XDG directories (`~/.config/omarchy-flow/`, `$XDG_RUNTIME_DIR/omarchy-flow/`); legacy compatibility mirrors must remain private and temporary.
   - Do not commit machine-specific absolute paths or credentials.

2. **QML & Plugin Standards**:
   - Verify that all QML components pass `qmllint` without errors.
   - Maintain backwards-compatible IPC interfaces for `io.github.ef-code.omarchy-flow` and `geminipill`.

3. **Running Tests**:
   ```sh
   bash tests/run.sh
   ```

   The runner selects `OMARCHY_FLOW_PYTHON`, the active virtual environment, or
   a local default virtual environment. Set `OMARCHY_FLOW_PYTHON` explicitly
   when testing a checkout with a specific `google-genai` installation. The
   suite uses temporary XDG directories and must not modify a developer's live
   model choice.

   Before opening a change, also run the installed Omarchy checks directly when
   available:

   ```sh
   omarchy plugin validate .
   qmllint -I "${OMARCHY_PATH:-/usr/share/omarchy}/shell" \
     -I /usr/lib/qt6/qml BarWidget.qml Pill.qml Service.qml
   ```
