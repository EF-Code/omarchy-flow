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
    text: ""
    iconComponent: flowIcon
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

  Component {
    id: flowIcon

    Item {
      id: flowIconRoot
      anchors.fill: parent

      property color barColor: button.foreground

      Behavior on barColor {
        ColorAnimation { duration: 160 }
      }

      opacity: root.isPaused ? 0.55 : 1.0

      Behavior on opacity {
        NumberAnimation { duration: 160 }
      }

      Row {
        id: flowMark
        anchors.centerIn: parent
        spacing: 1.5

        // Match the five waveform bars in Pill.qml without imposing a palette.
        Rectangle {
          width: 2
          radius: 1
          anchors.verticalCenter: parent.verticalCenter
          property real animatedHeight: 8
          height: root.isRecording && !root.isPaused ? animatedHeight : 8
          color: flowIconRoot.barColor

          SequentialAnimation on animatedHeight {
            running: root.isRecording && !root.isPaused
            loops: Animation.Infinite
            NumberAnimation { to: 11; duration: 280; easing.type: Easing.InOutSine }
            NumberAnimation { to: 5; duration: 240; easing.type: Easing.InOutSine }
            NumberAnimation { to: 8; duration: 220; easing.type: Easing.InOutSine }
          }
        }

        Rectangle {
          width: 2
          radius: 1
          anchors.verticalCenter: parent.verticalCenter
          property real animatedHeight: 10
          height: root.isRecording && !root.isPaused ? animatedHeight : 10
          color: flowIconRoot.barColor

          SequentialAnimation on animatedHeight {
            running: root.isRecording && !root.isPaused
            loops: Animation.Infinite
            NumberAnimation { to: 6; duration: 240; easing.type: Easing.InOutSine }
            NumberAnimation { to: 14; duration: 300; easing.type: Easing.InOutSine }
            NumberAnimation { to: 9; duration: 260; easing.type: Easing.InOutSine }
          }
        }

        Rectangle {
          width: 2
          radius: 1
          anchors.verticalCenter: parent.verticalCenter
          property real animatedHeight: 12
          height: root.isRecording && !root.isPaused ? animatedHeight : 12
          color: flowIconRoot.barColor

          SequentialAnimation on animatedHeight {
            running: root.isRecording && !root.isPaused
            loops: Animation.Infinite
            NumberAnimation { to: 14; duration: 260; easing.type: Easing.InOutSine }
            NumberAnimation { to: 5; duration: 280; easing.type: Easing.InOutSine }
            NumberAnimation { to: 11; duration: 220; easing.type: Easing.InOutSine }
          }
        }

        Rectangle {
          width: 2
          radius: 1
          anchors.verticalCenter: parent.verticalCenter
          property real animatedHeight: 13
          height: root.isRecording && !root.isPaused ? animatedHeight : 13
          color: flowIconRoot.barColor

          SequentialAnimation on animatedHeight {
            running: root.isRecording && !root.isPaused
            loops: Animation.Infinite
            NumberAnimation { to: 5; duration: 330; easing.type: Easing.InOutSine }
            NumberAnimation { to: 14; duration: 250; easing.type: Easing.InOutSine }
            NumberAnimation { to: 9; duration: 300; easing.type: Easing.InOutSine }
          }
        }

        Rectangle {
          width: 2
          radius: 1
          anchors.verticalCenter: parent.verticalCenter
          property real animatedHeight: 9
          height: root.isRecording && !root.isPaused ? animatedHeight : 9
          color: flowIconRoot.barColor

          SequentialAnimation on animatedHeight {
            running: root.isRecording && !root.isPaused
            loops: Animation.Infinite
            NumberAnimation { to: 13; duration: 270; easing.type: Easing.InOutSine }
            NumberAnimation { to: 5; duration: 310; easing.type: Easing.InOutSine }
            NumberAnimation { to: 10; duration: 260; easing.type: Easing.InOutSine }
          }
        }
      }
    }
  }
}
