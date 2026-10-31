import QtQuick
import "."

// The one track options menu (play now, play next, queue, like, more like
// this, add to playlist, edit). TrackRow and the Search room share this exact
// option set and handler set; only "play now" and "edit" are owner-defined
// (Iann verdict 2026-08-20 #7: no surface grows a parallel track menu).
//
// "Add to playlist" swaps this same popup to a playlist chooser rather than
// opening a second menu — AmpereMenu is deliberately flat, and one menu with
// two pages keeps the vocabulary single (Iann, 2026-08-22).
Loader {
    id: loader

    property var trackData: ({})
    // "" = the action list; otherwise the playlist chooser
    property string page: ""
    signal playNow()
    signal editRequested(var track)

    readonly property var actionOptions: [
        {id: "now",  label: "PLAY NOW"},
        {id: "next", label: "PLAY NEXT"},
        {id: "add",  label: "ADD TO QUEUE"},
        {id: "playlist", label: "ADD TO PLAYLIST  ›"},
        {id: "toggle-like", label: backend.likedFiles.indexOf(
            loader.trackData.file || "") >= 0 ? "REMOVE FROM LIKED" : "ADD TO LIKED"},
        {id: "like", label: "MORE LIKE THIS ✦"},
        {id: "edit", label: "EDIT TRACK INFO…"},
    ]
    readonly property var playlistOptions: {
        var rows = [{id: "back", label: "‹  BACK"}]
        var names = backend.playlists || []
        for (var i = 0; i < names.length; ++i)
            rows.push({id: "pl:" + names[i], label: String(names[i])})
        if (names.length === 0)
            rows.push({id: "none", label: "NO PLAYLISTS YET"})
        return rows
    }

    function openAt(item, x, y) {
        page = ""
        active = true
        loader.item.popupAt(item, x, y)
    }

    active: false
    sourceComponent: AmpereMenu {
        options: loader.page === "playlist" ? loader.playlistOptions
                                            : loader.actionOptions
        // The chooser stays open under the cursor instead of reopening
        // somewhere else, so the two pages read as one gesture.
        closeOnPick: false
        onPicked: id => {
            if (id === "playlist") { loader.page = "playlist"; return }
            if (id === "back") { loader.page = ""; return }
            if (id === "none") return
            close()
            if (id.indexOf("pl:") === 0) {
                backend.addToPlaylist(id.substring(3),
                                      [loader.trackData.file])
                loader.page = ""
                return
            }
            if (id === "now") loader.playNow()
            else if (id === "next") backend.playNext(loader.trackData.file)
            else if (id === "add") backend.queuePath(loader.trackData.file)
            else if (id === "toggle-like") backend.toggleLike(loader.trackData.file)
            else if (id === "like") backend.moreLikeThis(loader.trackData.file)
            else if (id === "edit") loader.editRequested(loader.trackData)
        }
    }
}
