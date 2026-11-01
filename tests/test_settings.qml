import QtQuick
import Quickshell
import "FlowPaths.js" as FlowPaths

Scope {
  id: root
  property int stage: 0
  function path(name) { return FlowPaths.localPath(Qt.resolvedUrl(name)) }
  function check(condition, message) { if (!condition) throw new Error(message) }

  SettingsView { id: settings; flowctlPath: root.path("fixtures/slow-settings"); modelOptions: [] }
  SettingsView { id: failedWrite; flowctlPath: root.path("fixtures/settings-write-fails"); modelOptions: [] }

  Timer {
    interval: 50
    running: true
    repeat: true
    onTriggered: {
      try {
        if (root.stage === 0) {
          settings.setLocalPreference("hud_position", "top")
          for (var i = 0; i < 50; i++) settings.setLocalPreference("copy_to_clipboard", i % 2 === 0)
          settings.setLocalPreference("waveform_enabled", false)
          root.check(settings.settingWriteQueue.length === 2, "rapid edits are not coalesced by preference key")
          root.check(settings.settingWriteQueue[0][3] === "copy_to_clipboard", "preference order changed")
          root.check(settings.settingWriteQueue[0][4] === "false", "latest preference value was lost")
          settings.resetPreferences()
          root.check(settings.notice.indexOf("pending preferences") !== -1, "reset overtakes queued writes")
          root.stage = 1
        } else if (root.stage === 1) {
          if (settings.preferencesSaving || settings.notice !== "Preference saved") return
          settings.reloadSettings()
          failedWrite.reloadSettings()
          root.stage = 2
        } else if (root.stage === 2) {
          if (failedWrite.copyToClipboard !== false || failedWrite.hudPosition !== "top" || failedWrite.waveformEnabled !== false) return
          root.check(settings.hudPosition === "top" && !settings.copyToClipboard && !settings.waveformEnabled, "initial settings read overwrote pending preferences")
          failedWrite.setLocalPreference("copy_to_clipboard", true)
          root.stage = 3
        } else if (root.stage === 3) {
          if (failedWrite.notice !== "Could not save preference" || failedWrite.copyToClipboard !== false) return
          settings.resetPreferences()
          settings.setLocalPreference("copy_to_clipboard", false)
          root.check(settings.settingWriteQueue.length === 1, "preference edit overtakes active reset")
          root.stage = 4
        } else if (root.stage === 4) {
          if (settings.preferencesSaving || settings.hudPosition !== "bottom" || !settings.waveformEnabled || settings.copyToClipboard !== false) return
          failedWrite.reloadSettings()
          root.stage = 5
        } else if (root.stage === 5) {
          if (failedWrite.hudPosition !== "bottom" || !failedWrite.waveformEnabled || failedWrite.copyToClipboard !== false) return
          console.log("FLOW_SETTINGS_TEST_PASS")
          Qt.quit()
        }
      } catch (error) {
        console.error("FLOW_SETTINGS_TEST_FAIL: " + error)
        Qt.quit()
      }
    }
  }
  Timer {
    interval: 15000
    running: true
    onTriggered: { console.error("FLOW_SETTINGS_TEST_FAIL: timeout at stage " + root.stage + " (" + settings.notice + ")"); Qt.quit() }
  }
}
