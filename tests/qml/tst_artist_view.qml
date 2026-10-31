import "../../qml"
import QtQuick
import QtTest

TestCase {
    id: testCase
    name: "ArtistViewBehavior"
    when: windowShown
    visible: true
    width: 1280
    height: 900

    property var backend: provider

    QtObject {
        id: provider
        property var requestedArtists: []
        property var artColors: []
        property var currentSong: ({})
        property var likedFiles: []
        property var calls: []
        signal artistBioReady(string artist, var info)
        signal artistDiscographyReady(string artist, int serial, var rows)
        signal databaseUpdated()

        function requestArtistDiscography(artist, serial) {
            artistDiscographyReady(artist, serial, artistDiscography(artist))
        }

        function canonicalArtistName(artist) {
            return artist === "Ye" ? "Kanye West" : artist
        }

        function artistDiscography(artist) {
            var path = "Rap/" + artist
            return [
                {
                    album: "808s & Heartbreak",
                    plays: 84,
                    tracks: [
                        {
                            file: path + "/808s/01 Say You Will.flac",
                            title: "Say You Will",
                            artist: "Kanye West",
                            album: "808s & Heartbreak",
                            date: "2008-11-24",
                            duration: 377
                        },
                        {
                            file: path + "/808s/02 Welcome to Heartbreak.flac",
                            title: "Welcome to Heartbreak",
                            artist: "Kanye West",
                            album: "808s & Heartbreak",
                            date: "2008-11-24",
                            duration: 263
                        }
                    ]
                }
            ]
        }

        function requestArtistBio(artist) {
            requestedArtists = requestedArtists.concat([artist])
        }
        function queuePath(path) { calls = calls.concat(["queue:" + path]) }
        function shufflePathNow(path) { calls = calls.concat(["shuffle:" + path]) }
        function playPath(path) { calls = calls.concat(["play:" + path]) }
        function playFiles(files, index) { calls = calls.concat(["files:" + index]) }
        function queueFiles(files) { calls = calls.concat(["queue-files:" + files.length]) }
        function playFilesShuffled(files) { calls = calls.concat(["shuffle-files:" + files.length]) }
        function playAlbum(files, index) { calls = calls.concat(["album:" + index]) }
        function playNext(file) { calls = calls.concat(["next:" + file]) }
        function toggleLike(file) { calls = calls.concat(["like:" + file]) }
        function moreLikeThis(file) { calls = calls.concat(["more:" + file]) }

        function publishBiography() {
            artistBioReady("Kanye West", {
                found: true,
                portrait: "0123456789012345678901234567890123456789",
                url: "https://en.wikipedia.org/wiki/Kanye_West",
                bio: "An American recording artist and producer whose catalog moves between soul sampling, electronic minimalism, gospel, and industrial production."
            })
        }
    }

    ArtistView {
        id: artist
        parent: testCase
        width: 1256
        height: 820
        artistName: "Kanye West"
        artistPath: "Rap/Kanye West"
    }

    function init() {
        provider.requestedArtists = []
        provider.calls = []
        artist.width = 1256
        artist.height = 820
        artist.filterQuery = ""
        artist.sortKey = "plays"
        artist.sortDescending = true
        artist.reload()
        wait(0)
        provider.publishBiography()
        wait(0)
    }

    function test_populatedIdentityUsesFullArtistPortrait() {
        compare(provider.requestedArtists.length, 1)
        compare(provider.requestedArtists[0], "Kanye West")
        compare(artist.albumCount, 1)
        compare(artist.songCount, 2)

        var portrait = findChild(artist, "artistHeroPortrait")
        var banner = findChild(artist, "artistIdentityBanner")
        var title = findChild(artist, "artistBannerTitle")
        var biography = findChild(artist, "artistBiography")
        var wikipedia = findChild(artist, "artistWikipediaLink")
        var queueAll = findChild(artist, "artistQueueAll")
        var shuffleAll = findChild(artist, "artistShuffleAll")
        var playAll = findChild(artist, "artistPlayAll")
        verify(portrait !== null)
        verify(banner !== null)
        verify(title !== null)
        verify(biography !== null)
        verify(wikipedia !== null)
        verify(queueAll !== null)
        verify(shuffleAll !== null)
        verify(playAll !== null)
        compare(portrait.source.toString(),
                "image://art/portrait-full:0123456789012345678901234567890123456789")
        compare(title.text, "Kanye West")
        verify(biography.text.indexOf("recording artist and producer") >= 0)
        verify(wikipedia.visible)
    }

    function test_releasePlayNeverEscapesCatalogViewport() {
        var catalog = findChild(artist, "artistCatalog")
        var releasePlay = findChild(artist, "artistReleasePlay0")
        verify(catalog !== null)
        verify(releasePlay !== null)
        compare(releasePlay.width, 44)
        compare(releasePlay.height, 44)
        verify(releasePlay.visible)
        verify(catalog.clip)
    }

    function test_desktopUsesPortraitLeftBannerAndChaptersRight() {
        artist.width = 1256
        wait(50)
        var hero = findChild(artist, "artistHero")
        var banner = findChild(artist, "artistIdentityBanner")
        var catalog = findChild(artist, "artistCatalog")
        var albumBlock = findChild(artist, "artistAlbumBlock0")
        var releaseArt = findChild(artist, "artistReleaseArt0")
        verify(hero !== null)
        verify(banner !== null)
        verify(catalog !== null)
        verify(albumBlock !== null)
        verify(releaseArt !== null)

        verify(hero.x + hero.width < banner.x)
        fuzzyCompare(banner.x, catalog.x, 0.5)
        fuzzyCompare(banner.width, catalog.width, 0.5)
        verify(catalog.y >= banner.y + banner.height)
        verify(hero.height >= artist.height * 0.75)
        verify(releaseArt.width >= 174)
        compare(albumBlock.width, catalog.width)
        verify(catalog.x + catalog.width <= artist.width + 0.5)
    }

    function test_compactRecomposesIdentityPortraitThenCatalog() {
        artist.width = 680
        wait(50)
        var hero = findChild(artist, "artistHero")
        var banner = findChild(artist, "artistIdentityBanner")
        var catalog = findChild(artist, "artistCatalog")
        var releaseArt = findChild(artist, "artistReleaseArt0")
        verify(hero !== null)
        verify(banner !== null)
        verify(catalog !== null)
        verify(releaseArt !== null)
        fuzzyCompare(hero.x, banner.x, 0.5)
        fuzzyCompare(catalog.x, banner.x, 0.5)
        verify(hero.y >= banner.y + banner.height)
        verify(catalog.y >= hero.y + hero.height)
        fuzzyCompare(hero.width, banner.width, 0.5)
        fuzzyCompare(catalog.width, banner.width, 0.5)
        verify(catalog.x + catalog.width <= artist.width + 0.5)
        verify(catalog.height > 0)
        verify(releaseArt.width >= 150)
    }

    function verifyTrackScrollbarSafeArea(width) {
        artist.width = width
        wait(50)
        var catalog = findChild(artist, "artistCatalog")
        var track = findChild(artist, "artistTrack0-0")
        verify(catalog !== null)
        verify(track !== null)
        verify(track.width > 0)
        var trackOrigin = track.mapToItem(catalog, 0, 0)
        verify(trackOrigin.x + track.width <= catalog.width - 23.5,
               "track right=" + (trackOrigin.x + track.width)
               + " catalog width=" + catalog.width)
    }

    function test_songDurationKeepsScrollbarSafeArea() {
        verifyTrackScrollbarSafeArea(1256)
        verifyTrackScrollbarSafeArea(680)
    }

    function test_catalog_search_sort_and_direction_share_one_projection() {
        artist.disco = [
            {
                album: "Zulu",
                plays: 4,
                tracks: [{ file: "z.flac", title: "Last Signal",
                           artist: "Kanye West", year: "2022", duration: 180 }]
            },
            {
                album: "Alpha",
                plays: 30,
                tracks: [{ file: "a.flac", title: "First Light",
                           artist: "Kanye West", year: "2008", duration: 190 }]
            }
        ]
        wait(0)
        compare(artist.visibleDisco[0].album, "Alpha")

        artist.sortKey = "title"
        artist.sortDescending = false
        wait(0)
        compare(artist.visibleDisco[0].album, "Alpha")
        artist.toggleSortDirection()
        wait(0)
        compare(artist.visibleDisco[0].album, "Zulu")

        artist.filterQuery = "first"
        wait(0)
        compare(artist.visibleDisco.length, 1)
        compare(artist.visibleDisco[0].tracks.length, 1)
        compare(artist.artistFiles.length, 1)
        compare(artist.artistFiles[0], "a.flac")

        verify(findChild(artist, "artistCatalogSearch") !== null)
        verify(findChild(artist, "artistSortPicker") !== null)
        const direction = findChild(artist, "artistSortDirection")
        verify(direction !== null)
        compare(direction.width, 44)
        compare(direction.height, 44)
    }

    function test_loadingAndNotFoundBiographyStatesRemainExplicit() {
        var biography = findChild(artist, "artistBiography")
        verify(biography !== null)
        artist.bio = ({})
        compare(biography.text, "Reading the artist archive…")
        provider.artistBioReady("Kanye West", {found: false})
        compare(biography.text, "No verified artist biography was found.")
        compare(artist.portraitSource, "")
    }
}
