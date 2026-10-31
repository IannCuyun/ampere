import QtQuick
import "."

// The honest first-index state. While the library worker reads the archive
// the rooms have nothing to show; rather than an unexplained void, one
// led-caps line on the wash recipe sits exactly where the content will land.
// No spinner, no box — the statement is the state.
//
// `inset` is the page gutter for rooms that mount this at the raw page edge
// (pass Theme.pageGutter(width)); rooms whose content column is already
// indented leave it at 0.
Column {
    id: root
    property int count: 0            // songs indexed so far; 0 hides the line
    property real inset: 0
    property string headline: "Reading the archive…"
    objectName: "archiveLoading"
    leftPadding: inset
    spacing: 8

    Text {
        objectName: "archiveLoadingHeadline"
        text: root.headline
        color: Theme.washFaint
        font.family: Theme.displayFont
        font.pixelSize: Theme.washMicro
        font.letterSpacing: 3
        font.capitalization: Font.AllUppercase
    }
    Text {
        visible: root.count > 0
        text: root.count.toLocaleString() + " songs indexed so far"
        color: Theme.washMuted
        font.family: Theme.font
        font.pixelSize: Theme.fsSmall
    }
}
