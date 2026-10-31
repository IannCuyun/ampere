import QtQuick
import QtQuick.Layouts
import "."

// Disliked — Contact Sheet (Iann's selected Direction B, 2026-08-15).
// The artwork run owns presentation selection only. Durable membership,
// restore, and permanent deletion remain backend-owned.
Item {
    id: view
    signal back()

    readonly property bool compact: width < 1080
    readonly property bool deleting: backend.deletingDisliked
    readonly property int dislikedCount: backend.dislikedFiles.length
    property var dislikedRows: []
    property bool selectionInitialized: false
    property int reloadGeneration: 0
    property string retainedSelectionFile: ""
    readonly property int rowCount: dislikedRows.length
    readonly property int selectedIndex: rowCount > 0
        ? Math.max(0, Math.min(contactSheet.currentIndex, rowCount - 1)) : -1
    readonly property var selectedSong: selectedIndex >= 0
        ? dislikedRows[selectedIndex] : ({})
    readonly property string selectedFile: selectedSong.file || ""

    function reloadRows() {
        var generation = ++reloadGeneration
        var priorFile = retainedSelectionFile !== ""
            ? retainedSelectionFile : (selectionInitialized ? selectedFile : "")
        var priorIndex = selectionInitialized ? selectedIndex : -1
        var rows = []
        var files = Array.from(backend.dislikedFiles)
        for (var i = 0; i < files.length; ++i)
            rows.push(backend.songInfo(files[i]))
        dislikedRows = rows
        // ListView applies a newly assigned model on the next event turn and
        // otherwise resets currentIndex to zero after our synchronous choice.
        Qt.callLater(function() {
            if (generation !== reloadGeneration)
                return
            if (rowCount <= 0) {
                contactSheet.currentIndex = -1
                selectionInitialized = false
                retainedSelectionFile = ""
                return
            }
            var nextIndex = priorFile !== "" ? files.indexOf(priorFile) : -1
            if (nextIndex < 0) {
                nextIndex = selectionInitialized && priorIndex >= 0
                    ? Math.min(priorIndex, rowCount - 1)
                    : Math.min(2, rowCount - 1)
            }
            selectionInitialized = true
            contactSheet.currentIndex = nextIndex
            retainedSelectionFile = files[nextIndex]
            contactSheet.positionViewAtIndex(nextIndex, ListView.Center)
        })
    }

    function selectIndex(index) {
        if (rowCount <= 0)
            return
        var nextIndex = Math.max(0, Math.min(index, rowCount - 1))
        contactSheet.currentIndex = nextIndex
        retainedSelectionFile = dislikedRows[nextIndex].file || ""
        Qt.callLater(function() {
            contactSheet.positionViewAtIndex(contactSheet.currentIndex, ListView.Center)
        })
    }

    function reconcileSelection() {
        if (rowCount <= 0) {
            contactSheet.currentIndex = -1
            selectionInitialized = false
            retainedSelectionFile = ""
            return
        }
        if (!selectionInitialized) {
            selectionInitialized = true
            contactSheet.currentIndex = Math.min(2, rowCount - 1)
        } else if (contactSheet.currentIndex < 0) {
            contactSheet.currentIndex = Math.min(2, rowCount - 1)
        } else if (contactSheet.currentIndex >= rowCount) {
            contactSheet.currentIndex = rowCount - 1
        }
        retainedSelectionFile = dislikedRows[contactSheet.currentIndex].file || ""
        Qt.callLater(function() {
            contactSheet.positionViewAtIndex(contactSheet.currentIndex, ListView.Center)
        })
    }

    function restoreSelected() {
        if (!deleting && selectedFile !== "")
            backend.toggleDislike(selectedFile)
    }

    function confirmSelectedDeletion() {
        if (selectedFile === "")
            return
        confirmDeletion([selectedFile],
            "Delete “" + (selectedSong.title || selectedFile) + "”?", 1)
    }

    Component.onCompleted: reloadRows()
    onWidthChanged: Qt.callLater(function() {
        if (contactSheet.currentIndex >= 0)
            contactSheet.positionViewAtIndex(contactSheet.currentIndex, ListView.Center)
    })

    Connections {
        target: backend
        function onDislikedChanged() { view.reloadRows() }
        function onLibrarySummaryChanged() { view.reloadRows() }
    }

    component RestoreAction: Rectangle {
        id: restoreAction
        property string label: "RESTORE"
        signal triggered()

        implicitWidth: 210
        implicitHeight: 44
        color: restoreMouse.pressed ? Qt.alpha(Theme.primary, 0.22)
             : restoreMouse.containsMouse ? Qt.alpha(Theme.primary, 0.16)
             : Qt.alpha(Theme.primary, 0.10)
        border.width: activeFocus ? 2 : 1
        border.color: activeFocus ? Theme.focusRing : Qt.alpha(Theme.primary, 0.72)
        activeFocusOnTab: enabled && visible
        Accessible.role: Accessible.Button
        Accessible.name: "Restore the selected track to rotation"
        Accessible.onPressAction: triggered()
        Keys.onReturnPressed: triggered()
        Keys.onSpacePressed: triggered()

        Row {
            anchors.centerIn: parent
            spacing: Theme.spaceSm
            Icon {
                name: "heart-o"
                size: 17
                color: restoreAction.enabled ? Theme.primary : Theme.washFaint
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: restoreAction.label
                color: restoreAction.enabled ? Theme.washInk : Theme.washFaint
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.weight: Font.DemiBold
                font.letterSpacing: 1.8
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        MouseArea {
            id: restoreMouse
            anchors.fill: parent
            enabled: restoreAction.enabled
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: restoreAction.triggered()
        }
    }

    component DangerAction: Rectangle {
        id: dangerAction
        property string label: ""
        property string accessibleName: label
        signal triggered()

        implicitWidth: Math.max(150, dangerRow.implicitWidth + Theme.spaceLg)
        implicitHeight: 44
        color: dangerMouse.pressed ? Qt.alpha(Theme.error, 0.16)
             : dangerMouse.containsMouse ? Qt.alpha(Theme.error, 0.09)
             : "transparent"
        border.width: activeFocus ? 2 : 1
        border.color: activeFocus ? Theme.focusRing : Qt.alpha(Theme.error, 0.48)
        activeFocusOnTab: enabled && visible
        Accessible.role: Accessible.Button
        Accessible.name: accessibleName
        Accessible.onPressAction: triggered()
        Keys.onReturnPressed: triggered()
        Keys.onSpacePressed: triggered()

        Row {
            id: dangerRow
            anchors.centerIn: parent
            spacing: Theme.spaceSm
            Icon {
                name: "trash"
                size: 15
                color: dangerAction.enabled ? Theme.error : Theme.washFaint
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: dangerAction.label
                color: dangerAction.enabled ? Theme.error : Theme.washFaint
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.weight: Font.DemiBold
                font.letterSpacing: 1.7
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        MouseArea {
            id: dangerMouse
            anchors.fill: parent
            enabled: dangerAction.enabled
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: dangerAction.triggered()
        }
    }

    Item {
        id: head
        anchors.left: parent.left
        anchors.leftMargin: Theme.pageGutter(view.width)
        anchors.right: parent.right
        anchors.rightMargin: Theme.pageGutter(view.width)
        anchors.top: parent.top
        anchors.topMargin: Math.max(66, Theme.pageTop(view.height))
        // Hidden desktop guidance must not consume compact vertical space.
        height: view.compact ? headLabel.implicitHeight
                             : Math.max(headLabel.implicitHeight, headNote.implicitHeight)

        Text {
            id: headLabel
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: "LIBRARY / DISLIKED  ·  " + view.dislikedCount + " OUT OF ROTATION"
            color: Theme.washMuted
            font.family: Theme.displayFont
            font.pixelSize: Theme.washMicro
            font.weight: Font.Medium
            font.letterSpacing: 2.4
        }

        Text {
            id: headNote
            visible: !view.compact
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(420, parent.width * 0.34)
            horizontalAlignment: Text.AlignRight
            wrapMode: Text.WordWrap
            text: "Restore freely. Permanent file removal stays behind a separate confirmation boundary."
            color: Theme.washMuted
            font.family: Theme.font
            font.pixelSize: Theme.fsSmall
            font.weight: Font.Light
            lineHeight: 1.35
        }
    }

    ListView {
        id: contactSheet
        objectName: "dislikedContactSheet"
        anchors.left: parent.left
        anchors.leftMargin: Theme.pageGutter(view.width)
        anchors.right: parent.right
        anchors.rightMargin: Theme.pageGutter(view.width)
        anchors.top: head.bottom
        anchors.topMargin: view.compact
            ? (view.height < 500 ? Theme.spaceSm : Theme.spaceLg)
            : Theme.space2xl
        height: tileSize + (view.compact ? Theme.spaceSm : Theme.spaceLg)
        orientation: ListView.Horizontal
        spacing: view.compact ? Theme.spaceSm : Theme.spaceMd
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: view.dislikedRows
        currentIndex: -1
        cacheBuffer: tileSize * 2
        activeFocusOnTab: visible && view.dislikedCount > 0
        Accessible.role: Accessible.List
        Accessible.name: "Disliked tracks. Use Left and Right to choose a track."
        Accessible.onDecreaseAction: view.selectIndex(currentIndex - 1)
        Accessible.onIncreaseAction: view.selectIndex(currentIndex + 1)
        Keys.onLeftPressed: view.selectIndex(currentIndex - 1)
        Keys.onRightPressed: view.selectIndex(currentIndex + 1)

        // The sheet is generous with whatever height is left AFTER the
        // actions have theirs. At the 720x480 floor it used to take its full
        // width-derived size and push Restore / Delete straight through the
        // player bar, so the only controls on the page could not be reached
        // (found 2026-08-22, ROADMAP 5.1).
        // Ask the actions what they need rather than guessing: they are the
        // only controls on this page and they are never the thing that gives
        // way (ROADMAP 5.1).
        readonly property real actionRoom: view.compact
            ? compactActions.implicitHeight + Theme.spaceMd * 2
            : 132
        readonly property real heightBudget: Math.max(
            64, view.height - contactSheet.y
                - (view.compact ? Theme.spaceSm : Theme.spaceLg)
                - contactSheet.actionRoom)
        // The sleeve takes its size from the width, exactly as it always
        // did; the height budget only ever REDUCES it, and only when the
        // room is too short to hold the actions as well (ROADMAP 5.1).
        readonly property real widthSize: view.compact
            ? Math.min(220, Math.max(64, (width - spacing * 2) / 3))
            : Math.min(300, Math.max(220, (width - spacing * 4) / 5))
        readonly property real tileSize: Math.max(
            64, Math.min(widthSize, heightBudget))
        readonly property real edgeInset: Math.max(0, width / 2 - tileSize / 2)

        header: Item {
            width: contactSheet.edgeInset
            height: contactSheet.height
        }
        footer: Item {
            width: contactSheet.edgeInset
            height: contactSheet.height
        }

        delegate: Item {
            id: sleeve
            width: contactSheet.tileSize
            height: contactSheet.height
            readonly property var song: modelData
            readonly property string file: song.file || ""
            readonly property int distance: Math.abs(index - contactSheet.currentIndex)
            readonly property bool selected: index === contactSheet.currentIndex

            Item {
                id: artStage
                anchors.centerIn: parent
                width: contactSheet.tileSize
                height: contactSheet.tileSize
                scale: sleeve.selected ? 1 : sleeve.distance === 1 ? 0.90 : 0.82
                opacity: sleeve.selected ? 1 : sleeve.distance === 1 ? 0.70 : 0.42

                MediaArtwork {
                    anchors.fill: parent
                    kind: "album"
                    source: "image://art/" + encodeURIComponent(sleeve.file)
                }

                Rectangle {
                    anchors.fill: parent
                    visible: sleeve.selected
                    color: "transparent"
                    border.width: 1
                    border.color: Theme.primary
                }

                Rectangle {
                    visible: sleeve.selected
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: Math.min(78, parent.height * 0.30)
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: "transparent" }
                        GradientStop { position: 0.38; color: Qt.rgba(0.035, 0.032, 0.028, 0.50) }
                        GradientStop { position: 1.0; color: Qt.rgba(0.035, 0.032, 0.028, 0.94) }
                    }
                }

                Column {
                    visible: sleeve.selected
                    anchors.left: parent.left
                    anchors.leftMargin: Theme.spaceMd
                    anchors.right: parent.right
                    anchors.rightMargin: Theme.spaceMd
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: Theme.spaceSm
                    spacing: 3
                    Text {
                        width: parent.width
                        text: sleeve.song.title || sleeve.file
                        elide: Text.ElideRight
                        color: Theme.washInk
                        font.family: Theme.font
                        font.pixelSize: Theme.fsBody
                        font.weight: Font.Medium
                    }
                    Text {
                        width: parent.width
                        text: sleeve.song.artist || "Unknown artist"
                        elide: Text.ElideRight
                        color: Theme.washMuted
                        font.family: Theme.displayFont
                        font.pixelSize: Theme.fsMicro
                        font.letterSpacing: 1.4
                    }
                }

                Rectangle {
                    anchors.fill: parent
                    color: sleeveHover.hovered && !sleeve.selected
                        ? Qt.alpha(Theme.primary, 0.08) : "transparent"
                }
            }

            Accessible.role: Accessible.ListItem
            Accessible.name: (song.title || file) + ", " + (song.artist || "Unknown artist")
            TapHandler { onTapped: view.selectIndex(index) }
            HoverHandler { id: sleeveHover; cursorShape: Qt.PointingHandCursor }
        }

        EmptyState {
            visible: view.dislikedCount === 0
            anchors.centerIn: parent
            width: Math.min(360, contactSheet.width)
            icon: "heart-crack"
            headline: "Nothing disliked"
            hint: "The whole archive is in rotation."
        }
    }

    GlowButton {
        objectName: "dislikedPrevious"
        visible: view.dislikedCount > 1
        enabled: !view.deleting && view.selectedIndex > 0
        opacity: enabled ? 0.82 : 0.28
        anchors.left: contactSheet.left
        anchors.verticalCenter: contactSheet.verticalCenter
        icon: "chevron-left"
        tip: "Previous disliked track"
        onClicked: view.selectIndex(view.selectedIndex - 1)
    }

    GlowButton {
        objectName: "dislikedNext"
        visible: view.dislikedCount > 1
        enabled: !view.deleting && view.selectedIndex < view.rowCount - 1
        opacity: enabled ? 0.82 : 0.28
        anchors.right: contactSheet.right
        anchors.verticalCenter: contactSheet.verticalCenter
        icon: "chevron-right"
        tip: "Next disliked track"
        onClicked: view.selectIndex(view.selectedIndex + 1)
    }

    Item {
        id: desktopActions
        visible: !view.compact && view.dislikedCount > 0
        anchors.left: contactSheet.left
        anchors.right: contactSheet.right
        anchors.top: contactSheet.bottom
        anchors.topMargin: Theme.spaceLg
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Theme.spaceLg

        Column {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width * 0.36
            spacing: Theme.spaceXs
            Text {
                text: (view.selectedIndex + 1) + " / " + view.dislikedCount + "  ·  SELECTED"
                color: Theme.primary
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.letterSpacing: 2.1
            }
            Text {
                width: parent.width
                text: view.selectedSong.title || view.selectedFile
                elide: Text.ElideRight
                color: Theme.washInk
                font.family: Theme.font
                font.pixelSize: Theme.fsTitle
                font.weight: Font.Light
            }
            Text {
                width: parent.width
                text: (view.selectedSong.artist || "Unknown artist")
                    + "  ·  " + (view.selectedSong.album || "Unknown album")
                elide: Text.ElideRight
                color: Theme.washMuted
                font.family: Theme.font
                font.pixelSize: Theme.fsSmall
            }
        }

        RestoreAction {
            objectName: "dislikedRestore"
            anchors.centerIn: parent
            width: 210
            height: 44
            enabled: !view.deleting
            opacity: enabled ? 1 : 0.45
            onTriggered: view.restoreSelected()
        }

        Column {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(360, parent.width * 0.28)
            spacing: Theme.spaceSm
            Text {
                anchors.right: parent.right
                text: "SEPARATE DELETION BOUNDARY"
                color: Theme.washFaint
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.letterSpacing: 1.8
            }
            Row {
                anchors.right: parent.right
                spacing: Theme.spaceSm
                DangerAction {
                    objectName: "dislikedDeleteSelected"
                    enabled: !view.deleting
                    label: "DELETE FILE…"
                    accessibleName: "Permanently delete the selected file"
                    onTriggered: view.confirmSelectedDeletion()
                }
                DangerAction {
                    objectName: "dislikedDeleteAll"
                    enabled: !view.deleting
                    label: "DELETE ALL " + view.dislikedCount + "…"
                    accessibleName: "Permanently delete every disliked file"
                    onTriggered: view.confirmDeletion(backend.dislikedFiles,
                        "Delete every disliked file?", view.dislikedCount)
                }
            }
        }

        Text {
            visible: view.deleting
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            text: "Removing files and reconciling the library…"
            color: Theme.primary
            font.family: Theme.font
            font.pixelSize: Theme.fsSmall
        }
    }

    ColumnLayout {
        id: compactActions
        visible: view.compact && view.dislikedCount > 0
        anchors.left: contactSheet.left
        anchors.right: contactSheet.right
        anchors.top: contactSheet.bottom
        anchors.topMargin: Theme.spaceMd
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Theme.spaceMd
        spacing: Theme.spaceSm

        Text {
            Layout.fillWidth: true
            text: (view.selectedIndex + 1) + " / " + view.dislikedCount + "  ·  SELECTED"
            color: Theme.primary
            font.family: Theme.displayFont
            font.pixelSize: Theme.washMicro
            font.letterSpacing: 2.0
        }
        Text {
            Layout.fillWidth: true
            text: view.selectedSong.title || view.selectedFile
            elide: Text.ElideRight
            color: Theme.washInk
            font.family: Theme.font
            font.pixelSize: Theme.fsTitle
            font.weight: Font.Light
        }
        Text {
            Layout.fillWidth: true
            text: (view.selectedSong.artist || "Unknown artist")
                + "  ·  " + (view.selectedSong.album || "Unknown album")
            elide: Text.ElideRight
            color: Theme.washMuted
            font.family: Theme.font
            font.pixelSize: Theme.fsSmall
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm
            RestoreAction {
                objectName: "dislikedRestoreCompact"
                Layout.fillWidth: true
                Layout.preferredHeight: 44
                enabled: !view.deleting
                opacity: enabled ? 1 : 0.45
                onTriggered: view.restoreSelected()
            }
            DangerAction {
                objectName: "dislikedDeleteSelectedCompact"
                Layout.fillWidth: true
                enabled: !view.deleting
                label: "DELETE FILE…"
                accessibleName: "Permanently delete the selected file"
                onTriggered: view.confirmSelectedDeletion()
            }
        }
        DangerAction {
            objectName: "dislikedDeleteAllCompact"
            Layout.alignment: Qt.AlignRight
            enabled: !view.deleting
            label: "DELETE ALL " + view.dislikedCount + "…"
            accessibleName: "Permanently delete every disliked file"
            onTriggered: view.confirmDeletion(backend.dislikedFiles,
                "Delete every disliked file?", view.dislikedCount)
        }
        Text {
            visible: view.deleting
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            text: "Removing files and reconciling the library…"
            color: Theme.primary
            font.family: Theme.font
            font.pixelSize: Theme.fsSmall
        }
        Item { Layout.fillHeight: true }
    }

    function confirmDeletion(files, title, count) {
        if (view.deleting || !files || files.length === 0)
            return
        deleteDialog.files = Array.from(files)
        deleteDialog.title = title
        deleteDialog.count = count
        deleteDialog.visible = true
        deleteDialog.forceActiveFocus()
    }

    Item {
        id: deleteDialog
        objectName: "dislikedDeleteDialog"
        property var files: []
        property string title: ""
        property int count: 0
        anchors.fill: parent
        visible: false
        z: 100
        focus: visible
        Keys.onEscapePressed: visible = false

        Rectangle {
            anchors.fill: parent
            color: Qt.alpha(Theme.bgLow, 0.82)
            MouseArea {
                anchors.fill: parent
                onClicked: deleteDialog.visible = false
            }
        }

        Rectangle {
            anchors.centerIn: parent
            width: Math.min(520, parent.width - Theme.space2xl)
            height: dialogContent.implicitHeight + Theme.space2xl
            radius: Theme.radius
            color: Theme.raisedSurface
            border.color: Theme.outline
            border.width: 1

            ColumnLayout {
                id: dialogContent
                anchors.fill: parent
                anchors.margins: Theme.spaceLg
                spacing: Theme.spaceMd

                Text {
                    Layout.fillWidth: true
                    text: deleteDialog.title
                    wrapMode: Text.WordWrap
                    color: Theme.text
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.fsTitle
                    font.weight: Font.DemiBold
                }
                Text {
                    Layout.fillWidth: true
                    text: deleteDialog.count === 1
                        ? "This removes the audio file from your library."
                        : deleteDialog.count + " audio files will be removed from your library."
                    wrapMode: Text.WordWrap
                    color: Theme.textDim
                    font.family: Theme.font
                    font.pixelSize: Theme.fsBody
                }
                Text {
                    Layout.fillWidth: true
                    text: backend.deleteMode === "server"
                        ? "The deletion occurs on the library server and propagates to synced devices. This cannot be undone in Ampere."
                        : "The deletion occurs on this device. This cannot be undone in Ampere."
                    wrapMode: Text.WordWrap
                    color: Theme.textDim
                    font.family: Theme.font
                    font.pixelSize: Theme.fsSmall
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spaceSm
                    Item { Layout.fillWidth: true }
                    GlowButton {
                        label: "CANCEL"
                        tip: "Keep the files"
                        onClicked: deleteDialog.visible = false
                    }
                    GlowButton {
                        icon: "trash"
                        label: deleteDialog.count === 1 ? "DELETE FILE" : "DELETE FILES"
                        active: true
                        tip: "Confirm permanent deletion"
                        onClicked: {
                            backend.deleteDislikedSongs(deleteDialog.files)
                            deleteDialog.visible = false
                        }
                    }
                }
            }
        }
    }
}
