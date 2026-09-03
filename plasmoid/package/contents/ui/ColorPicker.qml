/*
 * VRGB - inline HSV colour picker (saturation/value square + hue strip).
 *
 * Emits picked() continuously while dragging; the caller is expected to
 * throttle hardware writes rather than firing one per pixel.
 *
 * SPDX-License-Identifier: MIT
 */

import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: picker

    signal picked(color c)

    // Hue is kept separately from the emitted colour: greys report hsvHue == -1,
    // so round-tripping through a colour would make the hue marker jump to red.
    property real hue: 0
    property real sat: 1
    property real val: 1

    readonly property color currentColor: Qt.hsva(hue, sat, val, 1)

    // Seed the picker from outside without emitting picked().
    function setColor(c) {
        if (Qt.colorEqual(c, picker.currentColor)) {
            return;
        }
        hue = (c.hsvHue < 0) ? hue : c.hsvHue;
        sat = c.hsvSaturation;
        val = c.hsvValue;
    }

    spacing: Kirigami.Units.smallSpacing

    Rectangle {
        id: svSquare

        Layout.fillWidth: true
        Layout.preferredHeight: Kirigami.Units.gridUnit * 7

        radius: 3
        border.width: 1
        border.color: Qt.rgba(0, 0, 0, 0.25)

        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "#ffffff" }
            GradientStop { position: 1.0; color: Qt.hsva(picker.hue, 1, 1, 1) }
        }

        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 1.0; color: "#000000" }
            }
        }

        Rectangle {
            width: Math.round(Kirigami.Units.gridUnit * 0.8)
            height: width
            radius: width / 2
            color: "transparent"
            border.width: 2
            // Dark ring on pale areas, light ring everywhere else.
            border.color: (picker.val > 0.55 && picker.sat < 0.55) ? "#000000" : "#ffffff"
            x: picker.sat * svSquare.width - width / 2
            y: (1 - picker.val) * svSquare.height - height / 2
        }

        MouseArea {
            anchors.fill: parent

            function pick(mx, my) {
                picker.sat = Math.max(0, Math.min(1, mx / width));
                picker.val = 1 - Math.max(0, Math.min(1, my / height));
                picker.picked(picker.currentColor);
            }

            onPressed: mouse => pick(mouse.x, mouse.y)
            onPositionChanged: mouse => {
                if (pressed) {
                    pick(mouse.x, mouse.y);
                }
            }
        }
    }

    Rectangle {
        id: hueStrip

        Layout.fillWidth: true
        Layout.preferredHeight: Kirigami.Units.gridUnit

        radius: 3
        border.width: 1
        border.color: Qt.rgba(0, 0, 0, 0.25)

        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.000; color: "#ff0000" }
            GradientStop { position: 0.167; color: "#ffff00" }
            GradientStop { position: 0.333; color: "#00ff00" }
            GradientStop { position: 0.500; color: "#00ffff" }
            GradientStop { position: 0.667; color: "#0000ff" }
            GradientStop { position: 0.833; color: "#ff00ff" }
            GradientStop { position: 1.000; color: "#ff0000" }
        }

        Rectangle {
            width: 3
            height: parent.height + 4
            y: -2
            x: picker.hue * hueStrip.width - width / 2
            color: "#ffffff"
            border.width: 1
            border.color: "#000000"
        }

        MouseArea {
            anchors.fill: parent

            function pick(mx) {
                // Clamp below 1.0: a hue of exactly 1.0 wraps back to 0.
                picker.hue = Math.max(0, Math.min(0.9999, mx / width));
                picker.picked(picker.currentColor);
            }

            onPressed: mouse => pick(mouse.x)
            onPositionChanged: mouse => {
                if (pressed) {
                    pick(mouse.x);
                }
            }
        }
    }
}
