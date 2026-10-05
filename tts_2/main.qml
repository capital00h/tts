import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs

ApplicationWindow {
    id: window
    width: 800
    height: 540
    minimumWidth: 720
    minimumHeight: 480
    visible: true
    title: "GAME VOICE TTS"
    color: "#030303" // Pure pitch black

    // Property State Tracking
    property string currentStatus: "READY"
    property real sttMs: 0
    property real ttsMs: 0
    property real totalMs: 0
    property int audioLevel: 0
    property bool isPausedState: false

    Connections {
        target: backend
        function onStatusChanged(status) { window.currentStatus = status }
        function onMetricsChanged(stt, tts, tot) {
            window.sttMs = stt; window.ttsMs = tts; window.totalMs = tot
        }
        function onLevelChanged(level) { window.audioLevel = level }
        function onShowWarning(title, message) {
            warningDialog.dialogTitle = title
            warningDialog.dialogMessage = message
            warningDialog.open()
        }
    }

    // --- ACCENT COLOR PALETTE ---
    readonly property color cBg: "#050508"
    readonly property color cPanel: "#0D0E12"
    readonly property color cBorder: "#1E202B"
    readonly property color cAccent: "#00F0FF" // Neon Cyan
    readonly property color cAccentDim: "#005560"
    readonly property color cDanger: "#FF0055" // Neon Red
    readonly property color cText: "#FFFFFF"
    readonly property color cTextMuted: "#666C7A"

    readonly property var statusColors: ({
        "READY": cAccent,
        "LISTENING": "#F0B45A",
        "PROCESSING": cAccent,
        "SPEAKING": "#E58AB8"
    })
    function statusColor(status) {
        return statusColors.hasOwnProperty(status) ? statusColors[status] : cDanger
    }

    // ------------------------------------------------------------------
    // CUSTOM REUSABLE COMPONENTS
    // ------------------------------------------------------------------
    component CustomButton: Button {
        id: btn
        property color bgNormal: "#14161F"
        property color bgHover: "#1E2230"
        property color borderNormal: "#2A2E3D"
        property color borderHover: window.cAccent
        property color txtColor: window.cText

        implicitHeight: 34

        contentItem: Text {
            text: btn.text
            font.pixelSize: 11
            font.bold: true
            font.capitalization: Font.AllUppercase
            color: btn.txtColor
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }

        background: Rectangle {
            color: btn.pressed ? "#0A0B10" : (btn.hovered ? btn.bgHover : btn.bgNormal)
            border.color: btn.hovered ? btn.borderHover : btn.borderNormal
            border.width: 1
            radius: 4
        }
    }

    component CustomComboBox: ComboBox {
        id: combo
        implicitHeight: 34

        delegate: ItemDelegate {
            width: combo.width
            implicitHeight: 30
            contentItem: Text {
                text: modelData
                color: highlighted ? window.cAccent : window.cText
                font.pixelSize: 11
                verticalAlignment: Text.AlignVCenter
                leftPadding: 8
            }
            background: Rectangle {
                color: highlighted ? "#181B26" : window.cPanel
            }
        }

        contentItem: Text {
            leftPadding: 10
            text: combo.displayText
            font.pixelSize: 11
            color: window.cText
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }

        background: Rectangle {
            color: "#08090D"
            border.color: combo.hovered ? window.cAccent : window.cBorder
            border.width: 1
            radius: 4
        }

        popup: Popup {
            y: combo.height + 2
            width: combo.width
            implicitHeight: Math.min(contentItem.implicitHeight + 4, 180)
            padding: 2
            contentItem: ListView {
                clip: true
                model: combo.popup.visible ? combo.delegateModel : null
                currentIndex: combo.highlightedIndex
            }
            background: Rectangle {
                color: window.cPanel
                border.color: window.cBorder
                radius: 4
            }
        }
    }

    // ------------------------------------------------------------------
    // LAYOUT STRUCTURE
    // ------------------------------------------------------------------
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 10

        // 1. TOP HEADER STRIP
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 46
            color: window.cPanel
            border.color: window.cBorder
            radius: 4

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 16

                Rectangle {
                    width: 8
                    height: 8
                    radius: 4
                    color: window.statusColor(window.currentStatus)
                }

                Text {
                    text: window.currentStatus
                    font.pixelSize: 13
                    font.bold: true
                    font.letterSpacing: 1.5
                    color: window.cText
                }

                Item { Layout.fillWidth: true }

                Text {
                    text: "MIC LEVEL"
                    font.pixelSize: 9
                    font.bold: true
                    color: window.cTextMuted
                }

                Rectangle {
                    Layout.preferredWidth: 140
                    implicitHeight: 8
                    color: "#000000"
                    border.color: window.cBorder
                    border.width: 1
                    radius: 2

                    Rectangle {
                        width: parent.width * (window.audioLevel / 100.0)
                        height: parent.height
                        color: window.cAccent
                    }
                }
            }
        }

        // 2. MAIN TWO-COLUMN DASHBOARD
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 10

            // LEFT COLUMN: Fixed width lock
            ColumnLayout {
                Layout.preferredWidth: 280
                Layout.maximumWidth: 280
                Layout.fillWidth: false
                Layout.fillHeight: true
                spacing: 10

                // AUDIO ROUTING PANEL
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 140
                    color: window.cPanel
                    border.color: window.cBorder
                    radius: 4

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 4

                        Text {
                            text: "// AUDIO ROUTING"
                            font.pixelSize: 10
                            font.bold: true
                            color: window.cAccent
                        }

                        Text { text: "Input Microphone"; font.pixelSize: 10; color: window.cTextMuted }
                        CustomComboBox {
                            Layout.fillWidth: true
                            model: backend.inputDevices
                            currentIndex: backend.defaultInputDeviceIndex
                            onActivated: backend.setInputDevice(index)
                        }

                        Text { text: "Virtual Cable Output"; font.pixelSize: 10; color: window.cTextMuted }
                        CustomComboBox {
                            Layout.fillWidth: true
                            model: backend.outputDevices
                            currentIndex: backend.defaultVirtualCableIndex
                            onActivated: backend.setOutputDevice(index)
                        }
                    }
                }

                // AI PERSONA PANEL
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: window.cPanel
                    border.color: window.cBorder
                    radius: 4

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 10

                        Text {
                            text: "// AI PERSONA ENGINE"
                            font.pixelSize: 10
                            font.bold: true
                            color: window.cAccent
                        }

                        CheckBox {
                            id: personaCheck
                            text: "Enable Persona AI"
                            checked: backend.llmEnabled
                            font.pixelSize: 11
                            font.bold: true
                            onToggled: backend.setLlmEnabled(checked)

                            indicator: Rectangle {
                                implicitWidth: 16
                                implicitHeight: 16
                                x: personaCheck.leftPadding
                                y: parent.height / 2 - height / 2
                                radius: 3
                                color: "#08090D"
                                border.color: personaCheck.checked ? window.cAccent : window.cBorder

                                Rectangle {
                                    width: 8
                                    height: 8
                                    anchors.centerIn: parent
                                    color: window.cAccent
                                    visible: personaCheck.checked
                                    radius: 1
                                }
                            }

                            contentItem: Text {
                                text: personaCheck.text
                                font: personaCheck.font
                                color: window.cText
                                verticalAlignment: Text.AlignVCenter
                                leftPadding: personaCheck.indicator.width + 8
                            }
                        }

                        Text { text: "Active Persona Profile"; font.pixelSize: 10; color: window.cTextMuted }
                        CustomComboBox {
                            Layout.fillWidth: true
                            model: backend.personas
                            currentIndex: backend.personas.indexOf(backend.currentPersona)
                            onActivated: backend.setPersona(backend.personas[index])
                        }

                        Item { Layout.fillHeight: true }
                    }
                }
            }

            // RIGHT COLUMN: Soundboard (Fills all remaining horizontal space)
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: window.cPanel
                border.color: window.cBorder
                radius: 4

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 8

                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: "// SOUNDBOARD QUEUE"
                            font.pixelSize: 10
                            font.bold: true
                            color: window.cAccent
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: "TRIGGER: /name"
                            font.pixelSize: 9
                            color: window.cTextMuted
                        }
                    }

                    // Soundboard List View
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        color: "#050508"
                        border.color: window.cBorder
                        radius: 2

                        ListView {
                            id: sbListView
                            anchors.fill: parent
                            anchors.margins: 4
                            clip: true
                            model: backend.soundboardItems
                            delegate: Rectangle {
                                width: sbListView.width
                                height: 32
                                color: ListView.isCurrentItem ? "#141A24" : "transparent"
                                border.color: ListView.isCurrentItem ? window.cAccent : "transparent"
                                border.width: 1

                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    anchors.left: parent.left
                                    anchors.leftMargin: 8
                                    text: modelData
                                    color: window.cText
                                    font.pixelSize: 11
                                    font.family: "Consolas"
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    onClicked: sbListView.currentIndex = index
                                }
                            }
                        }
                    }

                    // Soundboard Action Buttons
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        CustomButton {
                            text: "Play"
                            Layout.fillWidth: true
                            borderHover: window.cAccent
                            txtColor: window.cAccent
                            onClicked: backend.playSoundboardIndex(sbListView.currentIndex)
                        }

                        CustomButton {
                            text: window.isPausedState ? "Resume" : "Pause"
                            Layout.fillWidth: true
                            onClicked: window.isPausedState = backend.togglePause()
                        }

                        CustomButton {
                            text: "Add Sound"
                            Layout.fillWidth: true
                            onClicked: soundFileDialog.open()
                        }

                        CustomButton {
                            text: "Delete"
                            Layout.fillWidth: true
                            borderHover: window.cDanger
                            txtColor: window.cDanger
                            onClicked: backend.removeSoundboardIndex(sbListView.currentIndex)
                        }
                    }
                }
            }
        }

        // 3. BOTTOM FOOTER BAR
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 40
            color: window.cPanel
            border.color: window.cBorder
            radius: 4

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 12

                Text {
                    text: "LATENCY: STT " + window.sttMs.toFixed(0) + "ms | TTS " + window.ttsMs.toFixed(0) + "ms | TOTAL " + window.totalMs.toFixed(0) + "ms"
                    font.pixelSize: 10
                    font.family: "Consolas"
                    color: window.cTextMuted
                }

                Item { Layout.fillWidth: true }

                CustomButton {
                    text: "Cancel / Silence"
                    implicitWidth: 130
                    onClicked: backend.cancel()
                }

                CustomButton {
                    text: "Exit App"
                    implicitWidth: 90
                    bgNormal: "#20080E"
                    borderNormal: "#4A101C"
                    borderHover: window.cDanger
                    txtColor: window.cDanger
                    onClicked: backend.closeApp()
                }
            }
        }
    }

    // DIALOGS
    FileDialog {
        id: soundFileDialog
        title: "Select Sound File"
        nameFilters: ["WAV Audio (*.wav)"]
        onAccepted: triggerDialog.open()
    }

    Dialog {
        id: triggerDialog
        title: "Add Soundboard Trigger"
        anchors.centerIn: parent
        modal: true
        standardButtons: Dialog.Ok | Dialog.Cancel

        background: Rectangle {
            color: window.cPanel
            border.color: window.cBorder
            radius: 4
        }

        ColumnLayout {
            spacing: 8
            Text {
                text: "Trigger command word:"
                color: window.cText
                font.pixelSize: 11
            }
            TextField {
                id: triggerInput
                placeholderText: "e.g., 1"
                Layout.fillWidth: true
                color: window.cText
                placeholderTextColor: window.cTextMuted
                background: Rectangle {
                    color: "#000000"
                    border.color: window.cBorder
                    radius: 2
                }
            }
        }

        onAccepted: {
            backend.addSoundboardEntry(soundFileDialog.selectedFile.toString(), triggerInput.text)
            triggerInput.text = ""
        }
        onRejected: triggerInput.text = ""
    }

    Dialog {
        id: warningDialog
        property string dialogTitle: ""
        property string dialogMessage: ""
        title: dialogTitle
        anchors.centerIn: parent
        modal: true
        standardButtons: Dialog.Ok

        background: Rectangle {
            color: window.cPanel
            border.color: window.cBorder
            radius: 4
        }

        Text {
            text: warningDialog.dialogMessage
            color: window.cText
            font.pixelSize: 11
            wrapMode: Text.WordWrap
            width: 320
        }
    }
}