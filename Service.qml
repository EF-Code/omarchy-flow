import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: root

  readonly property string flowctlPath: decodeURIComponent(String(Qt.resolvedUrl("scripts/flowctl")).replace(/^file:\/\//, ""))
  property var actionQueue: []

  function runNextAction() {
    if (actionProcess.running || root.actionQueue.length === 0) return
    actionProcess.command = root.actionQueue.shift()
    actionProcess.running = true
  }

  function runAction(action, extraArg) {
    var cmd = [root.flowctlPath, action]
    if (extraArg !== undefined && extraArg !== null && String(extraArg).trim() !== "") {
      cmd.push(String(extraArg))
    }
    if (actionProcess.running || root.actionQueue.length > 0) {
      if (root.actionQueue.length >= 8) return "busy"
      root.actionQueue.push(cmd)
      return "queued"
    }
    actionProcess.command = cmd
    actionProcess.running = true
    return "ok"
  }

  Process {
    id: actionProcess
    command: []
    onRunningChanged: {
      if (!running) Qt.callLater(root.runNextAction)
    }
  }

  // Upgrade only an existing Flow-managed block. This never installs
  // shortcuts for users who have not opted into them.
  Process {
    command: [root.flowctlPath, "migrate-hotkeys"]
    running: true
  }

  IpcHandler {
    target: "io.github.ef-code.omarchy-flow.service"

    function toggle(): string { return root.runAction("toggle") }
    function toggleSubmit(): string { return root.runAction("toggle-submit") }
    function start(): string { return root.runAction("start") }
    function stop(): string { return root.runAction("stop") }
    function submit(): string { return root.runAction("submit") }
    function pause(): string { return root.runAction("pause") }
    function resume(): string { return root.runAction("resume") }
    function cancel(): string { return root.runAction("cancel") }
    function setModel(modelId: string): string { return root.runAction("set-model", modelId) }
  }

  // Keep the short pre-0.2 target working while the service owns both
  // registrations. The bar widget intentionally does not register IPC of its
  // own, which avoids target collisions when the shell creates one widget per
  // monitor.
  IpcHandler {
    target: "io.github.ef-code.omarchy-flow"

    function toggle(): string { return root.runAction("toggle") }
    function toggleSubmit(): string { return root.runAction("toggle-submit") }
    function start(): string { return root.runAction("start") }
    function stop(): string { return root.runAction("stop") }
    function submit(): string { return root.runAction("submit") }
    function pause(): string { return root.runAction("pause") }
    function resume(): string { return root.runAction("resume") }
    function cancel(): string { return root.runAction("cancel") }
    function setModel(modelId: string): string { return root.runAction("set-model", modelId) }
  }
}
