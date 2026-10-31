import "../../qml"
import QtQuick
import QtTest

TestCase {
    id: testCase
    name: "AmbientGalleryTitleGeometry"
    when: windowShown
    width: 1256
    height: 820

    property var backend: provider

    QtObject {
        id: provider
        property real elapsed: 72
        property bool lyricsSynced: true
        property var artColors: ["#86c6d8", "#df886e"]
        property var currentSong: ({
                file: "Metal/All That Remains/Carry the Fire.flac",
                title: "Carry the Fire",
                artist: "All That Remains",
                album: "Antifragile"
            })
        property var lyrics: [
            {
                t: 38,
                line: "The weight is leaving now"
            },
            {
                t: 70,
                line: "I learned to carry the fire."
            }
        ]
        signal statusChanged
    }

    function init() {
        ambient.width = 1256;
        ambient.height = 820;
        wait(0);
    }

    function geometry() {
        return {
            art: findChild(ambient, "ambientArtwork"),
            lyric: findChild(ambient, "ambientLyricColumn"),
            identity: findChild(ambient, "ambientIdentity")
        };
    }

    function verifyGalleryTitleGeometry(g) {
        verify(g.art !== null);
        verify(g.lyric !== null);
        verify(g.identity !== null);
        compare(g.art.width, g.art.height);
        fuzzyCompare(g.art.x + g.art.width / 2, ambient.width / 2, 0.5);
        fuzzyCompare(g.identity.x + g.identity.width / 2,
                     ambient.width / 2, 0.5);
        verify(g.identity.y >= 0);
        verify(g.identity.y + g.identity.height + 20 <= g.art.y);
        verify(g.lyric.y >= g.art.y + g.art.height + 20);
        verify(g.lyric.y + g.lyric.height <= ambient.height + 0.5);
        compare(findChild(ambient, "ambientFullscreenButton"), null);
    }

    function test_desktopComposition() {
        var g = geometry();
        verifyGalleryTitleGeometry(g);
        verify(g.art.width >= ambient.height * 0.52);
    }

    function test_compactComposition() {
        ambient.width = 680;
        wait(0);
        var g = geometry();
        verifyGalleryTitleGeometry(g);
        verify(g.art.width <= ambient.width * 0.64 + 0.5);
        verify(g.art.width <= ambient.height * 0.38 + 0.5);
    }

    AmbientView {
        id: ambient
        parent: testCase
        width: 1256
        height: 820
        presentationActive: true
    }
}
