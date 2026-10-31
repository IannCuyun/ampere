import QtQuick
import QtQuick.Layouts
import "."

Item {
    id: view
    property string shelf: ""
    property var tracks: []
    property bool active: false
    readonly property bool compact: width < 700
    // Shelves open on the archive's shared page origin, like every other room.
    readonly property int pageMargin: compact ? Theme.spaceLg
                                             : Theme.pageGutter(width)
    readonly property var fileList: tracks.map(t => t.file)
    readonly property var meta: ({ arrivals:{title:"New arrivals",sub:"Fresh signals from the last three weeks"}, heavy:{title:"Heavy rotation",sub:"The records holding the room"}, loved:{title:"Loved, not lately",sub:"Favorites waiting to return"}, history:{title:"History",sub:"Your listening trail, newest first"}, throwback:{title:"Throwback",sub:"A transmission from months past"}, deep:{title:"Deep cuts",sub:"The unheard side of familiar rooms"} })
    function reload() {
        if (shelf === "") return
        tracks = backend.cachedSmartShelf(shelf)
        backend.requestLibrarySummary()
    }
    function whenText(t) { if (!t) return ""; var d=(Date.now()/1000-t)/86400; return d<1?"today":d<14?Math.round(d)+" days ago":new Date(t*1000).toLocaleDateString(Qt.locale(),"MMM d") }
    onShelfChanged: if (active) reload()
    onActiveChanged: if (active) reload()
    Connections {
        target: backend
        function onLibrarySummaryChanged() {
            if (view.active && view.shelf !== "")
                view.tracks = backend.cachedSmartShelf(view.shelf)
        }
    }

    ListView {
        id: list; anchors.fill: parent; anchors.leftMargin: view.pageMargin; anchors.rightMargin: view.pageMargin; anchors.topMargin: Theme.pageTop(view.height); clip: true; model: view.tracks; spacing: 0
        header: Item { width: list.width; height: view.compact ? 142 : 144
            Column { id:headerCopy;anchors.left:parent.left;anchors.right:view.compact?parent.right:headerActions.left;anchors.rightMargin:view.compact?0:Theme.spaceLg;anchors.bottom:view.compact?headerActions.top:parent.bottom;anchors.bottomMargin:view.compact?Theme.spaceSm:Theme.spaceXl;spacing:Theme.spaceSm
                Text { width:parent.width;text: (view.meta[view.shelf]||{title:""}).title; color: Theme.washInk; font.family: Theme.displayFont; font.pixelSize: view.compact?Theme.fsStat:Theme.fsHero; font.weight: Font.Light;wrapMode:Text.Wrap;maximumLineCount:2;elide:Text.ElideRight }
                Text { width:parent.width;text: (view.meta[view.shelf]||{sub:""}).sub + "  /  " + view.tracks.length + " tracks"; color: Theme.washMuted; font.family: Theme.font; font.pixelSize: Theme.fsBody;wrapMode:Text.Wrap;maximumLineCount:2;elide:Text.ElideRight }
            }
            Row { id:headerActions;anchors.left:view.compact?parent.left:undefined;anchors.right:view.compact?undefined:parent.right;anchors.bottom:parent.bottom;anchors.bottomMargin:view.compact?Theme.spaceLg:Theme.spaceXl;spacing:Theme.spaceSm
                GlowButton { icon:"play"; label:"PLAY"; visible:view.tracks.length>0; onClicked:backend.playFiles(view.fileList,0) }
                GlowButton { shuffleIcon:true; label:"SHUFFLE"; visible:view.tracks.length>0; onClicked:backend.playFilesShuffled(view.fileList) }
            }
        }
        delegate: TrackRow { required property var modelData; required property int index; width:list.width; trackData:modelData; fileList:view.fileList; rowIndex:index; whenText:view.shelf==="deep"?(modelData.when||""):view.whenText(modelData.when) }
        EmptyState { anchors.centerIn:parent;width:Math.max(0,parent.width-Theme.space2xl);visible:view.tracks.length===0;icon:"wave";headline:"THE ROOM IS QUIET";hint:"This shelf will fill as Ampere learns your listening." }
    }
}
