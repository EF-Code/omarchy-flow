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
  property bool menuOpen: false
  property bool settingsOpen: false

  readonly property var modelOptions: [
    { id: "whisper-base.en", title: "Whisper base.en", subtitle: "Local · Offline" },
    { id: "gemini-3.5-transcribe", title: "Gemini 3.5 Transcribe", subtitle: "Cloud · Dedicated transcription" },
    { id: "gemini-3.7-flash", title: "Gemini 3.7 Flash", subtitle: "Cloud · Speech understanding" }
  ]

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

  function close() {
    root.menuOpen = false
    root.settingsOpen = false
  }

  function openSettings() {
    root.menuOpen = false
    root.settingsOpen = true
    settingsView.settingsPage = "overview"
  }

  function returnToMenu() {
    root.settingsOpen = false
    Qt.callLater(function() { root.menuOpen = true })
  }

  function closeAfterAction(action, extraArg) {
    if (!root.runAction(action, extraArg)) return false
    root.close()
    return true
  }

  function selectModel(modelId, closeMenus) {
    if (closeMenus === undefined) closeMenus = true
    if (root.selectedModel === modelId) {
      if (closeMenus) root.close()
      return
    }
    if (!root.runAction("set-model", modelId)) return
    root.selectedModel = modelId
    if (closeMenus) root.close()
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
      ? ("Omarchy Flow: " + (root.isPaused ? "Paused" : "Recording") + " (" + root.selectedModel + ") — Left-Click for Menu")
      : ("Omarchy Flow: Voice Dictation (" + root.selectedModel + ") — Left-Click for Menu, Right-Click for Quick Action")

    onPressed: function(buttonCode) {
      if (buttonCode === Qt.RightButton) {
        if (root.isRecording) {
          root.runAction("pause")
        } else {
          root.toggleRecording()
        }
      } else if (buttonCode === Qt.LeftButton) {
        root.menuOpen = !root.menuOpen
      }
    }
  }

  Component.onCompleted: {
    settingsView.settingsPage = "overview"
    Qt.callLater(root.refreshStatus)
  }

  PopupCard {
    id: menuPopup
    anchorItem: root
    bar: root.bar
    owner: root
    open: root.menuOpen
    contentWidth: menuPopup.fittedContentWidth(Style.space(320))
    contentHeight: menuPopup.fittedContentHeight(menuColumn.implicitHeight)

    readonly property color foreground: Color.popups.text
    readonly property color mutedForeground: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.68)

    Column {
      id: menuColumn
      anchors.fill: parent
      spacing: Style.space(8)

      Row {
        width: parent.width
        spacing: Style.space(10)

        Loader {
          width: Style.space(28)
          height: Style.space(32)
          anchors.verticalCenter: parent.verticalCenter
          sourceComponent: flowIcon
        }

        Column {
          width: parent.width - Style.space(38)
          spacing: Style.space(2)
          anchors.verticalCenter: parent.verticalCenter

          Text {
            text: "Omarchy Flow"
            color: menuPopup.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.subtitle
            font.bold: true
          }

          Text {
            text: root.isRecording
              ? (root.isPaused ? "Recording paused" : "Recording in progress")
              : "Ready to dictate"
            color: menuPopup.mutedForeground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.caption
          }
        }
      }

      PanelSeparator { foreground: menuPopup.foreground }

      Text {
        text: "Speech model"
        color: menuPopup.foreground
        font.family: root.bar ? root.bar.fontFamily : Style.font.family
        font.pixelSize: Style.font.caption
        font.bold: true
      }

      Column {
        id: modelColumn
        width: parent.width
        height: root.modelOptions.length * Style.space(44) + Math.max(0, root.modelOptions.length - 1) * Style.space(4)
        spacing: Style.space(4)

        Repeater {
          model: root.modelOptions

          BorderSurface {
            id: modelRow
            required property var modelData
            required property int index

            width: modelColumn.width
            height: Style.space(44)
            readonly property bool selected: root.selectedModel === modelData.id
            readonly property bool hovered: modelMouse.containsMouse
            opacity: actionProcess.running ? 0.55 : 1.0
            color: selected
              ? Style.selectedFillFor(menuPopup.foreground, Color.accent)
              : hovered ? Style.hoverFillFor(menuPopup.foreground, Color.accent) : "transparent"
            borderSpec: selected
              ? Border.controlSpec("selected", menuPopup.foreground, Color.accent)
              : hovered ? Border.controlSpec("hover-cursor", menuPopup.foreground, Color.accent) : Border.none()

            Row {
              anchors.fill: parent
              anchors.leftMargin: Style.space(10)
              anchors.rightMargin: Style.space(10)
              spacing: Style.space(8)

              Column {
                width: parent.width - checkSlot.width - parent.spacing
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(1)

                Text {
                  width: parent.width
                  text: modelData.title
                  color: menuPopup.foreground
                  font.family: root.bar ? root.bar.fontFamily : Style.font.family
                  font.pixelSize: Style.font.body
                  font.bold: modelRow.selected
                  elide: Text.ElideRight
                }

                Text {
                  width: parent.width
                  text: modelData.subtitle
                  color: menuPopup.mutedForeground
                  font.family: root.bar ? root.bar.fontFamily : Style.font.family
                  font.pixelSize: Style.font.caption
                  elide: Text.ElideRight
                }
              }

              Item {
                id: checkSlot
                width: Style.space(16)
                height: parent.height

                Text {
                  anchors.centerIn: parent
                  visible: modelRow.selected
                  text: "✓"
                  color: Color.accent
                  font.family: root.bar ? root.bar.fontFamily : Style.font.family
                  font.pixelSize: Style.font.body
                  font.bold: true
                }
              }
            }

            MouseArea {
              id: modelMouse
              anchors.fill: parent
              enabled: !actionProcess.running
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: root.selectModel(modelData.id)
            }
          }
        }
      }

      PanelSeparator { foreground: menuPopup.foreground }

      Text {
        text: root.isRecording ? "Recording controls" : "Quick actions"
        color: menuPopup.foreground
        font.family: root.bar ? root.bar.fontFamily : Style.font.family
        font.pixelSize: Style.font.caption
        font.bold: true
      }

      Row {
        width: parent.width
        spacing: Style.space(6)

        Button {
          visible: !root.isRecording
          text: "Start dictation"
          foreground: menuPopup.foreground
          accent: Color.accent
          bordered: true
          enabled: !actionProcess.running
          onClicked: root.closeAfterAction("start")
        }

        Button {
          visible: !root.isRecording
          text: "Start & submit"
          foreground: menuPopup.foreground
          accent: Color.accent
          bordered: true
          enabled: !actionProcess.running
          onClicked: root.closeAfterAction("toggle-submit")
        }

        Button {
          visible: root.isRecording
          text: root.isPaused ? "Resume" : "Pause"
          foreground: menuPopup.foreground
          accent: Color.accent
          bordered: true
          enabled: !actionProcess.running
          onClicked: root.closeAfterAction("pause")
        }

        Button {
          visible: root.isRecording
          text: "Transcribe"
          foreground: menuPopup.foreground
          accent: Color.accent
          bordered: true
          enabled: !actionProcess.running
          onClicked: root.closeAfterAction("stop")
        }

        Button {
          visible: root.isRecording
          text: "Cancel"
          foreground: menuPopup.foreground
          accent: Color.accent
          bordered: true
          enabled: !actionProcess.running
          onClicked: root.closeAfterAction("cancel")
        }
      }

      Text {
        width: parent.width
        text: "Left-click opens this menu · Right-click is a quick recording action"
        color: menuPopup.mutedForeground
        font.family: root.bar ? root.bar.fontFamily : Style.font.family
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      Button {
        width: parent.width
        text: "Settings  ›"
        leftAlign: true
        foreground: menuPopup.foreground
        accent: Color.accent
        bordered: true
        enabled: !actionProcess.running
        onClicked: root.openSettings()
      }
    }
  }

  PopupCard {
    id: settingsPopup
    anchorItem: root
    bar: root.bar
    owner: root
    open: root.settingsOpen
    contentWidth: settingsPopup.fittedContentWidth(Style.space(500))
    contentHeight: settingsPopup.fittedContentHeight(settingsView.implicitHeight)

    SettingsView {
      id: settingsView
      anchors.fill: parent
      bar: root.bar
      flowctlPath: root.flowctlPath
      selectedModel: root.selectedModel
      onCloseRequested: root.returnToMenu()
      onModelRequested: function(modelId) { root.selectModel(modelId, false) }
    }
  }

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
