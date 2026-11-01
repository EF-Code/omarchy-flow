import QtQuick
import Quickshell
import "FlowPaths.js" as FlowPaths

Scope {
  id: root
  property int stage: 0
  function path(name) { return FlowPaths.localPath(Qt.resolvedUrl(name)) }
  function check(condition, message) { if (!condition) throw new Error(message) }

  FlowModelCatalog { id: failedCatalog; flowctlPath: root.path("fixtures/fail") }
  FlowModelCatalog { id: malformedCatalog; flowctlPath: root.path("fixtures/malformed") }
  FlowModelCatalog { id: timedOutCatalog; flowctlPath: root.path("fixtures/timeout") }
  FlowModelState { id: menuState; flowctlPath: root.path("fixtures/slow-save") }
  FlowModelState { id: settingsState; flowctlPath: root.path("fixtures/fail") }
  FlowModelState { id: failedWrite; flowctlPath: root.path("fixtures/write-fails") }
  FlowModelState { id: badStatus; flowctlPath: root.path("fixtures/bad-status") }
  // Exercise the state and bindings shared by the HUD without opening a real
  // Wayland layer surface in the offscreen test process.
  Item {
    id: pill
    readonly property string selectedModel: pillState.ready ? pillState.selectedModel : ""
    readonly property string displayedModel: pillState.displayedModel
    FlowModelState { id: pillState; flowctlPath: root.path("fixtures/fail") }
  }

  Timer {
    interval: 50
    repeat: true
    running: true
    onTriggered: {
      try {
        root.check(!badStatus.ready, "malformed status confirmed a local selection")
        if (root.stage === 0) {
          if (!menuState.ready || !settingsState.ready || !failedWrite.ready || !pill.selectedModel) return
          root.check(menuState.selectedModel === "gemini-3.5-transcribe", "saved cloud selection hidden")
          root.check(menuState.displayedModel === "gemini-3.5-transcribe", "cloud model displayed as offline")
          root.check(menuState.recordingCommand("start")[3] === "gemini-3.5-transcribe", "confirmed start lost model expectation")
          root.check(pill.displayedModel === "gemini-3.5-transcribe", "pill masks cloud without catalog")
          root.check(failedCatalog.models.length === 1 && !failedCatalog.ready, "failed-catalog fixture ineffective")
          root.check(!menuState.selectModel("whisper-base.en\nextra"), "invalid model accepted")
          root.check(menuState.selectModel("whisper-base.en"), "explicit fallback-local choice rejected")
          root.check(!menuState.ready, "unacknowledged selection marked confirmed")
          root.check(menuState.recordingCommand("start").length === 0, "unconfirmed write permits new capture")
          root.check(menuState.recordingCommand("toggle")[3] === "unconfirmed", "unconfirmed toggle cannot reach safe stop")
          root.stage = 1
        } else if (root.stage === 1) {
          if (!menuState.ready || settingsState.selectedModel !== "whisper-base.en" || pill.selectedModel !== "whisper-base.en") return
          root.check(menuState.selectedModel === "whisper-base.en", "local save not confirmed")
          root.check(menuState.selectModel("whisper-base.en"), "explicit repeated local choice skipped")
          root.check(!menuState.ready && menuState.saving, "repeated choice did not persist")
          root.stage = 2
        } else if (root.stage === 2) {
          if (!menuState.ready) return
          // The pill's selector uses the same shared state boundary.
          root.check(settingsState.selectModel("gemini-3.8-flash"), "cloud change rejected")
          root.stage = 3
        } else if (root.stage === 3) {
          if (menuState.selectedModel !== "gemini-3.8-flash" || pill.selectedModel !== "gemini-3.8-flash" || failedWrite.selectedModel !== "gemini-3.8-flash") return
          root.check(failedWrite.selectModel("whisper-base.en"), "write-failure trigger rejected")
          root.check(!failedWrite.ready, "failed write optimistically claims local")
          root.stage = 4
        } else if (root.stage === 4) {
          if (!failedWrite.ready || timedOutCatalog.attempts < 2) return
          root.check(failedWrite.selectedModel === "gemini-3.8-flash", "failed local write masks saved cloud")
          root.check(!malformedCatalog.ready && !timedOutCatalog.ready, "bad catalog marked ready")
          root.check(!menuState.acceptStatus("x".repeat(8193)), "oversized status accepted")
          root.check(!menuState.acceptStatus('{"model":"local<script>","recording":false,"paused":false,"recording_model":""}'), "malformed ID accepted")
          menuState.invalidate()
          root.check(!menuState.ready && menuState.displayedModel === "", "invalidated state claims a model")
          root.check(menuState.recordingCommand("start").length === 0, "failed refresh permits start")
          root.check(menuState.recordingCommand("toggle")[3] === "unconfirmed", "failed refresh blocks stopping audio")
          root.check(menuState.recordingCommand("toggle-submit")[3] === "unconfirmed", "submit toggle loses expectation")
          console.log("FLOW_MODEL_STATE_TEST_PASS")
          Qt.quit()
        }
      } catch (error) {
        console.error("FLOW_MODEL_STATE_TEST_FAIL: " + error)
        Qt.quit()
      }
    }
  }
  Timer {
    interval: 20000
    running: true
    onTriggered: {
      console.error("FLOW_MODEL_STATE_TEST_FAIL: timed out at stage " + root.stage)
      Qt.quit()
    }
  }
}
