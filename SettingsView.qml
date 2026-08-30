import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Ui

Item {
  id: root

  property var bar: null
  required property string flowctlPath
  property string selectedModel: "whisper-base.en"
  property string toggleAction: "transcribe"
  property string audioSource: "default"
  property bool copyToClipboard: true
  property bool hudEnabled: true
  property string hudPosition: "bottom"
  property bool waveformEnabled: true
  property var audioOptions: [
    { value: "default", label: "System default" }
  ]
  property var hotkeys: ({
    toggle: "SUPER + ALT + V",
    toggle_submit: "SUPER + ALT + SHIFT + V",
    push_to_talk: "F6",
    pause: "SUPER + ALT + P",
    cancel: "SUPER + ALT + C"
  })
  property bool hotkeysInstalled: false
  property var hotkeyConflicts: []
  property var diagnosticChecks: []
  property string notice: ""
  property string audioTestResult: ""
  property string settingsPage: "overview"
  property var settingWriteQueue: []

  readonly property color foreground: Color.popups.text
  readonly property color mutedForeground: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.68)
  readonly property string fontFamily: root.bar ? root.bar.fontFamily : Style.font.family

  readonly property var modelOptions: [
    { value: "whisper-base.en", label: "Whisper base.en" },
    { value: "gemini-3.5-transcribe", label: "Gemini 3.5 Transcribe" },
    { value: "gemini-3.7-flash", label: "Gemini 3.7 Flash" }
  ]

  readonly property var hotkeyDefinitions: [
    { id: "toggle", title: "Toggle dictation", description: "Press once to start, again to transcribe" },
    { id: "toggle_submit", title: "Dictate & submit", description: "Transcribe, type, and press Return" },
    { id: "push_to_talk", title: "Push to talk", description: "Hold to record, release to transcribe" },
    { id: "pause", title: "Pause / resume", description: "Pause or continue an active recording" },
    { id: "cancel", title: "Cancel recording", description: "Discard the active recording" }
  ]

  readonly property var settingsSections: [
    { id: "speech", title: "Speech & behavior", description: "Model, completion, and clipboard behavior" },
    { id: "shortcuts", title: "Keyboard shortcuts", description: "Set up global Hyprland shortcuts" },
    { id: "audio", title: "Audio & privacy", description: "Choose an input and understand data flow" },
    { id: "hud", title: "HUD & appearance", description: "Control the pill and waveform" },
    { id: "diagnostics", title: "Diagnostics", description: "Check dependencies and test your microphone" },
    { id: "about", title: "About Omarchy Flow", description: "Version, help, and reset options" }
  ]

  implicitWidth: Style.space(410)
  implicitHeight: settingsColumn.implicitHeight

  signal closeRequested()
  signal modelRequested(string modelId)

  function pageTitle() {
    if (root.settingsPage === "overview") return "Settings"
    for (var i = 0; i < root.settingsSections.length; i++) {
      if (root.settingsSections[i].id === root.settingsPage) return root.settingsSections[i].title
    }
    return "Settings"
  }

  function pageSubtitle() {
    if (root.settingsPage === "overview") return "Configure Flow for the way you work"
    for (var i = 0; i < root.settingsSections.length; i++) {
      if (root.settingsSections[i].id === root.settingsPage) return root.settingsSections[i].description
    }
    return "Configure Flow for the way you work"
  }

  function openPage(page) {
    root.settingsPage = page
    root.notice = ""
    root.audioTestResult = ""
    if (page === "audio") root.loadAudioSources()
    if (page === "shortcuts") root.loadHotkeyStatus()
    if (page === "diagnostics") root.runDiagnostics()
  }

  function goBack() {
    if (root.settingsPage === "overview") root.closeRequested()
    else {
      root.settingsPage = "overview"
      root.notice = ""
      root.audioTestResult = ""
    }
  }

  function applySettings(data) {
    if (!data || typeof data !== "object") return
    if (data.toggle_action) root.toggleAction = data.toggle_action
    if (data.audio_source) root.audioSource = data.audio_source
    if (data.copy_to_clipboard !== undefined) root.copyToClipboard = data.copy_to_clipboard === true
    if (data.hud_enabled !== undefined) root.hudEnabled = data.hud_enabled === true
    if (data.hud_position) root.hudPosition = data.hud_position
    if (data.waveform_enabled !== undefined) root.waveformEnabled = data.waveform_enabled === true
    if (data.hotkeys) root.hotkeys = data.hotkeys
  }

  function hotkeyValue(key) {
    return root.hotkeys && root.hotkeys[key] ? String(root.hotkeys[key]) : ""
  }

  function updateHotkey(key, value) {
    var updated = Object.assign({}, root.hotkeys)
    updated[key] = value
    root.hotkeys = updated
    root.notice = "Shortcut draft updated · apply to install it"
  }

  function setPreference(key, value) {
    var command = [root.flowctlPath, "set-setting", key, String(value)]
    if (settingsWriteProcess.running || root.settingWriteQueue.length > 0) {
      // Coalesce repeated edits to the same preference while preserving the
      // order of changes to different preferences.
      for (var i = 0; i < root.settingWriteQueue.length; i++) {
        if (root.settingWriteQueue[i][2] === key) {
          root.settingWriteQueue[i] = command
          return
        }
      }
      root.settingWriteQueue.push(command)
      return
    }
    settingsWriteProcess.command = command
    settingsWriteProcess.running = true
  }

  function runNextSettingWrite() {
    if (settingsWriteProcess.running || root.settingWriteQueue.length === 0) return
    settingsWriteProcess.command = root.settingWriteQueue.shift()
    settingsWriteProcess.running = true
  }

  function setLocalPreference(key, value) {
    if (key === "toggle_action") root.toggleAction = value
    else if (key === "audio_source") root.audioSource = value
    else if (key === "hud_position") root.hudPosition = value
    else if (key === "copy_to_clipboard") root.copyToClipboard = value
    else if (key === "hud_enabled") root.hudEnabled = value
    else if (key === "waveform_enabled") root.waveformEnabled = value
    root.setPreference(key, value)
  }

  function defaultHotkeys() {
    return {
      toggle: "SUPER + ALT + V",
      toggle_submit: "SUPER + ALT + SHIFT + V",
      push_to_talk: "F6",
      pause: "SUPER + ALT + P",
      cancel: "SUPER + ALT + C"
    }
  }

  function resetHotkeyDraft() {
    root.hotkeys = root.defaultHotkeys()
    root.notice = "Recommended shortcuts loaded · apply to install them"
  }

  function applyHotkeys() {
    if (hotkeyApplyProcess.running) return
    root.notice = "Applying shortcuts and reloading Hyprland…"
    hotkeyApplyProcess.command = [root.flowctlPath, "apply-hotkeys", JSON.stringify(root.hotkeys)]
    hotkeyApplyProcess.running = true
  }

  function loadAudioSources() {
    if (audioSourcesProcess.running) return
    audioSourcesProcess.running = true
  }

  function loadHotkeyStatus() {
    if (hotkeyStatusProcess.running) return
    hotkeyStatusProcess.running = true
  }

  function runDiagnostics() {
    if (doctorProcess.running) return
    doctorProcess.running = true
  }

  function runAudioTest() {
    if (audioTestProcess.running) return
    root.audioTestResult = "Testing microphone for half a second…"
    audioTestProcess.running = true
  }

  function resetPreferences() {
    if (resetProcess.running) return
    resetProcess.running = true
  }

  function openKeybindings() {
    if (!keybindingsProcess.running) keybindingsProcess.running = true
  }

  function openProject() {
    if (!projectProcess.running) projectProcess.running = true
  }

  Process {
    id: settingsProcess
    command: [root.flowctlPath, "settings"]
    running: true
    stdout: StdioCollector {
      id: settingsOutput
      waitForEnd: true
    }
    onExited: function(exitCode) {
      if (exitCode !== 0 || !settingsOutput.text) return
      try {
        root.applySettings(JSON.parse(settingsOutput.text.trim()))
      } catch (e) {}
    }
  }

  Process {
    id: settingsWriteProcess
    command: []
    stdout: StdioCollector { waitForEnd: true }
    stderr: StdioCollector { waitForEnd: true }
    onExited: function(exitCode) {
      if (exitCode === 0) root.notice = "Preference saved"
      else root.notice = "Could not save preference"
      Qt.callLater(root.runNextSettingWrite)
    }
  }

  Process {
    id: audioSourcesProcess
    command: [root.flowctlPath, "list-audio-sources"]
    stdout: StdioCollector {
      id: audioSourcesOutput
      waitForEnd: true
    }
    onExited: function(exitCode) {
      if (exitCode !== 0 || !audioSourcesOutput.text) return
      try {
        var sources = JSON.parse(audioSourcesOutput.text.trim())
        var mapped = []
        for (var i = 0; i < sources.length; i++) {
          mapped.push({ value: String(sources[i].id), label: String(sources[i].name) })
        }
        if (mapped.length > 0) root.audioOptions = mapped
      } catch (e) {}
    }
  }

  Process {
    id: hotkeyStatusProcess
    command: [root.flowctlPath, "hotkeys-status"]
    stdout: StdioCollector {
      id: hotkeyStatusOutput
      waitForEnd: true
    }
    onExited: function(exitCode) {
      if (exitCode !== 0 || !hotkeyStatusOutput.text) return
      try {
        var status = JSON.parse(hotkeyStatusOutput.text.trim())
        root.hotkeysInstalled = status.installed === true
        root.hotkeyConflicts = status.conflicts || []
        if (status.hotkeys) root.hotkeys = status.hotkeys
      } catch (e) {}
    }
  }

  Process {
    id: hotkeyApplyProcess
    command: []
    stdout: StdioCollector {
      id: hotkeyApplyOutput
      waitForEnd: true
    }
    stderr: StdioCollector {
      id: hotkeyApplyError
      waitForEnd: true
    }
    onExited: function(exitCode) {
      if (exitCode === 0) {
        root.hotkeysInstalled = true
        root.notice = "Shortcuts applied · Hyprland reloaded"
        try {
          var status = JSON.parse(hotkeyApplyOutput.text.trim())
          if (status.hotkeys) root.hotkeys = status.hotkeys
          root.hotkeyConflicts = status.conflicts || []
        } catch (e) {}
      } else {
        root.notice = hotkeyApplyError.text ? "Could not apply shortcuts · check for conflicts" : "Could not apply shortcuts"
        root.loadHotkeyStatus()
      }
    }
  }

  Process {
    id: doctorProcess
    command: [root.flowctlPath, "doctor"]
    stdout: StdioCollector {
      id: doctorOutput
      waitForEnd: true
    }
    onExited: function(exitCode) {
      if (exitCode !== 0 || !doctorOutput.text) return
      try {
        var report = JSON.parse(doctorOutput.text.trim())
        root.diagnosticChecks = report.checks || []
      } catch (e) {}
    }
  }

  Process {
    id: audioTestProcess
    command: [root.flowctlPath, "test-audio"]
    stdout: StdioCollector {
      id: audioTestOutput
      waitForEnd: true
    }
    onExited: function(exitCode) {
      try {
        var result = JSON.parse(audioTestOutput.text.trim())
        root.audioTestResult = result.message || (exitCode === 0 ? "Microphone capture works" : "Microphone capture failed")
      } catch (e) {
        root.audioTestResult = exitCode === 0 ? "Microphone capture works" : "Microphone capture failed"
      }
    }
  }

  Process {
    id: resetProcess
    command: [root.flowctlPath, "reset-settings"]
    stdout: StdioCollector { waitForEnd: true }
    onExited: function(exitCode) {
      if (exitCode === 0) {
        root.notice = "Flow preferences restored"
        settingsProcess.running = true
      } else root.notice = "Could not reset preferences"
    }
  }

  Process {
    id: keybindingsProcess
    command: ["omarchy", "menu", "keybindings"]
  }

  Process {
    id: projectProcess
    command: ["xdg-open", "https://github.com/EF-Code/omarchy-flow"]
  }

  Flickable {
    id: settingsFlickable
    anchors.fill: parent
    contentWidth: width
    contentHeight: settingsColumn.implicitHeight
    clip: true
    boundsBehavior: Flickable.StopAtBounds

    Column {
      id: settingsColumn
      width: settingsFlickable.width
      spacing: Style.space(8)

      Row {
        width: parent.width
        spacing: Style.space(8)

        Button {
          id: backButton
          text: "‹"
          foreground: root.foreground
          accent: Color.accent
          bordered: true
          onClicked: root.goBack()
        }

        Column {
          width: parent.width - backButton.width - parent.spacing
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(1)

          Text {
            text: root.pageTitle()
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.subtitle
            font.bold: true
            elide: Text.ElideRight
          }

          Text {
            width: parent.width
            text: root.pageSubtitle()
            color: root.mutedForeground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }
        }
      }

      PanelSeparator { foreground: root.foreground }

      Loader {
        id: pageLoader
        width: parent.width
        height: item ? item.implicitHeight : 0
        sourceComponent: root.settingsPage === "overview" ? overviewPage
          : root.settingsPage === "speech" ? speechPage
          : root.settingsPage === "shortcuts" ? shortcutsPage
          : root.settingsPage === "audio" ? audioPage
          : root.settingsPage === "hud" ? hudPage
          : root.settingsPage === "diagnostics" ? diagnosticsPage
          : aboutPage
      }

      Text {
        visible: root.notice !== ""
        width: parent.width
        text: root.notice
        color: root.mutedForeground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
    }
  }

  Component {
    id: overviewPage

    Column {
      width: root.width
      spacing: Style.space(6)

      Text {
        width: parent.width
        text: "Everything Flow can configure lives here. Changes are saved for your user account."
        color: root.mutedForeground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      Repeater {
        model: root.settingsSections

        BorderSurface {
          required property var modelData
          width: root.width
          height: Style.space(58)
          radius: Style.cornerRadius
          color: overviewMouse.containsMouse
            ? Style.hoverFillFor(root.foreground, Color.accent)
            : "transparent"
          borderSpec: overviewMouse.containsMouse
            ? Border.controlSpec("hover-cursor", root.foreground, Color.accent)
            : Border.none()

          Row {
            anchors.fill: parent
            anchors.leftMargin: Style.space(10)
            anchors.rightMargin: Style.space(10)
            spacing: Style.space(10)

            Column {
              width: parent.width - arrow.width - parent.spacing
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(1)

              Text {
                width: parent.width
                text: modelData.title
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                font.bold: true
                elide: Text.ElideRight
              }

              Text {
                width: parent.width
                text: modelData.description
                color: root.mutedForeground
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                elide: Text.ElideRight
              }
            }

            Text {
              id: arrow
              text: "›"
              color: root.mutedForeground
              font.family: root.fontFamily
              font.pixelSize: Style.font.subtitle
              anchors.verticalCenter: parent.verticalCenter
            }
          }

          MouseArea {
            id: overviewMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.openPage(modelData.id)
          }
        }
      }
    }
  }

  Component {
    id: speechPage

    Column {
      width: root.width
      spacing: Style.space(8)

      Text {
        width: parent.width
        text: "Choose the model and what a toggle recording should do when you finish speaking."
        color: root.mutedForeground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      Text {
        text: "Default model"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }

      FlowDropdown {
        width: parent.width
        showLabel: false
        value: root.selectedModel
        options: root.modelOptions
        foreground: root.foreground
        background: Color.popups.background
        popupBorder: Color.popups.border
        accent: Color.accent
        onChanged: root.modelRequested(value)
      }

      Text {
        text: "Toggle completion"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }

      FlowDropdown {
        width: parent.width
        showLabel: false
        value: root.toggleAction
        options: [
          { value: "transcribe", label: "Type text only" },
          { value: "submit", label: "Type text and press Return" }
        ]
        foreground: root.foreground
        background: Color.popups.background
        popupBorder: Color.popups.border
        accent: Color.accent
        onChanged: root.setLocalPreference("toggle_action", value)
      }

      Toggle {
        width: parent.width
        label: "Copy transcript to clipboard"
        description: "Keep a sensitive clipboard copy in addition to typing it"
        checked: root.copyToClipboard
        foreground: root.foreground
        accent: Color.accent
        onClicked: root.setLocalPreference("copy_to_clipboard", !root.copyToClipboard)
      }

      BorderSurface {
        width: parent.width
        implicitHeight: speechInfo.implicitHeight + Style.space(16)
        radius: Style.cornerRadius
        color: "transparent"
        borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)

        Column {
          id: speechInfo
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.leftMargin: Style.space(10)
          anchors.rightMargin: Style.space(10)
          spacing: Style.space(2)

          Text {
            text: "Privacy at a glance"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            font.bold: true
          }

          Text {
            width: parent.width
            text: root.selectedModel === "whisper-base.en"
              ? "Whisper stays local. Audio is removed after transcription."
              : "Cloud models send the recorded WAV to Google. Audio is removed after transcription."
            color: root.mutedForeground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }
        }
      }
    }
  }

  Component {
    id: shortcutsPage

    Column {
      width: root.width
      spacing: Style.space(8)

      BorderSurface {
        width: parent.width
        implicitHeight: shortcutStatus.implicitHeight + Style.space(16)
        radius: Style.cornerRadius
        color: "transparent"
        borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)

        Column {
          id: shortcutStatus
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.leftMargin: Style.space(10)
          anchors.rightMargin: Style.space(10)
          spacing: Style.space(2)

          Text {
            text: root.hotkeysInstalled ? "Flow shortcuts are active" : "Flow shortcuts are not installed"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            font.bold: true
          }

          Text {
            width: parent.width
            text: "Enter Hyprland syntax such as SUPER + ALT + V. Leave a field empty to disable that shortcut."
            color: root.mutedForeground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }
        }
      }

      Repeater {
        model: root.hotkeyDefinitions

        BorderSurface {
          required property var modelData
          width: root.width
          implicitHeight: shortcutLabel.implicitHeight + Style.space(16)
          radius: Style.cornerRadius
          color: "transparent"
          borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)

          Row {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: Style.space(10)
            anchors.rightMargin: Style.space(10)
            spacing: Style.space(8)

            Column {
              id: shortcutLabel
              width: parent.width - shortcutField.width - parent.spacing
              spacing: Style.space(1)
              anchors.verticalCenter: parent.verticalCenter

              Text {
                width: parent.width
                text: modelData.title
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                font.bold: true
                elide: Text.ElideRight
              }

              Text {
                width: parent.width
                text: modelData.description
                color: root.mutedForeground
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                elide: Text.ElideRight
              }
            }

            TextField {
              id: shortcutField
              width: Style.space(190)
              text: root.hotkeyValue(modelData.id)
              placeholderText: "Disabled"
              foreground: root.foreground
              accent: Color.accent
              font.family: root.fontFamily
              onEditingFinished: root.updateHotkey(modelData.id, text)
            }
          }
        }
      }

      Column {
        width: parent.width
        spacing: Style.space(3)
        visible: root.hotkeyConflicts.length > 0

        Text {
          text: "Existing bindings on these keys"
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }

        Repeater {
          model: root.hotkeyConflicts

          Text {
            required property var modelData
            width: parent.width
            text: "• " + modelData.shortcut + " · " + modelData.description
            color: root.mutedForeground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }
        }
      }

      Button {
        width: parent.width
        text: "Apply shortcuts"
        foreground: root.foreground
        accent: Color.accent
        bordered: true
        enabled: !hotkeyApplyProcess.running
        onClicked: root.applyHotkeys()
      }

      Row {
        width: parent.width
        spacing: Style.space(6)

        Button {
          width: (parent.width - parent.spacing) / 2
          text: "Use recommended"
          foreground: root.foreground
          accent: Color.accent
          bordered: true
          onClicked: root.resetHotkeyDraft()
        }

        Button {
          width: (parent.width - parent.spacing) / 2
          text: "Show all shortcuts"
          foreground: root.foreground
          accent: Color.accent
          bordered: true
          onClicked: root.openKeybindings()
        }
      }

      Text {
        width: parent.width
        text: "Applying creates a managed block in your Hyprland bindings and leaves the rest of your configuration intact."
        color: root.mutedForeground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
    }
  }

  Component {
    id: audioPage

    Column {
      width: root.width
      spacing: Style.space(8)

      Text {
        width: parent.width
        text: "Select the PipeWire/PulseAudio source Flow should record from."
        color: root.mutedForeground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      Text {
        text: "Input source"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }

      FlowDropdown {
        width: parent.width
        showLabel: false
        value: root.audioSource
        options: root.audioOptions
        foreground: root.foreground
        background: Color.popups.background
        popupBorder: Color.popups.border
        accent: Color.accent
        onChanged: root.setLocalPreference("audio_source", value)
      }

      Button {
        width: parent.width
        text: "Refresh input list"
        foreground: root.foreground
        accent: Color.accent
        bordered: true
        enabled: !audioSourcesProcess.running
        onClicked: root.loadAudioSources()
      }

      BorderSurface {
        width: parent.width
        implicitHeight: audioPrivacy.implicitHeight + Style.space(16)
        radius: Style.cornerRadius
        color: "transparent"
        borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)

        Column {
          id: audioPrivacy
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.leftMargin: Style.space(10)
          anchors.rightMargin: Style.space(10)
          spacing: Style.space(3)

          Text {
            text: "How audio is handled"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            font.bold: true
          }

          Text {
            width: parent.width
            text: "Whisper transcribes locally. Gemini models upload the temporary WAV only for transcription. Flow deletes the recording when the operation ends."
            color: root.mutedForeground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }
        }
      }
    }
  }

  Component {
    id: hudPage

    Column {
      width: root.width
      spacing: Style.space(8)

      Text {
        width: parent.width
        text: "Tune the floating status pill without changing the bar icon."
        color: root.mutedForeground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      Toggle {
        width: parent.width
        label: "Show transcription HUD"
        description: "Display the floating listening and transcription pill"
        checked: root.hudEnabled
        foreground: root.foreground
        accent: Color.accent
        onClicked: root.setLocalPreference("hud_enabled", !root.hudEnabled)
      }

      Text {
        text: "HUD position"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }

      FlowDropdown {
        width: parent.width
        showLabel: false
        value: root.hudPosition
        options: [
          { value: "bottom", label: "Bottom center" },
          { value: "top", label: "Top center" }
        ]
        foreground: root.foreground
        background: Color.popups.background
        popupBorder: Color.popups.border
        accent: Color.accent
        onChanged: root.setLocalPreference("hud_position", value)
      }

      Toggle {
        width: parent.width
        label: "Animated waveform"
        description: "Show the five-bar activity animation while listening"
        checked: root.waveformEnabled
        foreground: root.foreground
        accent: Color.accent
        onClicked: root.setLocalPreference("waveform_enabled", !root.waveformEnabled)
      }

      BorderSurface {
        width: parent.width
        implicitHeight: hudInfo.implicitHeight + Style.space(16)
        radius: Style.cornerRadius
        color: "transparent"
        borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)

        Column {
          id: hudInfo
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.leftMargin: Style.space(10)
          anchors.rightMargin: Style.space(10)
          spacing: Style.space(2)

          Text {
            text: "Theme adaptive"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            font.bold: true
          }

          Text {
            width: parent.width
            text: "The pill and bar mark inherit Omarchy colors and typography from your current theme."
            color: root.mutedForeground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }
        }
      }
    }
  }

  Component {
    id: diagnosticsPage

    Column {
      width: root.width
      spacing: Style.space(8)

      Text {
        width: parent.width
        text: "Flow checks the tools needed by the selected model and the current audio input."
        color: root.mutedForeground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      Column {
        width: parent.width
        spacing: Style.space(4)

        Repeater {
          model: root.diagnosticChecks

          BorderSurface {
            required property var modelData
            width: parent.width
            height: Style.space(42)
            radius: Style.cornerRadius
            color: "transparent"
            borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)

            Row {
              anchors.fill: parent
              anchors.leftMargin: Style.space(10)
              anchors.rightMargin: Style.space(10)
              spacing: Style.space(8)

              Text {
                id: statusMark
                text: modelData.ok ? "✓" : "!"
                color: modelData.ok ? root.foreground : Color.accent
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                font.bold: true
                anchors.verticalCenter: parent.verticalCenter
              }

              Column {
                width: parent.width - statusMark.width - parent.spacing
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(1)

                Text {
                  width: parent.width
                  text: modelData.label
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.bodySmall
                  elide: Text.ElideRight
                }

                Text {
                  width: parent.width
                  text: modelData.detail
                  color: root.mutedForeground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  elide: Text.ElideRight
                }
              }
            }

          }
        }
      }

      Text {
        visible: root.diagnosticChecks.length === 0
        width: parent.width
        text: "Running checks…"
        color: root.mutedForeground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      Row {
        width: parent.width
        spacing: Style.space(6)

        Button {
          width: (parent.width - parent.spacing) / 2
          text: "Run checks"
          foreground: root.foreground
          accent: Color.accent
          bordered: true
          enabled: !doctorProcess.running
          onClicked: root.runDiagnostics()
        }

        Button {
          width: (parent.width - parent.spacing) / 2
          text: "Test microphone"
          foreground: root.foreground
          accent: Color.accent
          bordered: true
          enabled: !audioTestProcess.running
          onClicked: root.runAudioTest()
        }
      }

      Text {
        visible: root.audioTestResult !== ""
        width: parent.width
        text: root.audioTestResult
        color: root.mutedForeground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
    }
  }

  Component {
    id: aboutPage

    Column {
      width: root.width
      spacing: Style.space(8)

      BorderSurface {
        width: parent.width
        implicitHeight: aboutInfo.implicitHeight + Style.space(16)
        radius: Style.cornerRadius
        color: "transparent"
        borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)

        Column {
          id: aboutInfo
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.leftMargin: Style.space(10)
          anchors.rightMargin: Style.space(10)
          spacing: Style.space(3)

          Text {
            text: "Omarchy Flow 0.3.0"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.subtitle
            font.bold: true
          }

          Text {
            width: parent.width
            text: "Voice dictation with local Whisper and Gemini transcription, designed for Omarchy."
            color: root.mutedForeground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }
        }
      }

      Button {
        width: parent.width
        text: "Open project page"
        foreground: root.foreground
        accent: Color.accent
        bordered: true
        enabled: !projectProcess.running
        onClicked: root.openProject()
      }

      Button {
        width: parent.width
        text: "Reset Flow preferences"
        foreground: root.foreground
        accent: Color.accent
        bordered: true
        enabled: !resetProcess.running
        onClicked: root.resetPreferences()
      }

      Text {
        width: parent.width
        text: "Resetting restores defaults for behavior, audio, HUD, and Flow shortcuts. It does not delete your API key or recordings from other applications."
        color: root.mutedForeground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
    }
  }
}
