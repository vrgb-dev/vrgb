/*
 * VRGB - Plasma 6 applet for ASUS Vivobook HID LampArray keyboards.
 *
 * The swatch grid is backed by vrgb profiles rather than hardcoded colours:
 * one click loads a profile, a double click opens it in the editor, and "+"
 * creates a new one. State is read straight out of ~/.config/vrgb/config.json;
 * every write goes through the `vrgb` CLI so the config file has a single
 * owner and the applet never touches hidraw itself.
 *
 * Two different brightnesses are in play, and they multiply:
 *   - asus::kbd_backlight (0..3), driven by the Fn keys and Plasma. The slider
 *     on the grid page is bound to it, so the widget and the Fn keys agree.
 *   - vrgb's own LampArray intensity (0..100), stored per profile. That one
 *     lives in the editor, since it is part of what a profile *is*.
 *
 * SPDX-License-Identifier: MIT
 */

import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.plasma5support as P5Support
import org.kde.plasma.private.brightnesscontrolplugin
import org.kde.kirigami as Kirigami

PlasmoidItem {
    id: root

    // Resolved at startup; install.sh puts vrgb in /usr/local/bin, which is not
    // always on plasmashell's PATH.
    property string vrgbBin: "vrgb"
    property color currentColor: "#00aa55"
    property int currentPercent: 100
    property string errorText: ""
    // Suppresses hardware writes while the UI is being seeded from config.json.
    property bool loading: true

    // [{ name, color, percent }], sorted by name.
    property var profiles: []

    // "grid" or "editor"
    property string page: "grid"
    property string editorName: ""
    property bool editorNew: false
    property color editorColor: "#ffffff"
    property int editorPercent: 100
    // Shown in the header instead of the hex while a swatch is hovered.
    property string hoveredName: ""

    // Brightness comes from Plasma so the Fn keys and the widget stay in step.
    readonly property int backlight: kbdBacklight.brightness
    readonly property int backlightMax: Math.max(1, kbdBacklight.brightnessMax)
    readonly property real litFraction: backlight / backlightMax

    readonly property var defaultPalette: [
        { name: "Red", color: "ff0000" }, { name: "Orange", color: "ff7f00" },
        { name: "Amber", color: "ffd400" }, { name: "Lime", color: "7fff00" },
        { name: "Green", color: "00ff5e" }, { name: "Cyan", color: "00e5ff" },
        { name: "Azure", color: "0080ff" }, { name: "Blue", color: "2b3cff" },
        { name: "Violet", color: "8b00ff" }, { name: "Magenta", color: "ff00c8" },
        { name: "Rose", color: "ff4d6d" }, { name: "White", color: "ffffff" }
    ]

    readonly property string hexColor: toHex(currentColor)

    // What the keys should actually look like: colour x vrgb intensity x backlight.
    readonly property color litColor: {
        var f = litFraction * currentPercent / 100;
        return Qt.rgba(currentColor.r * f, currentColor.g * f, currentColor.b * f, 1);
    }

    readonly property string resolveCmd: "command -v vrgb 2>/dev/null || echo /usr/local/bin/vrgb"
    readonly property string readCfgCmd: "cat \"$HOME/.config/vrgb/config.json\" 2>/dev/null"

    Plasmoid.icon: "input-keyboard"
    toolTipMainText: i18n("Keyboard Lighting")
    toolTipSubText: loading ? i18n("Reading configuration…")
                            : i18n("#%1 at %2%", hexColor.toUpperCase(),
                                   Math.round(litFraction * 100))

    preferredRepresentation: compactRepresentation

    function toHex(c) {
        function ch(v) {
            return Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16).padStart(2, "0");
        }
        return ch(c.r) + ch(c.g) + ch(c.b);
    }

    // Profile names reach a shell, so quote them properly rather than trusting
    // the field validator alone.
    function shellQuote(s) {
        return "'" + String(s).replace(/'/g, "'\\''") + "'";
    }

    function nameIsValid(name) {
        var n = String(name).trim();
        return n.length > 0 && n.length <= 32 && /^[A-Za-z0-9 _-]+$/.test(n);
    }

    function profileByName(name) {
        for (var i = 0; i < profiles.length; ++i) {
            if (profiles[i].name === name) {
                return profiles[i];
            }
        }
        return null;
    }

    // --- hardware / CLI ---------------------------------------------------

    // Live preview while the editor is open; snapshotted by "Save".
    function applyPreview() {
        if (loading) {
            return;
        }
        previewTimer.stop();
        executable.run(vrgbBin + " set " + toHex(editorColor) + " " + editorPercent);
    }

    function schedulePreview() {
        if (!loading) {
            previewTimer.restart();
        }
    }

    function loadProfile(name) {
        executable.run(vrgbBin + " profile load " + shellQuote(name));
    }

    function saveProfile(name) {
        // `profile save` snapshots the current state, so set it first.
        executable.run(vrgbBin + " set " + toHex(editorColor) + " " + editorPercent
                       + " && " + vrgbBin + " profile save " + shellQuote(name));
    }

    function deleteProfile(name) {
        executable.run(vrgbBin + " profile delete " + shellQuote(name));
    }

    function seedDefaults() {
        var parts = [];
        for (var i = 0; i < defaultPalette.length; ++i) {
            var p = defaultPalette[i];
            parts.push(vrgbBin + " set " + p.color + " 100");
            parts.push(vrgbBin + " profile save " + shellQuote(p.name));
        }
        // Put the keys back where they were rather than leaving them on the
        // last seeded colour.
        parts.push(vrgbBin + " set " + hexColor + " " + currentPercent);
        executable.run(parts.join(" && "));
    }

    // --- editor -----------------------------------------------------------

    function openEditor(name) {
        var p = profileByName(name);
        if (!p) {
            return;
        }
        editorNew = false;
        editorName = p.name;
        editorColor = "#" + p.color;
        editorPercent = p.percent;
        page = "editor";
    }

    function openNewEditor() {
        editorNew = true;
        editorName = "";
        editorColor = currentColor;
        editorPercent = currentPercent;
        page = "editor";
    }

    function closeEditor() {
        previewTimer.stop();
        page = "grid";
    }

    // --- config -----------------------------------------------------------

    function loadConfig(text) {
        var cfg = null;
        if (text.length > 0) {
            try {
                cfg = JSON.parse(text);
            } catch (e) {
                cfg = null;
            }
        }

        var list = [];
        if (cfg) {
            if (typeof cfg.color === "string" && /^[0-9a-fA-F]{6}$/.test(cfg.color)) {
                currentColor = "#" + cfg.color;
            }
            var pc = parseInt(cfg.percent, 10);
            if (!isNaN(pc)) {
                currentPercent = Math.max(0, Math.min(100, pc));
            }
            if (cfg.profiles && typeof cfg.profiles === "object") {
                for (var name in cfg.profiles) {
                    var p = cfg.profiles[name];
                    if (!p || !/^[0-9a-fA-F]{6}$/.test(String(p.color))) {
                        continue;
                    }
                    var pp = parseInt(p.percent, 10);
                    list.push({
                        name: name,
                        color: String(p.color),
                        percent: isNaN(pp) ? 100 : Math.max(0, Math.min(100, pp))
                    });
                }
            }
        }
        list.sort(function (a, b) { return a.name.localeCompare(b.name); });
        profiles = list;
        loading = false;

        // First run: turn the old hardcoded palette into real profiles so the
        // grid is not empty. Guarded by applet config, otherwise deleting every
        // profile would resurrect them on the next start.
        if (list.length === 0 && !Plasmoid.configuration.seededDefaults) {
            Plasmoid.configuration.seededDefaults = true;
            seedDefaults();
        }
    }

    function handleResult(source, code, out, err) {
        if (source === resolveCmd) {
            if (out.length > 0) {
                vrgbBin = out.split("\n")[0];
            }
            executable.run(readCfgCmd);
            return;
        }
        if (source === readCfgCmd) {
            loadConfig(out);
            return;
        }
        // Any other command was a write.
        if (code === 0) {
            errorText = "";
            executable.run(readCfgCmd);
        } else {
            errorText = err.length > 0 ? err : i18n("vrgb exited with code %1", code);
        }
    }

    Timer {
        id: previewTimer
        // vrgb returns in ~25 ms; 60 ms keeps a drag smooth without queueing up
        // one process per mouse move.
        interval: 60
        onTriggered: root.applyPreview()
    }

    Timer {
        id: clickTimer
        property string pendingName: ""
        // Must be at least the system double-click interval, or the single-click
        // load would fire before the second click is recognised.
        interval: (Qt.styleHints && Qt.styleHints.mouseDoubleClickInterval)
                  ? Qt.styleHints.mouseDoubleClickInterval : 400
        onTriggered: {
            if (pendingName.length > 0) {
                root.loadProfile(pendingName);
                pendingName = "";
            }
        }
    }

    KeyboardBrightnessControl {
        id: kbdBacklight
        // The popup shows the level itself; a second OSD on every drag step
        // would just be noise.
        isSilent: true
    }

    P5Support.DataSource {
        id: executable

        engine: "executable"
        connectedSources: []

        onNewData: (source, data) => {
            var code = data["exit code"];
            var out = (data["stdout"] || "").trim();
            var err = (data["stderr"] || "").trim();
            disconnectSource(source);
            root.handleResult(source, code, out, err);
        }

        function run(cmd) {
            // The engine keys sources by command string, so re-running an
            // identical command needs an explicit disconnect first.
            if (connectedSources.indexOf(cmd) !== -1) {
                disconnectSource(cmd);
            }
            connectSource(cmd);
        }
    }

    Component.onCompleted: executable.run(resolveCmd)

    compactRepresentation: MouseArea {
        onClicked: root.expanded = !root.expanded

        Kirigami.Icon {
            anchors.centerIn: parent
            width: Math.min(parent.width, parent.height)
            height: width
            // The symbolic variant keeps its key detail when masked; plain
            // input-keyboard flattens to a solid block.
            source: "input-keyboard-symbolic"
            isMask: true
            color: root.backlight > 0 ? root.currentColor : Kirigami.Theme.disabledTextColor
        }
    }

    fullRepresentation: Item {
        id: fullRep

        readonly property int pad: Kirigami.Units.largeSpacing
        // Height follows the content rather than a fixed guess, so the grid
        // page is not padded out to the (much taller) editor page. Anchoring
        // the content left/right/top only -- never filling -- keeps
        // content.implicitHeight independent of this item's own height, so the
        // binding cannot become circular.
        readonly property int contentHeight: content.implicitHeight + 2 * pad

        Layout.minimumWidth: Kirigami.Units.gridUnit * 15
        Layout.preferredWidth: Kirigami.Units.gridUnit * 17
        Layout.minimumHeight: contentHeight
        Layout.preferredHeight: contentHeight
        Layout.maximumHeight: contentHeight

        ColumnLayout {
            id: content

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: fullRep.pad
            spacing: Kirigami.Units.smallSpacing

            // --- header ---------------------------------------------------
            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.largeSpacing

                PlasmaComponents.ToolButton {
                    visible: root.page === "editor"
                    icon.name: "draw-arrow-back"
                    display: PlasmaComponents.ToolButton.IconOnly
                    text: i18n("Back")
                    onClicked: root.closeEditor()
                }

                Rectangle {
                    visible: root.page === "grid"
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 2.5
                    Layout.preferredHeight: Kirigami.Units.gridUnit * 2.5
                    radius: 4
                    color: root.litColor
                    border.width: 1
                    border.color: Qt.rgba(0, 0, 0, 0.3)
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0

                    Kirigami.Heading {
                        Layout.fillWidth: true
                        level: 4
                        elide: Text.ElideRight
                        text: root.page === "editor"
                              ? (root.editorNew ? i18n("New profile") : root.editorName)
                              : i18n("Keyboard Lighting")
                    }

                    PlasmaComponents.Label {
                        Layout.fillWidth: true
                        visible: root.page === "grid"
                        elide: Text.ElideRight
                        font.family: root.hoveredName.length > 0
                                     ? Kirigami.Theme.defaultFont.family : "monospace"
                        opacity: 0.75
                        text: root.hoveredName.length > 0
                              ? root.hoveredName
                              : "#" + root.hexColor.toUpperCase()
                    }
                }
            }

            Kirigami.Separator {
                Layout.fillWidth: true
                Layout.topMargin: Kirigami.Units.smallSpacing
                Layout.bottomMargin: Kirigami.Units.smallSpacing
            }

            // --- pages ----------------------------------------------------
            StackLayout {
                Layout.fillWidth: true
                // A StackLayout's own implicit height is the tallest page, which
                // is what left dead space under the grid. Report just the page
                // actually on screen.
                Layout.preferredHeight: root.page === "editor" ? editorPage.implicitHeight
                                                               : gridPage.implicitHeight
                currentIndex: root.page === "editor" ? 1 : 0

                // page 0: profile grid
                ColumnLayout {
                    id: gridPage

                    spacing: Kirigami.Units.smallSpacing

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 6
                        columnSpacing: Kirigami.Units.smallSpacing
                        rowSpacing: Kirigami.Units.smallSpacing

                        Repeater {
                            model: root.profiles

                            delegate: Rectangle {
                                id: swatch

                                required property var modelData
                                // Marks whichever profile matches the live colour.
                                // Colours need colorEqual; === compares wrappers.
                                readonly property bool isCurrent:
                                    Qt.colorEqual(root.currentColor, "#" + modelData.color)

                                Layout.fillWidth: true
                                Layout.preferredHeight: Kirigami.Units.gridUnit * 1.3
                                radius: 3
                                color: "#" + modelData.color
                                border.width: isCurrent ? 2 : 1
                                border.color: isCurrent ? Kirigami.Theme.highlightColor
                                                        : Qt.rgba(0, 0, 0, 0.3)

                                MouseArea {
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    onEntered: root.hoveredName = swatch.modelData.name
                                    onExited: {
                                        if (root.hoveredName === swatch.modelData.name) {
                                            root.hoveredName = "";
                                        }
                                    }
                                    // A double click also emits two clicks, so
                                    // defer the load and cancel it if a second
                                    // click arrives.
                                    onClicked: {
                                        clickTimer.pendingName = swatch.modelData.name;
                                        clickTimer.restart();
                                    }
                                    onDoubleClicked: {
                                        clickTimer.stop();
                                        clickTimer.pendingName = "";
                                        root.openEditor(swatch.modelData.name);
                                    }
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: Kirigami.Units.gridUnit * 1.3
                            radius: 3
                            color: "transparent"
                            border.width: 1
                            border.color: Kirigami.Theme.disabledTextColor

                            Kirigami.Icon {
                                anchors.centerIn: parent
                                width: Kirigami.Units.iconSizes.small
                                height: width
                                source: "list-add"
                                isMask: true
                                color: Kirigami.Theme.textColor
                            }

                            MouseArea {
                                anchors.fill: parent
                                hoverEnabled: true
                                onEntered: root.hoveredName = i18n("Add profile")
                                onExited: root.hoveredName = ""
                                onClicked: root.openNewEditor()
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: Kirigami.Units.smallSpacing

                        PlasmaComponents.Label {
                            text: i18n("Brightness")
                        }

                        Item {
                            Layout.fillWidth: true
                        }

                        PlasmaComponents.Label {
                            opacity: 0.75
                            text: root.backlight + " / " + root.backlightMax
                        }
                    }

                    PlasmaComponents.Slider {
                        id: backlightSlider

                        Layout.fillWidth: true
                        enabled: kbdBacklight.isBrightnessAvailable
                        from: 0
                        to: root.backlightMax
                        stepSize: 1
                        snapMode: PlasmaComponents.Slider.SnapAlways

                        // Straight to Plasma: this is a D-Bus property rather
                        // than a subprocess, so it needs no throttling.
                        onMoved: kbdBacklight.brightness = Math.round(value)
                    }

                    // Follows Plasma -- Fn keys, the brightness applet, anything
                    // else -- whenever the user is not dragging. Depending on
                    // backlightMax as well as backlight matters: PowerDevil
                    // publishes the maximum after the current value on startup,
                    // and without that dependency the slider can stay clamped
                    // against a stale range.
                    Binding {
                        target: backlightSlider
                        property: "value"
                        value: Math.min(root.backlight, root.backlightMax)
                        when: !backlightSlider.pressed
                        restoreMode: Binding.RestoreNone
                    }
                }

                // page 1: profile editor
                ColumnLayout {
                    id: editorPage

                    spacing: Kirigami.Units.smallSpacing

                    PlasmaComponents.TextField {
                        id: nameField

                        Layout.fillWidth: true
                        visible: root.editorNew
                        placeholderText: i18n("Profile name")
                        maximumLength: 32
                        // Seeded by onPageChanged, kept one-way so typing does
                        // not fight a binding.
                        onTextChanged: root.editorName = text
                    }

                    ColorPicker {
                        id: picker

                        Layout.fillWidth: true

                        onPicked: c => {
                            root.editorColor = c;
                            root.schedulePreview();
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: Kirigami.Units.smallSpacing

                        PlasmaComponents.Label {
                            text: i18n("Brightness")
                        }

                        Item {
                            Layout.fillWidth: true
                        }

                        PlasmaComponents.Label {
                            opacity: 0.75
                            text: root.editorPercent + "%"
                        }
                    }

                    PlasmaComponents.Slider {
                        id: percentSlider

                        Layout.fillWidth: true
                        from: 0
                        to: 100
                        stepSize: 1

                        onMoved: {
                            root.editorPercent = Math.round(value);
                            root.schedulePreview();
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: Kirigami.Units.smallSpacing
                        spacing: Kirigami.Units.smallSpacing

                        PlasmaComponents.Button {
                            visible: !root.editorNew
                            icon.name: "edit-delete"
                            text: i18n("Delete")
                            onClicked: {
                                root.deleteProfile(root.editorName);
                                root.closeEditor();
                            }
                        }

                        Item {
                            Layout.fillWidth: true
                        }

                        PlasmaComponents.Button {
                            icon.name: "document-save"
                            text: i18n("Save")
                            enabled: root.nameIsValid(root.editorName)
                            onClicked: {
                                root.saveProfile(root.editorName.trim());
                                root.closeEditor();
                            }
                        }
                    }
                }
            }

            Kirigami.InlineMessage {
                Layout.fillWidth: true
                type: Kirigami.MessageType.Error
                text: root.errorText
                visible: root.errorText.length > 0
            }
        }

        // Seed the editor widgets whenever a profile is opened. They live in a
        // StackLayout page that is built once, so this cannot be a
        // Component.onCompleted.
        Connections {
            target: root

            function onPageChanged() {
                if (root.page === "editor") {
                    picker.setColor(root.editorColor);
                    percentSlider.value = root.editorPercent;
                    nameField.text = root.editorName;
                }
            }
        }
    }
}
