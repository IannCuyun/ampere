import QtQuick
import QtQuick.Controls.Basic
import "."

// One editable tag with its fault stated beside it and completion drawn from
// the library itself (Iann, 2026-08-21). Completion never invents a spelling:
// candidates are names his catalog already uses.
Item {
    id: tf
    property string label: ""
    property string field: ""
    property string value: ""
    property string issue: ""            // "" when the field is healthy
    readonly property bool faulted: issue !== ""
    property var suggestions: []
    property int highlighted: -1
    signal edited(string value)

    implicitHeight: 62 + (suggestOpen ? suggestList.height : 0)
    readonly property bool suggestOpen: input.activeFocus && suggestions.length > 0

    function refresh(text) {
        suggestions = (field === "" || text.length < 1)
            ? [] : backend.tagSuggestions(field, text)
        highlighted = -1
    }
    function accept(name) {
        input.text = name
        tf.value = name
        tf.edited(name)
        suggestions = []
    }

    Text {
        id: labelText
        anchors.left: parent.left
        anchors.top: parent.top
        text: tf.label
        color: tf.faulted ? Theme.error : Theme.washFaint
        font.family: Theme.displayFont
        font.pixelSize: Theme.washMicro
        font.letterSpacing: 2.2
    }
    Text {
        objectName: "tagFieldIssue"
        anchors.left: labelText.right
        anchors.leftMargin: 12
        anchors.baseline: labelText.baseline
        visible: tf.faulted
        text: tf.issue
        color: Theme.error
        font.family: Theme.displayFont
        font.pixelSize: Theme.washMicro
        font.letterSpacing: 2.2
    }

    TextField {
        id: input
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: labelText.bottom
        anchors.topMargin: 8
        height: 32
        leftPadding: 0; rightPadding: 0; topPadding: 0; bottomPadding: 6
        background: null
        text: tf.value
        color: Theme.washInk
        selectionColor: Qt.alpha(Theme.primary, 0.28)
        selectedTextColor: Theme.washInk
        placeholderText: tf.faulted ? "—" : ""
        placeholderTextColor: Qt.alpha(Theme.error, 0.7)
        font.family: Theme.font
        font.pixelSize: Theme.fsBody
        selectByMouse: true
        Accessible.name: tf.label + (tf.faulted ? ", " + tf.issue : "")
        onTextEdited: { tf.value = text; tf.edited(text); tf.refresh(text) }
        Keys.onDownPressed: if (tf.suggestOpen)
            tf.highlighted = Math.min(tf.highlighted + 1, tf.suggestions.length - 1)
        Keys.onUpPressed: if (tf.suggestOpen) tf.highlighted = Math.max(tf.highlighted - 1, -1)
        Keys.onReturnPressed: if (tf.highlighted >= 0) tf.accept(tf.suggestions[tf.highlighted])
        Keys.onEscapePressed: tf.suggestions = []
    }
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: input.bottom
        height: 1
        color: input.activeFocus ? Theme.primary
             : tf.faulted ? Qt.alpha(Theme.error, 0.55) : Theme.washHair
    }

    // completion plane — the ArchiveMenu recipe, same as every Ampere popover
    Rectangle {
        id: suggestList
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: input.bottom
        anchors.topMargin: 6
        z: 40
        visible: tf.suggestOpen
        height: visible ? column.height : 0
        color: Qt.alpha(Theme.bgLow, 0.98)
        border.color: Theme.washHair
        border.width: 1
        radius: 0

        Column {
            id: column
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: 1
            Repeater {
                model: tf.suggestions
                delegate: Item {
                    required property string modelData
                    required property int index
                    width: column.width
                    height: 38
                    Accessible.role: Accessible.Button
                    Accessible.name: "Use " + modelData
                    Accessible.onPressAction: tf.accept(modelData)
                    Rectangle {
                        anchors.fill: parent
                        color: (tf.highlighted === index || rowHover.hovered)
                               ? Qt.alpha(Theme.washInk, 0.065) : "transparent"
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 14
                        anchors.right: parent.right
                        anchors.rightMargin: 14
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData
                        color: Theme.washInk
                        font.family: Theme.font
                        font.pixelSize: Theme.fsSmall
                        elide: Text.ElideRight
                    }
                    HoverHandler { id: rowHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: tf.accept(modelData) }
                }
            }
        }
    }
}
