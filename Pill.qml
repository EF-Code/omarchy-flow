import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

Item {
    id: root

    property bool isVisible: false
    property string stateMode: "listening" // "listening", "paused", "transcribing", "status", "done"
    property string statusText: ""
    property bool dropdownOpen: false
    property string selectedModel: "whisper-base.en"
    property bool hudEnabled: true
    property string hudPosition: "bottom"
    property bool waveformEnabled: true

    readonly property string flowctlPath: decodeURIComponent(String(Qt.resolvedUrl("scripts/flowctl")).replace(/^file:\/\//, ""))
    readonly property int maxTextLength: 256

    function sanitizedStatusText(raw) {
        if (!raw || typeof raw !== "string") return ""
        var s = raw.trim()
        if (s.length > 128) s = s.slice(0, 128)
        return s
    }

    function sanitizedModelId(raw) {
        if (!raw || typeof raw !== "string") return "whisper-base.en"
        var s = raw.trim()
        if (s.length > 64) s = s.slice(0, 64)
        if (s === "whisper-base.en" || s === "gemini-3.5-transcribe" || s === "gemini-3.7-flash") return s
        return "whisper-base.en"
    }

    function runProcess(process): string {
        if (!process || process.running) return "busy"
        process.running = true
        return "ok"
    }

    // Load saved model on startup
    Process {
        id: loadModelProcess
        command: [root.flowctlPath, "model"]
        running: true
        stdout: SplitParser {
            onRead: function(data) {
                var m = data.trim()
                if (m.length > 64) m = m.slice(0, 64)
                if (m) {
                    root.selectedModel = root.sanitizedModelId(m)
                }
            }
        }
        Component.onDestruction: if (running) running = false
    }

    Timer {
        interval: 3000
        running: loadModelProcess.running
        onTriggered: loadModelProcess.running = false
    }

    // Save model process
    Process {
        id: saveModelProcess
        command: []
        function save(modelId: string): string {
            if (running) return "busy"
            var safe = root.sanitizedModelId(modelId)
            command = [root.flowctlPath, "model", safe]
            running = true
            return "ok"
        }
        Component.onDestruction: if (running) running = false
    }

    Timer {
        interval: 5000
        running: saveModelProcess.running
        onTriggered: saveModelProcess.running = false
    }

    Process {
        id: loadSettingsProcess
        command: [root.flowctlPath, "settings"]
        running: true
        stdout: StdioCollector {
            id: settingsOutput
            waitForEnd: true
        }
        onExited: function(exitCode) {
            if (exitCode !== 0 || !settingsOutput.text) return
            try {
                var raw = settingsOutput.text
                if (raw.length > 8192) raw = raw.slice(0, 8192)
                var settings = JSON.parse(raw.trim())
                if (settings.hud_enabled !== undefined) root.hudEnabled = settings.hud_enabled === true
                if (settings.hud_position === "top" || settings.hud_position === "bottom") root.hudPosition = settings.hud_position
                if (settings.waveform_enabled !== undefined) root.waveformEnabled = settings.waveform_enabled === true
            } catch (e) {}
        }
        Component.onDestruction: if (running) running = false
    }

    Timer {
        interval: 5000
        running: loadSettingsProcess.running
        onTriggered: loadSettingsProcess.running = false
    }

    IpcHandler {
        id: geminiHandler
        target: "geminipill"

        function setListening(): string {
            hideTimer.stop()
            root.statusText = "Listening..."
            root.stateMode = "listening"
            root.isVisible = true
            root.dropdownOpen = false
            return "ok"
        }

        function setPaused(): string {
            hideTimer.stop()
            root.statusText = "Paused"
            root.stateMode = "paused"
            root.isVisible = true
            root.dropdownOpen = false
            return "ok"
        }

        function setResumed(): string {
            hideTimer.stop()
            root.statusText = "Listening..."
            root.stateMode = "listening"
            root.isVisible = true
            root.dropdownOpen = false
            return "ok"
        }

        function setTranscribing(text: string): string {
            hideTimer.stop()
            // Keep the in-progress label stable and concise. Temporary errors
            // and notices use the separate status state below.
            root.statusText = "Transcribing..."
            root.stateMode = "transcribing"
            root.isVisible = true
            root.dropdownOpen = false
            return "ok"
        }

        function setDone(): string {
            hideTimer.stop()
            root.stateMode = "done"
            root.statusText = "Done"
            root.isVisible = true
            root.dropdownOpen = false
            hideTimer.interval = 700
            hideTimer.restart()
            return "ok"
        }

        function setStatus(text: string): string {
            var safe = root.sanitizedStatusText(text) || "Status"
            root.statusText = safe
            root.stateMode = "status"
            root.isVisible = true
            root.dropdownOpen = false
            hideTimer.interval = 1800
            hideTimer.restart()
            return "ok"
        }

        function hide(): string {
            hideTimer.stop()
            root.isVisible = false
            root.dropdownOpen = false
            return "ok"
        }

        function toggle(): string {
            return root.runProcess(toggleProcess)
        }
    }

    IpcHandler {
        target: "io.github.ef-code.omarchy-flow.pill"

        function setListening(): string { return geminiHandler.setListening() }
        function setPaused(): string { return geminiHandler.setPaused() }
        function setResumed(): string { return geminiHandler.setResumed() }
        function setTranscribing(text: string): string { return geminiHandler.setTranscribing(text) }
        function setDone(): string { return geminiHandler.setDone() }
        function setStatus(text: string): string { return geminiHandler.setStatus(text) }
        function hide(): string { return geminiHandler.hide() }
        function toggle(): string {
            return root.runProcess(toggleProcess)
        }
    }

    Timer {
        id: hideTimer
        interval: 1000
        onTriggered: {
            root.isVisible = false
            root.dropdownOpen = false
        }
    }

    Timer {
        interval: 3000
        repeat: true
        running: true
        onTriggered: if (!loadSettingsProcess.running) loadSettingsProcess.running = true
    }

    // Process runners for button clicks and actions
    Process {
        id: pauseProcess
        command: [root.flowctlPath, "pause"]
        Component.onDestruction: if (running) running = false
    }
    Timer { interval: 8000; running: pauseProcess.running; onTriggered: pauseProcess.running = false }
    Process {
        id: transcribeProcess
        command: [root.flowctlPath, "stop"]
        Component.onDestruction: if (running) running = false
    }
    Timer { interval: 15000; running: transcribeProcess.running; onTriggered: transcribeProcess.running = false }
    Process {
        id: cancelProcess
        command: [root.flowctlPath, "cancel"]
        Component.onDestruction: if (running) running = false
    }
    Timer { interval: 8000; running: cancelProcess.running; onTriggered: cancelProcess.running = false }
    Process {
        id: toggleProcess
        command: [root.flowctlPath, "toggle"]
        Component.onDestruction: if (running) running = false
    }
    Timer { interval: 10000; running: toggleProcess.running; onTriggered: toggleProcess.running = false }

    PanelWindow {
        id: panel
        visible: root.hudEnabled && (root.isVisible || card.opacity > 0)
        anchors {
            top: root.hudPosition === "top"
            bottom: root.hudPosition === "bottom"
        }
        margins {
            top: root.hudPosition === "top" ? 60 : 0
            bottom: root.hudPosition === "bottom" ? 110 : 0
        }
        implicitWidth: Math.max(card.width, (dropdownMenu.visible ? dropdownMenu.width : 0))
        implicitHeight: card.height + (dropdownMenu.visible ? (dropdownMenu.height + 10) : 0)
        color: "transparent"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        WlrLayershell.namespace: "omarchy-flow-pill"
        exclusionMode: ExclusionMode.Ignore

        Item {
            anchors.fill: parent

            // Dropdown Menu Card (Crystal Liquid Glass Dropdown)
            Rectangle {
                id: dropdownMenu
                visible: root.dropdownOpen && (root.stateMode === "listening" || root.stateMode === "paused")
                width: 210
                height: menuCol.implicitHeight + 16
                radius: 16
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: card.top
                anchors.bottomMargin: 10

                border.color: "#45FFFFFF"
                border.width: 1

                gradient: Gradient {
                    GradientStop { position: 0.0; color: "#35FFFFFF" }
                    GradientStop { position: 0.2; color: "#2212121C" }
                    GradientStop { position: 1.0; color: "#2812121C" }
                }

                opacity: visible ? 0.98 : 0.0
                Behavior on opacity {
                    NumberAnimation { duration: 140 }
                }

                Column {
                    id: menuCol
                    anchors.centerIn: parent
                    spacing: 3
                    width: parent.width - 16

                    Repeater {
                        model: [
                            { id: "whisper-base.en", title: "Local Whisper", subtitle: "base.en • Offline" },
                            { id: "gemini-3.5-transcribe", title: "Gemini 3.5 Transcribe", subtitle: "Cloud • Dedicated transcription" },
                            { id: "gemini-3.7-flash", title: "Gemini 3.7 Flash", subtitle: "Cloud • Speech transcription" }
                        ]

                        Rectangle {
                            width: menuCol.width
                            height: 36
                            radius: 10
                            color: root.selectedModel === modelData.id ? "#35FFFFFF" : (itemMouse.containsMouse ? "#1EFFFFFF" : "transparent")
                            border.color: root.selectedModel === modelData.id ? "#50FFFFFF" : "transparent"
                            border.width: 1

                            Row {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                spacing: 8

                                Column {
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 1

                                    Text {
                                        text: modelData.title
                                        font.pixelSize: 11
                                        font.weight: root.selectedModel === modelData.id ? Font.DemiBold : Font.Normal
                                        color: root.selectedModel === modelData.id ? "#FFFFFF" : "#F1F5F9"
                                        textFormat: Text.PlainText
                                    }
                                    Text {
                                        text: modelData.subtitle
                                        font.pixelSize: 9
                                        color: "#CBD5E1"
                                        textFormat: Text.PlainText
                                    }
                                }
                            }

                            // Active Check indicator
                            Text {
                                visible: root.selectedModel === modelData.id
                                anchors.right: parent.right
                                anchors.rightMargin: 12
                                anchors.verticalCenter: parent.verticalCenter
                                text: "✓"
                                font.pixelSize: 12
                                font.bold: true
                                color: "#FFFFFF"
                                textFormat: Text.PlainText
                            }

                            MouseArea {
                                id: itemMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    root.selectedModel = modelData.id
                                    saveModelProcess.save(modelData.id)
                                    root.dropdownOpen = false
                                }
                            }
                        }
                    }
                }
            }

            // Crystal iOS Liquid Glass Floating Capsule (Unified Single-Layer Glass Body)
            Rectangle {
                id: card
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                width: contentRow.implicitWidth + 24
                height: 48
                radius: 24

                // Unified liquid glass gradient
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "#32FFFFFF" }
                    GradientStop { position: 0.35; color: "#14101018" }
                    GradientStop { position: 1.0; color: "#18101018" }
                }

                opacity: root.isVisible ? 0.98 : 0.0
                border.color: "#50FFFFFF"
                border.width: 1

                Behavior on opacity {
                    NumberAnimation { duration: 160; easing.type: Easing.OutQuad }
                }
                Behavior on width {
                    NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
                }

                Row {
                    id: contentRow
                    anchors.centerIn: parent
                    spacing: 9

                    // 1. Google 5-Color Waveform Equalizer (High Luminance Vibrant Bars)
                    Row {
                        id: barsRow
                        visible: root.waveformEnabled
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2.5

                        // Green
                        Rectangle {
                            width: 3
                            radius: 1.5
                            color: "#22C55E"
                            height: root.isVisible ? bar1Height : 10
                            anchors.verticalCenter: parent.verticalCenter
                            property real bar1Height: 12
                            SequentialAnimation on bar1Height {
                                running: root.isVisible && root.stateMode === "listening"
                                loops: Animation.Infinite
                                NumberAnimation { to: 22; duration: 300; easing.type: Easing.InOutSine }
                                NumberAnimation { to: 7; duration: 250; easing.type: Easing.InOutSine }
                                NumberAnimation { to: 15; duration: 280; easing.type: Easing.InOutSine }
                            }
                        }

                        // Light Green
                        Rectangle {
                            width: 3
                            radius: 1.5
                            color: "#4ADE80"
                            height: root.isVisible ? bar2Height : 13
                            anchors.verticalCenter: parent.verticalCenter
                            property real bar2Height: 15
                            SequentialAnimation on bar2Height {
                                running: root.isVisible && root.stateMode === "listening"
                                loops: Animation.Infinite
                                NumberAnimation { to: 9; duration: 240; easing.type: Easing.InOutSine }
                                NumberAnimation { to: 25; duration: 320; easing.type: Easing.InOutSine }
                                NumberAnimation { to: 13; duration: 260; easing.type: Easing.InOutSine }
                            }
                        }

                        // Blue
                        Rectangle {
                            width: 3
                            radius: 1.5
                            color: "#3B82F6"
                            height: root.isVisible ? bar3Height : 17
                            anchors.verticalCenter: parent.verticalCenter
                            property real bar3Height: 18
                            SequentialAnimation on bar3Height {
                                running: root.isVisible && (root.stateMode === "listening" || root.stateMode === "transcribing")
                                loops: Animation.Infinite
                                NumberAnimation { to: 26; duration: root.stateMode === "listening" ? 280 : 480; easing.type: Easing.InOutSine }
                                NumberAnimation { to: 8; duration: root.stateMode === "listening" ? 290 : 490; easing.type: Easing.InOutSine }
                                NumberAnimation { to: 18; duration: root.stateMode === "listening" ? 250 : 450; easing.type: Easing.InOutSine }
                            }
                        }

                        // Red
                        Rectangle {
                            width: 3
                            radius: 1.5
                            color: "#EF4444"
                            height: root.isVisible ? bar4Height : 17
                            anchors.verticalCenter: parent.verticalCenter
                            property real bar4Height: 19
                            SequentialAnimation on bar4Height {
                                running: root.isVisible && (root.stateMode === "listening" || root.stateMode === "transcribing")
                                loops: Animation.Infinite
                                NumberAnimation { to: 8; duration: root.stateMode === "listening" ? 330 : 530; easing.type: Easing.InOutSine }
                                NumberAnimation { to: 26; duration: root.stateMode === "listening" ? 250 : 450; easing.type: Easing.InOutSine }
                                NumberAnimation { to: 14; duration: root.stateMode === "listening" ? 300 : 500; easing.type: Easing.InOutSine }
                            }
                        }

                        // Yellow
                        Rectangle {
                            width: 3
                            radius: 1.5
                            color: "#F59E0B"
                            height: root.isVisible ? bar5Height : 13
                            anchors.verticalCenter: parent.verticalCenter
                            property real bar5Height: 14
                            SequentialAnimation on bar5Height {
                                running: root.isVisible && root.stateMode === "listening"
                                loops: Animation.Infinite
                                NumberAnimation { to: 23; duration: 270; easing.type: Easing.InOutSine }
                                NumberAnimation { to: 7; duration: 310; easing.type: Easing.InOutSine }
                                NumberAnimation { to: 16; duration: 260; easing.type: Easing.InOutSine }
                            }
                        }
                    }

                    // 2. Liquid Glass Model Trigger / Status
                    Rectangle {
                        id: modelBadge
                        height: 28
                        width: modelRow.implicitWidth + 14
                        radius: 14
                        color: modelMouse.containsMouse || root.dropdownOpen ? "#30FFFFFF" : "#14FFFFFF"
                        border.color: modelMouse.containsMouse || root.dropdownOpen ? "#55FFFFFF" : "#28FFFFFF"
                        border.width: 1
                        anchors.verticalCenter: parent.verticalCenter

                        Behavior on color {
                            ColorAnimation { duration: 120 }
                        }

                        Row {
                            id: modelRow
                            anchors.centerIn: parent
                            spacing: 4

                            Text {
                                text: {
                                    if (root.stateMode === "paused") return "Paused"
                                    if (root.stateMode === "done") return root.statusText || "Done"
                                    if (root.stateMode === "status") return root.statusText || "Status"
                                    if (root.stateMode === "transcribing") return "Transcribing..."
                                    if (root.selectedModel === "whisper-base.en") return "Whisper"
                                    if (root.selectedModel === "gemini-3.5-transcribe") return "3.5 Transcribe"
                                    if (root.selectedModel === "gemini-3.7-flash") return "3.7 Flash"
                                    return root.selectedModel
                                }
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                                color: {
                                    if (root.stateMode === "paused") return "#FBBF24"
                                    if (root.stateMode === "status") return "#FBBF24"
                                    if (root.stateMode === "done") return "#4ADE80"
                                    return "#FFFFFF"
                                }
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                            }
                            Text {
                                visible: root.stateMode === "listening" || root.stateMode === "paused"
                                text: root.dropdownOpen ? "▴" : "▾"
                                font.pixelSize: 9
                                color: "#CBD5E1"
                                textFormat: Text.PlainText
                            }
                        }

                        MouseArea {
                            id: modelMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (root.stateMode === "listening" || root.stateMode === "paused") {
                                    root.dropdownOpen = !root.dropdownOpen
                                }
                            }
                        }
                    }

                    // 3. Subtle Glass Divider
                    Rectangle {
                        visible: root.stateMode === "listening" || root.stateMode === "paused"
                        width: 1
                        height: 16
                        color: "#35FFFFFF"
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    // 4. Liquid Glass Action Buttons (Unified Crystal Liquid Glass Styling)
                    Row {
                        id: buttonsRow
                        visible: root.stateMode === "listening" || root.stateMode === "paused"
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 4.5

                        // Button 1: Sleek Pause / Resume
                        Rectangle {
                            id: pauseBtn
                            width: 26
                            height: 26
                            radius: 13
                            color: pauseMouse.containsMouse ? "#30FFFFFF" : "#14FFFFFF"
                            border.color: root.stateMode === "paused" ? "#60FBBF24" : (pauseMouse.containsMouse ? "#50FFFFFF" : "#25FFFFFF")
                            border.width: 1
                            anchors.verticalCenter: parent.verticalCenter

                            Item {
                                anchors.centerIn: parent
                                width: 10
                                height: 10

                                Row {
                                    visible: root.stateMode !== "paused"
                                    anchors.centerIn: parent
                                    spacing: 3

                                    Rectangle {
                                        width: 2.2
                                        height: 9
                                        radius: 1.1
                                        color: pauseMouse.containsMouse ? "#FFFFFF" : "#E2E8F0"
                                    }
                                    Rectangle {
                                        width: 2.2
                                        height: 9
                                        radius: 1.1
                                        color: pauseMouse.containsMouse ? "#FFFFFF" : "#E2E8F0"
                                    }
                                }

                                Text {
                                    visible: root.stateMode === "paused"
                                    anchors.centerIn: parent
                                    text: "▶"
                                    font.pixelSize: 10
                                    color: "#FBBF24"
                                    textFormat: Text.PlainText
                                }
                            }

                            MouseArea {
                                id: pauseMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    root.dropdownOpen = false
                                    root.runProcess(pauseProcess)
                                }
                            }
                        }

                        // Button 2: Transcribe / Submit (Liquid Glass Tick Icon)
                        Rectangle {
                            id: transcribeBtn
                            width: 26
                            height: 26
                            radius: 13
                            color: transcribeMouse.containsMouse ? "#35FFFFFF" : "#14FFFFFF"
                            border.color: transcribeMouse.containsMouse ? "#60FFFFFF" : "#25FFFFFF"
                            border.width: 1
                            anchors.verticalCenter: parent.verticalCenter

                            Text {
                                anchors.centerIn: parent
                                text: "✓"
                                font.pixelSize: 13
                                font.bold: true
                                color: transcribeMouse.containsMouse ? "#FFFFFF" : "#F1F5F9"
                                textFormat: Text.PlainText
                            }

                            MouseArea {
                                id: transcribeMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    root.dropdownOpen = false
                                    root.runProcess(transcribeProcess)
                                }
                            }
                        }

                        // Button 3: Cancel (Liquid Glass X)
                        Rectangle {
                            id: cancelBtn
                            width: 26
                            height: 26
                            radius: 13
                            color: cancelMouse.containsMouse ? "#35EF4444" : "#14FFFFFF"
                            border.color: cancelMouse.containsMouse ? "#EF4444" : "#25FFFFFF"
                            border.width: 1
                            anchors.verticalCenter: parent.verticalCenter

                            Text {
                                anchors.centerIn: parent
                                text: "✕"
                                font.pixelSize: 11
                                color: cancelMouse.containsMouse ? "#EF4444" : "#E2E8F0"
                                textFormat: Text.PlainText
                            }

                            MouseArea {
                                id: cancelMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    root.dropdownOpen = false
                                    root.runProcess(cancelProcess)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
