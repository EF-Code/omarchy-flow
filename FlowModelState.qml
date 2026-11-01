import QtQuick
import Quickshell.Io

// Model identity comes from persisted backend state, independently of whether
// catalog metadata is available. Empty/unconfirmed identity never means local.
Item {
  id: root
  required property string flowctlPath
  property bool ready: false
  property string selectedModel: ""
  property string recordingModel: ""
  property bool isRecording: false
  property bool isPaused: false
  property bool saving: false
  property bool loading: false
  readonly property string displayedModel: ready ? (recordingModel || selectedModel) : ""
  property int revision: 0

  function validModelId(value) {
    return typeof value === "string" && /^[a-z0-9][a-z0-9.-]{0,63}$/.test(value)
  }

  function recordingCommand(action) {
    if (action !== "start" && action !== "toggle" && action !== "toggle-submit") return []
    if (action === "start" && (!root.ready || root.saving)) return []
    // A toggle can always reach stop. If cached status is stale, the sentinel
    // prevents the backend from turning that stop into a fresh capture.
    var expected = root.ready && !root.saving ? root.selectedModel : "unconfirmed"
    return [root.flowctlPath, "qml", action, expected]
  }

  function refresh() {
    if (root.loading || root.saving) return
    root.loading = true
    statusProcess.revision = root.revision
    statusProcess.running = true
  }

  function invalidate() {
    root.revision++
    root.ready = false
    root.refresh()
  }

  function selectModel(modelId) {
    if (root.saving || !validModelId(modelId)) return false
    // Invalidate in-flight reads and require a fresh read after the write,
    // including when the user explicitly reselects the displayed model.
    root.revision++
    root.ready = false
    root.saving = true
    saveProcess.command = [root.flowctlPath, "qml", "set-model", modelId]
    saveProcess.running = true
    return true
  }

  function acceptStatus(raw) {
    if (typeof raw !== "string" || raw.length > 8192) return false
    try {
      var data = JSON.parse(raw)
      if (!data || typeof data !== "object" || !validModelId(data.model)) return false
      if (typeof data.recording !== "boolean" || typeof data.paused !== "boolean") return false
      if (typeof data.recording_model !== "string") return false
      if (data.recording_model !== "" && !validModelId(data.recording_model)) return false
      if (data.recording && !data.recording_model) return false
      root.selectedModel = data.model
      root.recordingModel = data.recording_model
      root.isRecording = data.recording
      root.isPaused = data.paused
      return true
    } catch (e) { return false }
  }

  Process {
    id: statusProcess
    property int revision: 0
    command: [root.flowctlPath, "qml", "status"]
    stdout: StdioCollector { id: statusOutput; waitForEnd: true }
    onExited: function(exitCode) {
      root.loading = false
      if (revision !== root.revision || root.saving) {
        Qt.callLater(root.refresh)
        return
      }
      root.ready = exitCode === 0 && root.acceptStatus(statusOutput.text)
    }
    Component.onDestruction: if (running) running = false
  }
  Timer {
    interval: 5000
    running: root.loading
    onTriggered: { root.ready = false; root.loading = false; statusProcess.running = false }
  }
  Process {
    id: saveProcess
    command: []
    onExited: { root.saving = false; Qt.callLater(root.refresh) }
    Component.onDestruction: if (running) running = false
  }
  Timer {
    interval: 8000
    running: root.saving
    onTriggered: { root.saving = false; saveProcess.running = false; Qt.callLater(root.refresh) }
  }
  Timer {
    interval: 500 + Math.floor(Math.random() * 200)
    repeat: true
    running: true
    onTriggered: root.refresh()
  }
  Component.onCompleted: Qt.callLater(root.refresh)
}
