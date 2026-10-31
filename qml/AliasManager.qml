import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

// Artist aliases — Library Doctor (Iann's direction 2026-08-21, SPEC
// UNDESIGNED #17). Pick an artist, search his own artists, attach the alias.
// SUGGESTIONS are proposals he confirms; nothing here merges on its own, which
// is what keeps this inside SPEC's no-fuzzy-aliases rule. Every alias is
// reversible and no tag is ever rewritten.
Item {
    id: mgr
    property string chosen: ""
    readonly property var aliasMap: backend.artistAliases || ({})
    readonly property var suggestions: {
        aliasMap;   // settled aliases are no longer candidates
        return chosen !== "" ? backend.aliasSuggestions(chosen) : []
    }
    property string search: ""

    implicitHeight: body.implicitHeight

    property int refresh: 0
    readonly property var allArtists: {
        refresh;   // re-read after an alias rebuilds the artist projection
        var rows = backend.libraryArtists() || []
        var names = []
        for (var i = 0; i < rows.length; ++i)
            names.push(rows[i].name !== undefined ? rows[i].name : rows[i])
        return names
    }
    readonly property var matches: {
        if (chosen === "" || search.length < 1) return []
        var needle = search.toLowerCase(), out = []
        for (var i = 0; i < allArtists.length && out.length < 12; ++i) {
            var name = String(allArtists[i] || "")
            if (name.toLowerCase().indexOf(needle) !== -1 && name !== chosen)
                out.push(name)
        }
        return out
    }
    readonly property var attached: {
        var out = []
        for (var alias in aliasMap)
            if (aliasMap[alias] === chosen) out.push(alias)
        return out.sort()
    }

    function attach(name) {
        if (!name || !chosen) return
        backend.setArtistAlias(name, chosen)
        search = ""
        refresh += 1
    }

    ColumnLayout {
        id: body
        width: parent.width
        spacing: Theme.spaceLg

        // Doctor states every empty room; this one says what the tool is FOR
        // rather than leaving a bare field floating on the wash.
        Column {
            Layout.fillWidth: true
            Layout.topMargin: Theme.spaceLg
            visible: mgr.chosen === ""
            spacing: 10
            Text {
                text: "NOTHING COMBINED YET"
                color: Theme.washFaint
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.letterSpacing: 2.8
            }
            Text {
                width: parent.width
                text: "Two names, one artist."
                color: Theme.washInk
                font.family: Theme.font
                font.pixelSize: 30
                font.weight: Font.Light
                wrapMode: Text.Wrap
            }
            Text {
                width: parent.width
                text: "Some records file themselves under a second billing — a "
                      + "release series, a backing band, a stage name. Choose the "
                      + "artist they belong to and combine them. Ampere suggests "
                      + "the ones it can see; you decide every one."
                color: Theme.washMuted
                font.family: Theme.font
                font.pixelSize: Theme.fsSmall
                font.weight: Font.Light
                wrapMode: Text.Wrap
            }
        }

        // ---- 1. which artist is the real identity ----
        Column {
            Layout.fillWidth: true
            spacing: 8
            Text {
                text: "THE ARTIST"
                color: Theme.washFaint
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.letterSpacing: 2.8
            }
            Text {
                width: parent.width
                text: mgr.chosen !== "" ? mgr.chosen : "Choose an artist below"
                color: mgr.chosen !== "" ? Theme.washInk : Theme.washFaint
                font.family: Theme.displayFont
                font.pixelSize: 32
                elide: Text.ElideRight
            }
            Item {
                width: parent.width
                height: 34
                TextField {
                    id: field
                    objectName: "aliasSearchField"
                    anchors.fill: parent
                    leftPadding: 0; rightPadding: 0; topPadding: 0; bottomPadding: 4
                    background: null
                    color: Theme.washInk
                    placeholderText: mgr.chosen === "" ? "SEARCH YOUR ARTISTS"
                                                       : "SEARCH AN ARTIST TO COMBINE"
                    placeholderTextColor: Theme.washFaint
                    selectionColor: Qt.alpha(Theme.primary, 0.28)
                    selectedTextColor: Theme.washInk
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.washMicro
                    font.letterSpacing: 1.8
                    selectByMouse: true
                    Accessible.name: placeholderText
                    onTextChanged: mgr.search = text
                    Keys.onReturnPressed: {
                        var first = mgr.matches.length ? mgr.matches[0] : ""
                        if (first) { mgr.pick(first); text = "" }
                    }
                    Keys.onEscapePressed: text = ""
                }
                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 1
                    color: field.activeFocus ? Theme.primary : Theme.washHair
                }
            }
        }

        // ---- 2. results of that search ----
        Column {
            Layout.fillWidth: true
            visible: mgr.matches.length > 0
            spacing: 0
            Repeater {
                model: mgr.matches
                delegate: Item {
                    required property string modelData
                    width: parent.width
                    height: 44
                    Accessible.role: Accessible.Button
                    Accessible.name: mgr.chosen === ""
                        ? "Choose " + modelData
                        : "Make " + modelData + " an alias of " + mgr.chosen
                    Accessible.onPressAction: mgr.pick(modelData)
                    Rectangle {
                        anchors.fill: parent
                        color: hover.hovered ? Qt.alpha(Theme.washInk, 0.065) : "transparent"
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData
                        color: Theme.washInk
                        font.family: Theme.font
                        font.pixelSize: Theme.fsBody
                        elide: Text.ElideRight
                    }
                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 1
                        color: Theme.washHair
                    }
                    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: mgr.pick(modelData) }
                }
            }
        }

        // ---- 3. suggestions: proposals, never merges ----
        Column {
            Layout.fillWidth: true
            visible: mgr.chosen !== "" && mgr.suggestions.length > 0
            spacing: 0
            Text {
                bottomPadding: 8
                text: "SUGGESTIONS"
                color: Theme.primary
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.letterSpacing: 2.8
            }
            Repeater {
                model: mgr.suggestions
                delegate: Item {
                    required property var modelData
                    width: parent.width
                    height: 54
                    Accessible.role: Accessible.Button
                    Accessible.name: "Make " + modelData.name
                                     + " an alias of " + mgr.chosen
                                     + " — " + modelData.reason
                    Accessible.onPressAction: mgr.attach(modelData.name)
                    Rectangle {
                        anchors.fill: parent
                        color: sHover.hovered ? Qt.alpha(Theme.washInk, 0.065) : "transparent"
                    }
                    Column {
                        anchors.left: parent.left
                        anchors.right: addLink.left
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2
                        Text {
                            width: parent.width
                            text: modelData.name
                            color: Theme.washInk
                            font.family: Theme.font
                            font.pixelSize: Theme.fsBody
                            elide: Text.ElideRight
                        }
                        Text {
                            width: parent.width
                            text: modelData.reason
                            color: Theme.washFaint
                            font.family: Theme.font
                            font.pixelSize: Theme.fsSmall
                            elide: Text.ElideRight
                        }
                    }
                    WashLine {
                        id: addLink
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        label: "Combine"
                        primaryAction: true
                        onActivated: mgr.attach(modelData.name)
                    }
                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 1
                        color: Theme.washHair
                    }
                    HoverHandler { id: sHover }
                }
            }
        }

        // ---- 4. what is already combined, and how to undo it ----
        Column {
            Layout.fillWidth: true
            visible: mgr.attached.length > 0
            spacing: 0
            Text {
                bottomPadding: 8
                text: "COMBINED INTO THIS ARTIST"
                color: Theme.washFaint
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.letterSpacing: 2.8
            }
            Repeater {
                model: mgr.attached
                delegate: Item {
                    required property string modelData
                    width: parent.width
                    height: 44
                    Accessible.role: Accessible.Button
                    Accessible.name: "Separate " + modelData + " from " + mgr.chosen
                    Accessible.onPressAction: mgr.separate(modelData)
                    Text {
                        anchors.left: parent.left
                        anchors.right: undoLink.left
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData
                        color: Theme.washMuted
                        font.family: Theme.font
                        font.pixelSize: Theme.fsBody
                        elide: Text.ElideRight
                    }
                    WashLine {
                        id: undoLink
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        label: "Separate"
                        onActivated: mgr.separate(modelData)
                    }
                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 1
                        color: Theme.washHair
                    }
                }
            }
        }

        Text {
            Layout.fillWidth: true
            visible: mgr.chosen !== ""
            text: "Combining is reversible and never changes your tags — it only "
                  + "tells Ampere that two credits are one artist."
            color: Theme.washFaint
            font.family: Theme.font
            font.pixelSize: Theme.fsSmall
            wrapMode: Text.Wrap
        }
    }

    function firstMatch(text) {
        var needle = String(text || "").toLowerCase()
        if (!needle) return ""
        for (var i = 0; i < allArtists.length; ++i) {
            var name = String(allArtists[i] || "")
            if (name.toLowerCase().indexOf(needle) !== -1) return name
        }
        return ""
    }
    function separate(name) {
        backend.removeArtistAlias(name)
        refresh += 1
    }
    function pick(name) {
        if (chosen === "") { chosen = name; search = "" }
        else attach(name)
    }
}
