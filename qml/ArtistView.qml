import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import "."

// Artist Discography — Direction A hybrid (design/SPEC.md · Artist page).
// A monumental rectilinear portrait owns the left field; a wide identity
// banner introduces C-style release chapters in the right field.
Item {
    id: view

    property string artistName: ""
    property string artistPath: ""
    property string canonicalName: ""
    signal openPath(string path)
    signal openAlbum(string path, string album)
    signal destinationRequested(string section)

    property var bio: ({})
    property var disco: []
    // The room is the artist's leading release, softened, exactly as Album
    // View makes the record its own room. Before this the page showed
    // whatever happened to be PLAYING, so a page about one artist sat in
    // another artist's record (2026-08-22).
    readonly property string roomFile: {
        for (var i = 0; i < disco.length; ++i) {
            var tracks = disco[i].tracks || []
            if (tracks.length && tracks[0].file) return tracks[0].file
        }
        return ""
    }
    property bool synchronousArtworkPreview: false
    property string filterQuery: ""
    property string sortKey: "plays"
    property bool sortDescending: true
    readonly property var sortOptions: [
        { id: "plays", label: "Listening" },
        { id: "title", label: "Release title" },
        { id: "year", label: "Release year" },
        { id: "tracks", label: "Track count" }
    ]
    readonly property bool compact: width < 900
    readonly property var albumCount: disco.filter(function(album) {
        return album.album !== ""
    }).length
    readonly property int songCount: disco.reduce(function(total, album) {
        return total + album.tracks.length
    }, 0)
    readonly property var artistFiles: visibleDisco.reduce(function(files, album) {
        return files.concat(view.albumFiles(album))
    }, [])
    readonly property string portraitSource: bio.portrait
        ? "image://art/portrait-full:" + bio.portrait : ""
    readonly property real pageGutter: compact ? 40 : Theme.pageGutter(width)
    readonly property real pageTop: compact ? 70 : Math.max(76, height * 0.085)
    readonly property real pageBottom: 20
    readonly property real fieldGap: compact ? 18 : Math.max(30, width * 0.024)

    // Discography resolves off the GUI thread; the previous list stays until
    // the newest request answers, and older responses are dropped.
    property int discoRequestSerial: 0

    function reload() {
        if (!artistName)
            return
        canonicalName = backend.canonicalArtistName(artistName)
        discoRequestSerial += 1
        backend.requestArtistDiscography(canonicalName, discoRequestSerial)
        bio = ({})
        backend.requestArtistBio(canonicalName)
    }
    function applyDiscography(artist, serial, rows) {
        if (artist !== canonicalName || Number(serial) < discoRequestSerial)
            return
        disco = rows || []
    }

    function releaseYear(album) {
        if (!album || !album.tracks || !album.tracks.length)
            return ""
        var track = album.tracks[0]
        var value = String(track.year || track.date || "")
        var match = value.match(/[0-9]{4}/)
        return match ? match[0] : ""
    }

    function albumDirectory(album) {
        if (!album || !album.tracks || !album.tracks.length)
            return artistPath
        var file = String(album.tracks[0].file || "")
        return file.substring(0, file.lastIndexOf("/")) || artistPath
    }

    // Only a DIFFERING credit is shown: repeating the artist whose page this
    // is was already rejected (SPEC row 39), and featured guests are now real
    // identities (ROADMAP 1.3).
    function credit(track) {
        var artist = String((track && track.artist) || "")
        var primary = String(view.canonicalName || "")
        if (!artist || !primary || artist === primary) return ""
        var lowered = artist.toLowerCase(), lead = primary.toLowerCase()
        if (lowered.indexOf(lead) === 0) {
            var rest = artist.slice(primary.length)
                             .replace(/^[\s,&/·]*(feat\.?|featuring|with|w\/)?[\s.]*/i, "")
            return rest || ""
        }
        return artist
    }

    function albumFiles(album) {
        return album && album.tracks
            ? album.tracks.map(function(track) { return track.file }) : []
    }

    function sortLabel() {
        for (var i = 0; i < sortOptions.length; ++i)
            if (sortOptions[i].id === sortKey)
                return sortOptions[i].label
        return "Listening"
    }

    function chooseSort(key) {
        sortKey = key
    }

    function toggleSortDirection() {
        sortDescending = !sortDescending
    }

    function sortDirectionName() {
        return sortDescending ? "reverse" : "forward"
    }

    readonly property var visibleDisco: {
        var query = filterQuery.trim().toLocaleLowerCase()
        var rows = []
        for (var i = 0; i < disco.length; ++i) {
            var release = disco[i]
            var title = String(release.album || "Singles & loose tracks")
            var year = releaseYear(release)
            var releaseMatches = !query
                || title.toLocaleLowerCase().indexOf(query) !== -1
                || year.indexOf(query) !== -1
            var tracks = releaseMatches ? release.tracks.slice()
                : release.tracks.filter(function(track) {
                    return String(track.title || "").toLocaleLowerCase()
                        .indexOf(query) !== -1
                })
            if (releaseMatches || tracks.length) {
                rows.push({
                    album: release.album,
                    plays: Number(release.plays || 0),
                    tracks: tracks,
                    sourceIndex: i
                })
            }
        }
        var direction = sortDescending ? -1 : 1
        rows.sort(function(a, b) {
            var result = 0
            if (sortKey === "title") {
                result = String(a.album || "Singles & loose tracks")
                    .toLocaleLowerCase().localeCompare(
                        String(b.album || "Singles & loose tracks")
                            .toLocaleLowerCase())
            } else if (sortKey === "year") {
                result = Number(releaseYear(a) || 0)
                       - Number(releaseYear(b) || 0)
            } else if (sortKey === "tracks") {
                result = a.tracks.length - b.tracks.length
            } else {
                result = Number(a.plays || 0) - Number(b.plays || 0)
            }
            if (result === 0)
                result = a.sourceIndex - b.sourceIndex
            return direction * result
        })
        return rows
    }

    onArtistNameChanged: reload()
    onVisibleChanged: if (visible && disco.length === 0) reload()

    Connections {
        target: backend
        ignoreUnknownSignals: true
        function onArtistDiscographyReady(name, serial, rows) {
            view.applyDiscography(name, serial, rows)
        }
        function onArtistBioReady(name, info) {
            if (name === view.canonicalName)
                view.bio = info
        }
        function onDatabaseUpdated() {
            if (view.visible)
                view.reload()
        }
    }

    Rectangle {
        anchors.fill: parent
        color: Qt.alpha("#090808", 0.27)
    }

    component BannerAction: Item {
        id: bannerAction
        property string iconName: ""
        property string labelText: ""
        property bool primary: false
        signal triggered()

        width: Math.max(76, actionContents.width + 22)
        height: 44
        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: labelText
        Accessible.onPressAction: bannerAction.triggered()
        Keys.onReturnPressed: bannerAction.triggered()
        Keys.onEnterPressed: bannerAction.triggered()
        Keys.onSpacePressed: bannerAction.triggered()

        Rectangle {
            anchors.fill: parent
            color: actionTap.pressed
                ? Qt.alpha(Theme.primary, 0.16)
                : actionHover.hovered ? Theme.hoverSurface : "transparent"
            border.width: bannerAction.activeFocus ? 1 : 0
            border.color: Theme.focusRing
        }
        Row {
            id: actionContents
            anchors.centerIn: parent
            spacing: 8
            Icon {
                name: bannerAction.iconName
                size: bannerAction.primary ? 15 : 14
                color: bannerAction.primary || bannerAction.activeFocus
                    || actionHover.hovered ? Theme.primary : Theme.washMuted
            }
            Text {
                text: bannerAction.labelText
                color: bannerAction.primary || bannerAction.activeFocus
                    || actionHover.hovered ? Theme.washInk : Theme.washMuted
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.letterSpacing: 1.5
                font.capitalization: Font.AllUppercase
            }
        }
        HoverHandler {
            id: actionHover
            cursorShape: Qt.PointingHandCursor
        }
        TapHandler {
            id: actionTap
            onTapped: bannerAction.triggered()
        }
    }

    // Direction A's visual anchor. `portrait-full:` deliberately bypasses the
    // circular artist transform used by Library cards.
    ArchiveWash {
        anchors.fill: parent
        sourceFile: view.roomFile
        veil: 0.60
        fitStrength: 0.0
    }

    Rectangle {
        id: portraitField
        objectName: "artistHero"
        x: view.pageGutter
        y: view.compact ? identityBanner.y + identityBanner.height + view.fieldGap
                        : view.pageTop
        width: view.compact
            ? view.width - view.pageGutter * 2
            : (view.width - view.pageGutter * 2 - view.fieldGap) * 0.455
        height: view.compact
            ? Math.min(286, Math.max(210, view.height * 0.33))
            : view.height - y - view.pageBottom
        color: portrait.status === Image.Ready
               ? "transparent" : Qt.alpha(Theme.washInk, 0.04)
        border.width: portrait.status === Image.Ready ? 0 : 1
        border.color: Theme.washHair
        clip: true

        Image {
            id: portrait
            objectName: "artistHeroPortrait"
            anchors.fill: parent
            source: view.portraitSource
            fillMode: Image.PreserveAspectCrop
            sourceSize: Qt.size(1536, 1536)
            asynchronous: !view.synchronousArtworkPreview
            cache: true
            visible: status === Image.Ready
        }

        // No verified portrait: show one of the artist's own record sleeves
        // rather than a bare initial (Iann, 2026-08-22). It is still THEIR
        // artwork, so the field stays about them; the caption says which.
        Image {
            id: sleeveFallback
            anchors.fill: parent
            visible: portrait.status !== Image.Ready && view.roomFile !== ""
            source: view.roomFile
                    ? "image://art/" + encodeURIComponent(view.roomFile) : ""
            fillMode: Image.PreserveAspectCrop
            sourceSize: Qt.size(1536, 1536)
            asynchronous: !view.synchronousArtworkPreview
            cache: true
        }

        Column {
            anchors.centerIn: parent
            width: Math.max(160, parent.width - 48)
            spacing: 10
            visible: portrait.status !== Image.Ready
                     && sleeveFallback.status !== Image.Ready
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: (view.canonicalName || "?").charAt(0).toUpperCase()
                color: Qt.alpha(Theme.washInk, 0.25)
                font.family: Theme.font
                font.pixelSize: Math.min(132, portraitField.height * 0.34)
                font.weight: Font.ExtraLight
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: portrait.status === Image.Loading
                    ? "READING ARTIST PORTRAIT" : "PORTRAIT NOT FOUND"
                color: Theme.washFaint
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.letterSpacing: 2.4
            }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: Math.min(150, parent.height * 0.24)
            gradient: Gradient {
                GradientStop { position: 0; color: "transparent" }
                GradientStop { position: 1; color: Qt.alpha("#080707", 0.58) }
            }
        }
        Text {
            anchors.left: parent.left
            anchors.leftMargin: 22
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 18
            // The caption never claims a portrait it is not showing.
            text: portrait.status === Image.Ready ? "ARTIST PORTRAIT"
                : sleeveFallback.status === Image.Ready ? "FROM THIS ARTIST'S RECORDS"
                : "ARTIST PORTRAIT"
            color: Qt.alpha(Theme.washInk, 0.72)
            font.family: Theme.displayFont
            font.pixelSize: Theme.washMicro
            font.letterSpacing: 2.6
        }
    }

    // The purple-marked identity treatment: a wide banner at the top of the
    // right field, backed only by faint exact-release color and image traces.
    Rectangle {
        id: identityBanner
        objectName: "artistIdentityBanner"
        x: view.compact ? view.pageGutter
                        : portraitField.x + portraitField.width + view.fieldGap
        y: view.pageTop
        width: view.width - x - view.pageGutter
        height: view.compact ? 202 : Math.min(238, view.height * 0.285)
        color: "transparent"
        border.width: 0
        clip: true

        // The decorative cover strip that used to sit here at 0.105 opacity
        // read as smudges behind the artist's name; the room already carries
        // the record (Album View grammar, 2026-08-22).

        Text {
            id: identityEyebrow
            anchors.left: parent.left
            anchors.leftMargin: 24
            anchors.top: parent.top
            anchors.topMargin: 18
            text: "ARTIST ARCHIVE"
            color: Theme.primary
            font.family: Theme.displayFont
            font.pixelSize: Theme.washMicro
            font.letterSpacing: 2.8
        }
        Text {
            id: artistTitle
            objectName: "artistBannerTitle"
            anchors.left: parent.left
            anchors.leftMargin: 24
            anchors.right: parent.right
            anchors.rightMargin: 24
            anchors.top: identityEyebrow.bottom
            anchors.topMargin: 3
            height: view.compact ? 50 : 67
            text: view.canonicalName
            color: Theme.washInk
            font.family: Theme.font
            font.pixelSize: view.compact ? 42 : 62
            font.weight: Font.ExtraLight
            // Keep tracking independent of Text.Fit's measured result. Feeding
            // the fitted pixel size back here creates a sizing loop.
            font.letterSpacing: -(view.compact ? 42 : 62) * 0.035
            fontSizeMode: Text.Fit
            minimumPixelSize: 28
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }
        Text {
            id: identityCounts
            anchors.left: artistTitle.left
            anchors.top: artistTitle.bottom
            anchors.topMargin: 1
            text: view.albumCount + (view.albumCount === 1 ? " RELEASE" : " RELEASES")
                  + "  ·  " + view.songCount + (view.songCount === 1 ? " SONG" : " SONGS")
            color: Theme.washFaint
            font.family: Theme.displayFont
            font.pixelSize: Theme.washMicro
            font.letterSpacing: 2.2
        }
        Text {
            id: biography
            objectName: "artistBiography"
            anchors.left: artistTitle.left
            anchors.right: parent.right
            anchors.rightMargin: 24
            anchors.top: identityCounts.bottom
            anchors.topMargin: 9
            text: view.bio.bio || (view.bio.found === false
                ? "No verified artist biography was found."
                : "Reading the artist archive…")
            // The banner is a fixed height with the actions pinned beneath
            // it; five lines ran straight through them. Three is the most it
            // can carry and still leave the actions reachable.
            maximumLineCount: view.compact ? 2 : 3
            elide: Text.ElideRight
            wrapMode: Text.Wrap
            color: view.bio.found === false ? Theme.washFaint : Theme.washMuted
            font.family: Theme.font
            font.pixelSize: view.compact ? 13 : 14
            font.weight: Font.Light
            lineHeight: 1.28
        }

        Row {
            id: bannerActions
            anchors.left: parent.left
            anchors.leftMargin: 14
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 5
            spacing: 2
            BannerAction {
                objectName: "artistQueueAll"
                iconName: "playlist"
                labelText: "Queue"
                onTriggered: backend.queueFiles(view.artistFiles)
            }
            BannerAction {
                objectName: "artistShuffleAll"
                iconName: "shuffle"
                labelText: "Shuffle"
                onTriggered: backend.playFilesShuffled(view.artistFiles)
            }
            BannerAction {
                objectName: "artistPlayAll"
                iconName: "play"
                labelText: "Play all"
                primary: true
                onTriggered: backend.playFiles(view.artistFiles, 0)
            }
        }
        Text {
            id: wikipediaLink
            objectName: "artistWikipediaLink"
            anchors.right: parent.right
            anchors.rightMargin: 22
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 17
            visible: (view.bio.url || "") !== "" && !view.compact
            activeFocusOnTab: visible
            Accessible.role: Accessible.Link
            Accessible.name: "Open " + view.canonicalName + " on Wikipedia"
            Accessible.onPressAction: Qt.openUrlExternally(view.bio.url)
            text: "WIKIPEDIA  ↗"
            color: activeFocus ? Theme.primary : Theme.washMuted
            font.family: Theme.displayFont
            font.pixelSize: Theme.washMicro
            font.letterSpacing: 1.8
            HoverHandler { cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: Qt.openUrlExternally(view.bio.url) }
            Keys.onReturnPressed: Qt.openUrlExternally(view.bio.url)
            Keys.onSpacePressed: Qt.openUrlExternally(view.bio.url)
        }
    }

    Item {
        id: catalogTools
        objectName: "artistCatalogTools"
        x: identityBanner.x
        y: view.compact ? portraitField.y + portraitField.height + 10
                        : identityBanner.y + identityBanner.height + 10
        width: identityBanner.width
        height: 44

        TextField {
            id: catalogSearch
            objectName: "artistCatalogSearch"
            anchors.left: parent.left
            anchors.right: sortPicker.left
            anchors.rightMargin: 24
            anchors.verticalCenter: parent.verticalCenter
            height: 30
            leftPadding: 0
            rightPadding: 0
            topPadding: 0
            bottomPadding: 0
            background: null
            color: Theme.washInk
            placeholderText: "SEARCH THIS ARTIST"
            placeholderTextColor: Theme.washFaint
            selectionColor: Qt.alpha(Theme.primary, 0.28)
            selectedTextColor: Theme.washInk
            font.family: Theme.displayFont
            font.pixelSize: Theme.washMicro
            font.letterSpacing: 1.8
            selectByMouse: true
            inputMethodHints: Qt.ImhNoPredictiveText
            Accessible.name: "Search " + view.canonicalName + " releases and tracks"
            onTextChanged: view.filterQuery = text
            Keys.onEscapePressed: {
                text = ""
                focus = false
            }
        }

        Item {
            id: sortPicker
            objectName: "artistSortPicker"
            anchors.right: sortDirection.left
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            width: view.compact ? 146 : 168
            height: 30
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: "Sort by " + view.sortLabel()
            Accessible.description: "Choose the artist catalog sort field"
            Accessible.onPressAction: sortPicker.openMenu()
            Keys.onReturnPressed: openMenu()
            Keys.onEnterPressed: openMenu()
            Keys.onSpacePressed: openMenu()

            function openMenu() {
                sortMenu.popupAt(sortPicker,
                    sortPicker.width - sortMenu.width, sortPicker.height + 6)
            }

            Rectangle {
                anchors.fill: parent
                color: sortTap.pressed
                    ? Qt.alpha(Theme.primary, 0.14)
                    : sortHover.hovered ? Theme.hoverSurface : "transparent"
                border.width: sortPicker.activeFocus ? 1 : 0
                border.color: Theme.focusRing
            }
            Row {
                anchors.left: parent.left
                anchors.leftMargin: 8
                anchors.right: parent.right
                anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                spacing: 7
                Text {
                    width: parent.width - 18
                    text: view.sortLabel()
                    elide: Text.ElideRight
                    color: sortPicker.activeFocus || sortHover.hovered
                        ? Theme.washInk : Theme.washFaint
                    font.family: Theme.displayFont
                    font.pixelSize: Theme.washMicro
                    font.letterSpacing: 1.8
                    font.capitalization: Font.AllUppercase
                    anchors.verticalCenter: parent.verticalCenter
                }
                Icon {
                    name: "chevron-down"
                    size: 10
                    color: sortPicker.activeFocus || sortHover.hovered
                        ? Theme.washInk : Theme.washFaint
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
            HoverHandler {
                id: sortHover
                cursorShape: Qt.PointingHandCursor
            }
            TapHandler {
                id: sortTap
                onTapped: sortPicker.openMenu()
            }
            ArchiveMenu {
                id: sortMenu
                selectedId: view.sortKey
                options: view.sortOptions
                onPicked: id => view.chooseSort(id)
            }
        }

        Item {
            id: sortDirection
            objectName: "artistSortDirection"
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: 44
            height: 44
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: "Sort " + view.sortDirectionName()
            Accessible.description: "Reverse the current artist catalog sort order"
            Accessible.onPressAction: view.toggleSortDirection()
            Keys.onReturnPressed: view.toggleSortDirection()
            Keys.onEnterPressed: view.toggleSortDirection()
            Keys.onSpacePressed: view.toggleSortDirection()
            Rectangle {
                anchors.fill: parent
                color: directionTap.pressed
                    ? Qt.alpha(Theme.primary, 0.14)
                    : directionHover.hovered ? Theme.hoverSurface : "transparent"
                border.width: sortDirection.activeFocus ? 1 : 0
                border.color: Theme.focusRing
            }
            Icon {
                anchors.centerIn: parent
                name: "arrow-up"
                size: 13
                rotation: view.sortDescending ? 180 : 0
                color: sortDirection.activeFocus || directionHover.hovered
                    ? Theme.washInk : Theme.washFaint
                Behavior on rotation {
                    NumberAnimation { duration: Theme.motionFast }
                }
            }
            HoverHandler {
                id: directionHover
                cursorShape: Qt.PointingHandCursor
            }
            TapHandler {
                id: directionTap
                onTapped: view.toggleSortDirection()
            }
        }
    }

    ArchiveLoading {
        visible: !backend.libraryReady
        x: catalog.x
        y: catalog.y
        count: backend.libraryTotalSongs
    }

    ListView {
        id: catalog
        objectName: "artistCatalog"
        visible: backend.libraryReady
        x: view.compact ? view.pageGutter : identityBanner.x
        y: catalogTools.y + catalogTools.height + 4
        width: view.width - x - view.pageGutter
        height: Math.max(0, view.height - y - view.pageBottom)
        clip: true
        spacing: 12
        cacheBuffer: 1800
        boundsBehavior: Flickable.StopAtBounds
        model: view.visibleDisco
        ScrollBar.vertical: ArchiveScrollBar {}
        footer: Item { width: 1; height: 28 }

        delegate: Item {
            id: albumBlock
            required property var modelData
            required property int index
            objectName: "artistAlbumBlock" + index
            width: catalog.width
            readonly property var files: view.albumFiles(modelData)
            readonly property real artSize: view.compact
                ? Math.min(190, width * 0.34)
                : Math.min(258, Math.max(208, width * 0.30))
            readonly property real detailX: artSize + (view.compact ? 18 : 26)
            readonly property real detailWidth: Math.max(0, width - detailX)
            readonly property real trackTop: 96
            height: Math.max(artSize + 24,
                             trackTop + modelData.tracks.length * 44 + 24)
            clip: true

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 1
                color: Theme.washHair
            }
            MediaArtwork {
                id: releaseArt
                objectName: "artistReleaseArt" + albumBlock.index
                x: 0
                y: 12
                width: albumBlock.artSize
                height: albumBlock.artSize
                kind: "album"
                asynchronousLoading: !view.synchronousArtworkPreview
                source: albumBlock.files.length
                    ? "image://art/" + encodeURIComponent(albumBlock.files[0]) : ""
            }
            Text {
                x: albumBlock.detailX
                y: 15
                width: albumBlock.detailWidth - releasePlay.width - 14
                text: (view.releaseYear(albumBlock.modelData)
                      ? view.releaseYear(albumBlock.modelData) + "  ·  " : "")
                      + "ALBUM"
                color: Theme.primary
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.letterSpacing: 2.3
            }
            Text {
                id: releaseTitle
                x: albumBlock.detailX
                y: 33
                width: albumBlock.detailWidth - releasePlay.width - 14
                height: 32
                text: albumBlock.modelData.album || "Singles & loose tracks"
                color: activeFocus || releaseTitleHover.hovered
                    ? Theme.primary : Theme.washInk
                font.family: Theme.font
                font.pixelSize: view.compact ? 20 : 25
                font.weight: Font.Light
                elide: Text.ElideRight
                activeFocusOnTab: true
                Accessible.role: Accessible.Button
                Accessible.name: "Open album "
                    + (albumBlock.modelData.album || "Singles and loose tracks")
                Accessible.onPressAction: view.openAlbum(
                    view.albumDirectory(albumBlock.modelData), albumBlock.modelData.album)
                HoverHandler {
                    id: releaseTitleHover
                    cursorShape: Qt.PointingHandCursor
                }
                TapHandler {
                    onTapped: view.openAlbum(
                        view.albumDirectory(albumBlock.modelData), albumBlock.modelData.album)
                }
                Keys.onReturnPressed: view.openAlbum(
                    view.albumDirectory(albumBlock.modelData), albumBlock.modelData.album)
                Keys.onSpacePressed: view.openAlbum(
                    view.albumDirectory(albumBlock.modelData), albumBlock.modelData.album)
            }
            Text {
                x: albumBlock.detailX
                y: 68
                text: albumBlock.files.length + (albumBlock.files.length === 1
                    ? " TRACK" : " TRACKS")
                    + (albumBlock.modelData.plays > 0
                       ? "  ·  " + albumBlock.modelData.plays + " PLAYS" : "")
                color: Theme.washFaint
                font.family: Theme.displayFont
                font.pixelSize: Theme.washMicro
                font.letterSpacing: 1.8
            }
            GlowButton {
                id: releasePlay
                objectName: "artistReleasePlay" + albumBlock.index
                anchors.top: parent.top
                anchors.topMargin: 18
                anchors.right: parent.right
                anchors.rightMargin: 18
                width: 44
                height: 44
                visible: albumBlock.y + albumBlock.height > catalog.contentY
                         && albumBlock.y < catalog.contentY + catalog.height
                icon: "play"
                tip: "Play this release"
                onClicked: backend.playFiles(albumBlock.files, 0)
            }
            Column {
                x: albumBlock.detailX
                y: albumBlock.trackTop
                width: Math.max(0, albumBlock.detailWidth - 24)
                Repeater {
                    model: albumBlock.modelData.tracks
                    delegate: TrackRow {
                        required property var modelData
                        required property int index
                        objectName: "artistTrack" + albumBlock.index + "-" + index
                        width: parent.width
                        trackData: modelData
                        fileList: albumBlock.files
                        rowIndex: index
                        albumMode: true
                        showArtist: false
                        subText: view.credit(modelData)
                    }
                }
            }
        }

        Text {
            anchors.centerIn: parent
            visible: view.visibleDisco.length === 0
            text: view.filterQuery.trim() !== "" ? "NO MATCHING MEDIA"
                  : view.artistName ? "NO RELEASES FOUND" : "ARTIST NOT FOUND"
            color: Theme.washFaint
            font.family: Theme.displayFont
            font.pixelSize: Theme.washMicro
            font.letterSpacing: 2.6
        }
    }
}
