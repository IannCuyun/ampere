import "../../qml"
import QtQuick
import QtTest

TestCase {
    name: "MediaArtworkFallback"
    when: windowShown
    width: 200
    height: 120

    function test_folderUsesDrawnFallbackWhenProviderHasNoArt() {
        folder.source = "image://missing/folder:Artless/track.flac";
        tryCompare(folder, "fallbackVisible", true);
    }

    function test_emptySourceUsesSemanticFallback() {
        folder.source = "";
        compare(folder.fallbackVisible, true);
    }

    function test_artistLibraryArtUsesRealProviderCircle() {
        artist.source = "image://art/Artists/Kanye/cover.flac";
        compare(artist.resolvedSource.toString(),
                "image://art/round:Artists/Kanye/cover.flac");
        artist.source = "image://art/portrait:012345";
        compare(artist.resolvedSource.toString(),
                "image://art/portrait:012345");
        album.source = "image://art/Albums/808s/cover.flac";
        compare(album.resolvedSource.toString(),
                "image://art/Albums/808s/cover.flac");
    }

    function test_albumDefaultUsesDprAwareHighQualityDecodeTier() {
        album.width = 300;
        album.height = 300;
        verify(album.automaticDecodeSize >= 512);
        verify(album.automaticDecodeSize <= 1536);
    }

    MediaArtwork {
        id: folder
        width: 44
        height: 44
        kind: "folder"
    }

    MediaArtwork {
        id: artist
        width: 44
        height: 44
        kind: "artist"
    }

    MediaArtwork {
        id: album
        width: 44
        height: 44
        kind: "album"
    }
}
