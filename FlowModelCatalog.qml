import QtQuick
import Quickshell.Io

// Every selector consumes the backend's allowlisted catalog. Keep one safe
// offline option available if the bounded startup query cannot complete.
Item {
  id: root
  required property string flowctlPath
  property bool ready: false
  property var models: [
    { id: "whisper-base.en", name: "Local Whisper (base.en)", title: "Local Whisper", shortName: "Whisper", desc: "base.en · Offline", provider: "local" }
  ]
  readonly property var dropdownOptions: models.map(function(model) {
    return { value: model.id, label: model.name }
  })

  function find(modelId) {
    for (var i = 0; i < root.models.length; i++) {
      if (root.models[i].id === modelId) return root.models[i]
    }
    return null
  }

  function accept(raw) {
    if (typeof raw !== "string" || raw.length > 16384) return false
    try {
      var parsed = JSON.parse(raw)
      if (!Array.isArray(parsed) || parsed.length < 1 || parsed.length > 16) return false
      var ids = []
      for (var i = 0; i < parsed.length; i++) {
        var model = parsed[i]
        if (!model || typeof model !== "object" || typeof model.id !== "string") return false
        if (!/^[a-z0-9][a-z0-9.-]{0,63}$/.test(model.id) || ids.indexOf(model.id) !== -1) return false
        if (model.provider !== "local" && model.provider !== "gemini") return false
        var fields = ["name", "title", "shortName", "desc"]
        for (var j = 0; j < fields.length; j++) {
          var value = model[fields[j]]
          if (typeof value !== "string" || value.length < 1 || value.length > 128) return false
        }
        ids.push(model.id)
      }
      if (parsed[0].id !== "whisper-base.en" || parsed[0].provider !== "local") return false
      root.models = parsed
      return true
    } catch (e) { return false }
  }

  Process {
    id: catalogProcess
    command: [root.flowctlPath, "qml", "list-models"]
    running: true
    stdout: StdioCollector { id: output; waitForEnd: true }
    onExited: function(exitCode) {
      if (exitCode === 0) root.ready = root.accept(output.text)
    }
    Component.onDestruction: if (running) running = false
  }

  Timer {
    interval: 5000
    running: catalogProcess.running
    onTriggered: catalogProcess.running = false
  }
}
