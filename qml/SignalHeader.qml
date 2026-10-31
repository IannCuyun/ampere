import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "."

// One Ampere search instrument. The persistent shell owns the wordmark;
// Search owns only this line field, the recent-searches plane beneath it
// (artboard `B · Search bar history`, DECISIONS 2026-08-20 #5/#6), and the
// full-room Record Wall below.
Item {
    id: header

    property alias query: search.text
    property var historyProvider: backend
    readonly property var history: historyProvider
        && historyProvider.searchHistory !== undefined
        ? historyProvider.searchHistory : []
    readonly property bool historyOpen: search.activeFocus
        && search.text === "" && history.length > 0
    // Main's global Esc defers to the staged-Esc contract through these.
    readonly property bool fieldHasFocus: search.activeFocus
    function focusField() { search.forceActiveFocus(); }
    property int historyIndex: -1

    signal openFolder(string path)
    signal openAlbum(string path, string album)
    signal openArtist(string name, string path)
    signal editTrack(var track)
    signal dismiss()

    function focusSearch() {
        search.forceActiveFocus();
        Qt.callLater(search.selectAll);
    }
    // Clear is an explicit choice (S-09/S-14): empties text + results and
    // hands focus back to the field.
    function clearSearch() {
        search.text = "";
        results.clearResults();
        results.close();
        search.forceActiveFocus();
    }
    // Closing keeps the last query and results (Iann verdict #5); reopening
    // restores them through focusSearch().
    function closeSearch() {
        dismiss();
    }
    function escapeField() {
        closeSearch();
    }
    function submit() {
        var trimmed = search.text.trim();
        if (historyOpen && historyIndex >= 0 && historyIndex < history.length) {
            runHistory(history[historyIndex]);
            return;
        }
        if (trimmed.length >= 2)
            results.expandAll();
    }
    function remember(text) {
        if (historyProvider && typeof historyProvider.rememberSearch === "function")
            historyProvider.rememberSearch(text);
    }
    function runHistory(text) {
        historyIndex = -1;
        search.text = text;
        search.forceActiveFocus();
        Qt.callLater(function() { search.cursorPosition = search.text.length; });
    }
    function forget(text) {
        if (historyProvider && typeof historyProvider.forgetSearch === "function")
            historyProvider.forgetSearch(text);
        historyIndex = Math.min(historyIndex, history.length - 1);
    }
    function clearHistory() {
        if (historyProvider && typeof historyProvider.clearSearchHistory === "function")
            historyProvider.clearSearchHistory();
        historyIndex = -1;
        search.forceActiveFocus();
    }
    // Verification seam: open the shared track menu on the first song row
    // without synthetic pointer input.
    function openFirstRowMenu() { results.openFirstRowMenu(); }
    function moveHistory(step) {
        if (!history.length)
            return;
        historyIndex = (historyIndex + step + history.length) % history.length;
    }

    MouseArea {
        anchors.fill: parent
        z: 0
        onClicked: header.closeSearch()
    }

    SearchDropdown {
        id: results
        z: 1
        anchors.fill: parent
        anchors.topMargin: 82
        query: search.text
        onCloseRequested: header.closeSearch()
        onFocusFieldRequested: search.forceActiveFocus()
        onQueryCommitted: q => header.remember(q)
        onEditTrack: track => header.editTrack(track)
        onOpenFolder: p => {
            header.openFolder(p);
            header.closeSearch();
        }
        onOpenAlbum: (p, a) => {
            header.openAlbum(p, a);
            header.closeSearch();
        }
        onOpenArtistPage: (n, p) => {
            header.openArtist(n, p);
            header.closeSearch();
        }
    }

    Rectangle {
        id: field
        z: 2
        anchors.top: parent.top
        anchors.topMargin: 20
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(500, Math.max(280, header.width * 0.42))
        height: 44
        color: "transparent"

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: search.activeFocus ? 2 : 1
            color: search.activeFocus ? Theme.primary : Theme.washHair
            Behavior on color { ColorAnimation { duration: 120 } }
        }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 8
            spacing: 10
            Icon {
                name: "search"
                size: 15
                color: search.activeFocus ? Theme.primary : Theme.washMuted
            }
            TextField {
                id: search
                Layout.fillWidth: true
                background: null
                color: Theme.washInk
                selectionColor: Qt.alpha(Theme.primary, 0.28)
                selectedTextColor: Theme.washInk
                placeholderText: "Search your archive"
                Accessible.name: "Search your archive"
                placeholderTextColor: Theme.washFaint
                font.family: Theme.font
                font.pixelSize: Theme.fsBody
                selectByMouse: true
                onTextChanged: header.historyIndex = -1
                Keys.onReturnPressed: header.submit()
                Keys.onEnterPressed: header.submit()
                // Staged Esc (S-09): from a result, Esc returns here (owned
                // by the room); from the field, Esc closes the room and the
                // query survives for the next opening.
                Keys.onEscapePressed: header.escapeField()
                Keys.onDownPressed: {
                    if (header.historyOpen)
                        header.moveHistory(1);
                    else
                        results.focusFirst();
                }
                Keys.onUpPressed: if (header.historyOpen) header.moveHistory(-1)
            }
            GlowButton {
                visible: search.text !== ""
                activeFocusOnTab: false
                icon: "close"
                tip: "Clear search"
                onClicked: header.clearSearch()
            }
        }
    }

    // ---- recent searches (artboard `B · Search bar history`) ----
    Rectangle {
        id: historyPlane
        objectName: "searchHistoryPlane"
        z: 3
        visible: header.historyOpen
        anchors.top: field.bottom
        anchors.topMargin: 8
        anchors.left: field.left
        anchors.right: field.right
        height: historyColumn.height
        // SPEC row 24 recipe: square, hairline, translucent bgLow. The 0.84
        // alpha is deliberate (SPEC row 23 bans an opaque generic slab) and
        // stays pinned; the 2026-08-21 correction is in the ROWS, which were
        // reading as a generic list widget — see below.
        color: Qt.alpha(Theme.bgLow, 0.84)
        border.color: Theme.washHair
        border.width: 1
        radius: 0

        Column {
            id: historyColumn
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 1
            anchors.rightMargin: 1
            spacing: 0
            Text {
                topPadding: 14
                leftPadding: 16
                bottomPadding: 8
                text: "RECENT"
                color: Theme.washFaint
                font.family: Theme.displayFont
                font.pixelSize: Theme.fsMicro
                font.letterSpacing: 3
            }
            Repeater {
                model: header.history
                delegate: Item {
                    id: historyRow
                    required property string modelData
                    required property int index
                    readonly property bool current: header.historyIndex === index
                    width: historyColumn.width
                    height: 44 + (index > 0 ? 1 : 0)
                    Accessible.role: Accessible.Button
                    Accessible.name: "Search again for " + modelData
                    Accessible.onPressAction: header.runHistory(modelData)

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 44
                        color: historyRow.current || rowHover.hovered
                            ? Qt.alpha(Theme.washInk, 0.065) : "transparent"
                        Icon {
                            id: rowGlyph
                            anchors.left: parent.left
                            anchors.leftMargin: 16
                            anchors.verticalCenter: parent.verticalCenter
                            name: "search"
                            size: 13
                            color: Theme.washMuted
                        }
                        Text {
                            anchors.left: rowGlyph.right
                            anchors.leftMargin: 12
                            anchors.right: forgetGlyph.left
                            anchors.rightMargin: 12
                            anchors.verticalCenter: parent.verticalCenter
                            text: historyRow.modelData
                            color: Theme.washInk
                            font.family: Theme.font
                            font.pixelSize: Theme.fsBody
                            elide: Text.ElideRight
                        }
                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            anchors.leftMargin: 16
                            anchors.rightMargin: 16
                            height: historyRow.index < header.history.length - 1 ? 1 : 0
                            color: Theme.washHair
                        }
                        HoverHandler { id: rowHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: header.runHistory(historyRow.modelData) }
                        Item {
                            id: forgetGlyph
                            anchors.right: parent.right
                            anchors.rightMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            width: 28
                            height: 28
                            Accessible.role: Accessible.Button
                            Accessible.name: "Forget " + historyRow.modelData
                            Accessible.onPressAction: header.forget(historyRow.modelData)
                            Text {
                                anchors.centerIn: parent
                                text: "×"
                                color: forgetHover.hovered ? Theme.washInk : Theme.washFaint
                                font.family: Theme.font
                                font.pixelSize: 14
                            }
                            HoverHandler { id: forgetHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: header.forget(historyRow.modelData) }
                        }
                    }
                }
            }
            Item {
                width: historyColumn.width
                height: 1 + 12 + clearLabel.height + 14
                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    height: 1
                    color: Theme.washHair
                }
                Text {
                    id: clearLabel
                    anchors.left: parent.left
                    anchors.leftMargin: 16
                    anchors.top: parent.top
                    anchors.topMargin: 13
                    text: "CLEAR HISTORY"
                    color: clearHover.hovered ? Theme.washInk : Theme.primary
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.fsMicro
                    font.letterSpacing: 3
                }
                Accessible.role: Accessible.Button
                Accessible.name: "Clear search history"
                Accessible.onPressAction: header.clearHistory()
                HoverHandler { id: clearHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: header.clearHistory() }
            }
        }
    }
}
