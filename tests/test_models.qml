import QtQuick
import Quickshell
import "FlowPaths.js" as FlowPaths

Scope {
  id: root

  function check(condition, message) {
    if (!condition) throw new Error(message)
  }

  FlowModelCatalog {
    id: catalog
    flowctlPath: FlowPaths.localPath(Qt.resolvedUrl("scripts/flowctl"))
  }

  Timer {
    interval: 50
    running: true
    repeat: true
    onTriggered: {
      if (!catalog.ready) return
      try {
        root.check(FlowPaths.localPath("qs:///tmp/Flow%20Test/scripts/flowctl") === "/tmp/Flow Test/scripts/flowctl", "qs URL was not decoded")
        root.check(FlowPaths.localPath("file:///tmp/Flow%20Test/scripts/flowctl") === "/tmp/Flow Test/scripts/flowctl", "file URL was not decoded")
        root.check(FlowPaths.localPath("https://example.invalid/flowctl") === "", "remote URL accepted as executable path")
        root.check(catalog.find("gemini-4-argon") === null, "paid-only model offered")
        root.check(catalog.find("gemini-3.8-flash") !== null, "Flash model missing")
        root.check(catalog.find("gemini-3.5-flash-lite") === null, "removed Flash-Lite model offered")
        root.check(catalog.models.length === 3, "unexpected model catalog size")
        root.check(catalog.dropdownOptions.length === catalog.models.length, "settings catalog differs")
        var before = JSON.stringify(catalog.models)
        root.check(!catalog.accept("x".repeat(16385)), "oversized input accepted")
        root.check(!catalog.accept("null"), "null catalog accepted")
        root.check(!catalog.accept("[]"), "empty catalog accepted")
        root.check(!catalog.accept("{"), "invalid JSON accepted")
        root.check(!catalog.accept(JSON.stringify([catalog.models[0], catalog.models[0]])), "duplicate ids accepted")
        var invalid = JSON.parse(before)
        invalid[1].shortName = "x".repeat(129)
        root.check(!catalog.accept(JSON.stringify(invalid)), "oversized label accepted")
        root.check(JSON.stringify(catalog.models) === before, "failed parse changed catalog")
        console.log("FLOW_MODEL_TEST_PASS")
      } catch (error) {
        console.error("FLOW_MODEL_TEST_FAIL: " + error)
      }
      Qt.quit()
    }
  }

  Timer {
    interval: 7000
    running: true
    onTriggered: {
      console.error("FLOW_MODEL_TEST_FAIL: catalog startup timeout")
      Qt.quit()
    }
  }
}
