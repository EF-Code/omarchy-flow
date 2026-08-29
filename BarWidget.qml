import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "io.github.ef-code.omarchy-flow"

  readonly property string flowctlPath: decodeURIComponent(String(Qt.resolvedUrl("scripts/flowctl")).replace(/^file:\/\//, ""))
  property bool isRecording: false
  property bool isPaused: false
  property string selectedModel: "whisper-base.en"

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function runAction(action, extraArg) {
    if (actionProcess.running) return false
    var cmd = [root.flowctlPath, action]
    if (extraArg !== undefined && extraArg !== null && String(extraArg).trim() !== "") {
      cmd.push(String(extraArg))
    }
    actionProcess.command = cmd
    actionProcess.running = true
    return true
  }

  function refreshStatus() {
    if (!statusProcess.running) {
      statusProcess.running = true
    }
  }

  function toggleRecording(): bool {
    if (!root.runAction("toggle")) return false
    root.isRecording = !root.isRecording
    return true
  }

  Process {
    id: actionProcess
    command: []
    onRunningChanged: {
      if (!running) {
        root.refreshStatus()
      }
    }
  }

  Process {
    id: statusProcess
    command: [root.flowctlPath, "status"]
    stdout: StdioCollector {
      id: statusOut
      waitForEnd: true
    }
    onExited: function(exitCode) {
      if (exitCode === 0 && statusOut.text) {
        try {
          var data = JSON.parse(statusOut.text.trim())
          root.isRecording = data.recording === true
          root.isPaused = data.paused === true
          if (data.model) root.selectedModel = data.model
        } catch (e) {}
      }
    }
  }

  Timer {
    interval: root.isRecording ? 1000 : 3000
    repeat: true
    running: true
    onTriggered: root.refreshStatus()
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.isRecording ? (root.isPaused ? "󰏤" : "󰍬") : "󰍭"
    active: root.isRecording
    useActiveColor: true
    activeColor: root.isPaused ? "#FBBF24" : Color.accent

    tooltipText: root.isRecording
      ? ("Omarchy Flow: " + (root.isPaused ? "Paused" : "Recording") + " (" + root.selectedModel + ") — Click to Transcribe")
      : ("Omarchy Flow: Voice Dictation (" + root.selectedModel + ") — Left-Click to Start, Right-Click to Pause/Toggle")

    onPressed: function(buttonCode) {
      if (buttonCode === Qt.RightButton) {
        if (root.isRecording) {
          root.runAction("pause")
        } else {
          root.toggleRecording()
        }
      } else if (buttonCode === Qt.LeftButton) {
        root.toggleRecording()
      }
    }
  }

  Component.onCompleted: Qt.callLater(root.refreshStatus)
}
