import "../../qml"
import QtQuick
import QtTest
TestCase {
    id: tc
    name: "HomeListeningRows"
    when: windowShown
    width: 1440; height: 804
    property var backend: provider
    QtObject {
        id: provider
        property bool libraryReady: true
        property int libraryTotalSongs: 8
        property var played: []
        signal librarySummaryChanged()
        function requestLibrarySummary() {}
        function playAlbum(files, index) { played = files }
        function homeOverview() { return {ready:true, sections:[{title:"Favorites", cards:[{kind:"song", file:"A/a.flac", path:"A", album:"Album", artist:"Artist", title:"Song", label:"Last month’s favorite song",reason:"Most played · September 2026"}, {kind:"album",file:"B/b.flac",path:"B",album:"Other",artist:"Artist",title:"Other",label:"Unheard",reason:"No recorded plays"}]}],metrics:{week:4}} }
    }
    LandingView { id: page; anchors.fill: parent; active: true }
    SignalSpy { id: albums; target: page; signalName: "openAlbum" }
    function test_song_activation_and_album_navigation_are_distinct() {
        page.reload()
        const cards = page.overview.sections[0].cards
        page.activate(cards[0]); compare(provider.played[0], "A/a.flac")
        albums.clear(); page.activate(cards[1]); compare(albums.count, 1)
        compare(albums.signalArguments[0][0], "B")
        compare(albums.signalArguments[0][1], "Other")
    }
    function test_visible_projection_stays_stable_on_background_update() {
        page.reload(); const old = page.overview
        provider.librarySummaryChanged(); compare(page.overview, old)
    }
    function test_compact_cards_remain_within_view_and_scroll() {
        tc.width = 720; tc.height = 384; wait(0)
        const card = findChild(page, "homeRecommendationCard")
        verify(card !== null); verify(card.width > 250)
        const p = card.mapToItem(page, 0, 0)
        verify(p.x >= 0 && p.x + card.width <= page.width)
        const flick = findChild(page, "homeFlick")
        verify(flick.contentHeight > flick.height)
        card.forceActiveFocus(); wait(0); verify(card.activeFocus)
        tc.width = 1440; tc.height = 804
    }
}
