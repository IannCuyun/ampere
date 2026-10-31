import QtQuick
import QtQuick.Window
import "."

// Semantic artwork primitive. Shape communicates media type everywhere:
// artists are circular; albums, songs, and folders are square with hard
// corners. Folder art is representative media, never a new shape category.
Rectangle {
    id: artwork
    property url source: ""
    property string kind: "album" // album | song | artist | folder
    property int fillMode: Image.PreserveAspectCrop
    property color fallbackColor: Theme.planeRaised
    // Test/render harness seam only. Production remains asynchronous; an
    // inert Python image provider can opt out to avoid crossing the GIL from
    // Qt's image worker while capturing a deterministic verification frame.
    property bool asynchronousLoading: true
    // Optional explicit decode bound. Otherwise every album image uses the
    // provider's highest-resolution verified source and a DPR-aware tier: the
    // source stays crisp without decoding a 1536px raster for every tiny row.
    property int decodeSize: 0
    readonly property bool isArtist: kind === "artist"
    // A rounded Rectangle does not mask child Images in Qt Quick: clip is
    // still rectangular. Route artist library art through the provider's
    // real alpha-circle transform; portrait: keys are already alpha-masked.
    readonly property url resolvedSource: {
        var raw = artwork.source.toString();
        var prefix = "image://art/";
        if (!artwork.isArtist || raw.indexOf(prefix) !== 0)
            return artwork.source;
        var key = raw.substring(prefix.length);
        if (key.indexOf("portrait:") === 0 || key.indexOf("round:") === 0)
            return artwork.source;
        return prefix + "round:" + key;
    }
    readonly property bool fallbackVisible: artwork.source.toString() === ""
        || (kind === "folder" && sourceImage.status !== Image.Ready)
    readonly property int automaticDecodeSize: {
        var required = Math.ceil(Math.max(width, height)
                                 * Math.max(1, Screen.devicePixelRatio));
        if (required <= 512)
            return 512;
        if (required <= 1024)
            return 1024;
        return 1536;
    }

    color: fallbackColor
    radius: isArtist ? Math.min(width, height) / 2 : 0
    clip: true

    Image {
        id: sourceImage
        anchors.fill: parent
        source: artwork.resolvedSource
        fillMode: artwork.fillMode
        sourceSize: {
            var side = artwork.decodeSize > 0
                       ? artwork.decodeSize : artwork.automaticDecodeSize;
            return Qt.size(side, side);
        }
        asynchronous: artwork.asynchronousLoading
        cache: true
        visible: status === Image.Ready
    }

    Icon {
        anchors.centerIn: parent
        visible: artwork.fallbackVisible
        name: artwork.isArtist ? "artist" : artwork.kind === "folder" ? "folder" : "disc"
        size: Math.max(14, Math.min(28, Math.min(parent.width, parent.height) * 0.4))
        color: Theme.textSubtle
    }
}
