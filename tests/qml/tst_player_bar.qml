import "../../qml"
import QtQuick
import QtTest

TestCase {
    id: testCase
    name: "PlayerBarCompactBehavior"
    when: windowShown
    visible: true
    width: 1280
    height: 180

    property var backend: provider

    QtObject {
        id: provider
        property var artColors: []
        property var currentSong: ({
            file: "Rap/Kanye West/808s & Heartbreak/04 Heartless.flac",
            title: "Heartless",
            artist: "Kanye West",
            album: "808s & Heartbreak"
        })
        property var likedFiles: []
        property var dislikedFiles: []
        property real elapsed: 80
        property real duration: 211
        property int volume: 89
        property string state: "play"
        property bool repeat: false
        property bool single: false
        property bool autoplayOn: false
        property string contextShuffleMode: "off"
        property var seeks: []
        property var shuffleContexts: []
        property var likedCalls: []
        property var dislikedCalls: []

        function artistPath() { return "Rap/Kanye West" }
        function requestSeek(seconds) { seeks = seeks.concat([seconds]) }
        function requestVolume() {}
        function requestPlayPause() {}
        function requestPrevious() {}
        function requestNext() {}
        function cycleContextShuffle(context) { shuffleContexts = shuffleContexts.concat([context]) }
        function requestCycleRepeat() {}
        function toggleLike(file) { likedCalls = likedCalls.concat([file]) }
        function toggleDislike(file) { dislikedCalls = dislikedCalls.concat([file]) }
    }

    PlayerBar {
        id: player
        parent: testCase
        width: 1280
        height: 96
        anchors.bottom: parent.bottom
    }

    function init() {
        provider.seeks = []
        provider.likedFiles = []
        provider.dislikedFiles = []
        provider.likedCalls = []
        provider.dislikedCalls = []
        provider.repeat = false
        provider.single = false
        player.width = 1280
        wait(50)
    }

    function test_loopOneUsesNumberOneAndStateCopy() {
        const loop = findChild(player, "playerLoopControl")
        const badge = findChild(player, "playerLoopControlBadge")
        verify(loop !== null)
        verify(badge !== null)
        verify(!loop.active)
        verify(!badge.visible)
        compare(loop.Accessible.name, "Loop off")

        provider.repeat = true
        tryCompare(loop, "active", true)
        compare(loop.Accessible.name, "Loop current queue")
        verify(!badge.visible)

        provider.single = true
        tryCompare(badge, "visible", true)
        compare(badge.text, "1")
        compare(loop.Accessible.name, "Repeat current song")
        compare(loop.width, 44)
        compare(loop.height, 44)
    }

    function verifyZonesContained(width) {
        player.width = width
        wait(50)
        const identity = findChild(player, "playerIdentityZone")
        const transport = findChild(player, "playerTransportZone")
        const utilities = findChild(player, "playerUtilityZone")
        verify(identity !== null)
        verify(transport !== null)
        verify(utilities !== null)
        for (const zone of [identity, transport, utilities]) {
            const origin = zone.mapToItem(player, 0, 0)
            verify(origin.x >= -0.5)
            verify(origin.x + zone.width <= player.width + 0.5,
                   zone.objectName + " right=" + (origin.x + zone.width)
                   + " player=" + player.width)
            verify(zone.width > 0)
        }
        verify(identity.mapToItem(player, 0, 0).x
               < transport.mapToItem(player, 0, 0).x)
        verify(transport.mapToItem(player, 0, 0).x
               < utilities.mapToItem(player, 0, 0).x)
    }

    function centerX(item) {
        return item.mapToItem(player, 0, 0).x + item.width / 2
    }

    function verifyPlayCentered(width) {
        player.width = width
        wait(50)
        const play = findChild(player, "playerPlayControl")
        const identity = findChild(player, "playerIdentityZone")
        const utilities = findChild(player, "playerUtilityZone")
        const shuffle = findChild(player, "contextShuffleControl")
        const next = findChild(player, "playerNextControl")
        const like = findChild(player, "playerLikeControl")
        const dislike = findChild(player, "playerDislikeControl")
        verify(play !== null)
        verify(identity !== null)
        verify(utilities !== null)
        verify(shuffle !== null)
        verify(next !== null)
        fuzzyCompare(centerX(play), width / 2, 0.5)
        verifyZonesContained(width)
        const identityOrigin = identity.mapToItem(player, 0, 0)
        const utilitiesOrigin = utilities.mapToItem(player, 0, 0)
        const leftEdge = (like.visible ? like : shuffle).mapToItem(
            player, 0, 0).x
        const rightControl = dislike.visible ? dislike : next
        const rightOrigin = rightControl.mapToItem(player, 0, 0)
        verify(identityOrigin.x + identity.width <= leftEdge + 0.5)
        verify(rightOrigin.x + rightControl.width
               <= utilitiesOrigin.x + 0.5)
    }

    function test_pocketHorizonContainsThreeZones() {
        compare(Theme.playerHeight, 96)
        verifyPlayCentered(1920)
        verifyPlayCentered(1280)
        verifyPlayCentered(900)
        verifyPlayCentered(560)
    }

    function test_deckUsesTheSameBackgroundAsTheAlbumRoom() {
        compare(player.color, "#00000000")
        verify(!player.gradient || player.gradient.stops.length === 0)
    }

    function test_seekTargetShowsExactDestinationAndSeeksOnRelease() {
        const rail = findChild(player, "playerSeekRail")
        const handle = findChild(player, "playerSeekHandle")
        const target = findChild(player, "playerSeekTarget")
        const preview = findChild(player, "playerSeekPreview")
        verify(rail !== null)
        verify(handle !== null)
        verify(target !== null)
        verify(preview !== null)
        verify(handle.visible)

        rail.forceActiveFocus()
        tryVerify(function() { return target.visible && preview.visible })
        compare(rail.targetFraction, rail.fraction)

        mouseMove(rail, rail.width * 0.75, rail.height / 2)
        tryVerify(function() { return target.visible && preview.visible })
        fuzzyCompare(rail.targetFraction, 0.75, 0.02)

        mousePress(rail, rail.width * 0.75, rail.height / 2,
                   Qt.LeftButton)
        mouseRelease(rail, rail.width * 0.75, rail.height / 2,
                     Qt.LeftButton)
        compare(provider.seeks.length, 1)
        fuzzyCompare(provider.seeks[0], provider.duration * 0.75, 1.0)
    }

    function test_contextShuffleUsesShared44pxStateVisual() {
        const control = findChild(player, "contextShuffleControl")
        verify(control !== null)
        compare(control.width, 44)
        compare(control.height, 44)
        compare(control.icon, "shuffle")
        verify(!control.active)
        provider.contextShuffleMode = "standard"
        tryCompare(control, "active", true)
        compare(control.icon, "shuffle")
        provider.contextShuffleMode = "smart"
        tryCompare(control, "icon", "smart-shuffle")
        verify(control.active)
        mouseClick(control, control.width / 2, control.height / 2,
                   Qt.LeftButton)
        compare(provider.shuffleContexts.length, 1)
        verify(control.Accessible.name.indexOf("next:") >= 0)
    }

    function test_desktopTastePairUses44pxMutuallyReadableStates() {
        const like = findChild(player, "playerLikeControl")
        const dislike = findChild(player, "playerDislikeControl")
        verify(like !== null)
        verify(dislike !== null)
        verify(like.visible)
        verify(dislike.visible)
        compare(like.width, 44)
        compare(like.height, 44)
        compare(dislike.width, 44)
        compare(dislike.height, 44)
        verify(like.Accessible.name.indexOf("Like") >= 0)
        verify(dislike.Accessible.name.indexOf("Dislike") >= 0)
        const shuffle = findChild(player, "contextShuffleControl")
        const previous = findChild(player, "playerPreviousControl")
        const play = findChild(player, "playerPlayControl")
        const next = findChild(player, "playerNextControl")
        const loop = findChild(player, "playerLoopControl")
        verify(shuffle !== null)
        verify(previous !== null)
        verify(play !== null)
        verify(next !== null)
        verify(loop !== null)
        verify(centerX(like) < centerX(shuffle),
               "like=" + centerX(like) + " shuffle=" + centerX(shuffle))
        verify(centerX(shuffle) < centerX(previous))
        verify(centerX(previous) < centerX(play))
        verify(centerX(play) < centerX(next))
        verify(centerX(next) < centerX(loop))
        verify(centerX(loop) < centerX(dislike))
        fuzzyCompare(centerX(play), player.width / 2, 0.5)

        provider.likedFiles = [provider.currentSong.file]
        tryCompare(like, "active", true)
        verify(!dislike.active)
        provider.likedFiles = []
        provider.dislikedFiles = [provider.currentSong.file]
        tryCompare(dislike, "active", true)
        verify(!like.active)

        mouseClick(like, like.width / 2, like.height / 2, Qt.LeftButton)
        mouseClick(dislike, dislike.width / 2, dislike.height / 2,
                   Qt.LeftButton)
        const likeOrigin = like.mapToItem(player, 0, 0)
        const dislikeOrigin = dislike.mapToItem(player, 0, 0)
        compare(provider.likedCalls.length, 1,
                "Like click at " + likeOrigin.x + "," + likeOrigin.y)
        compare(provider.dislikedCalls.length, 1,
                "Dislike click at " + dislikeOrigin.x + ","
                + dislikeOrigin.y)
        compare(provider.likedCalls[0], provider.currentSong.file)
        compare(provider.dislikedCalls[0], provider.currentSong.file)
    }

    function test_compactTastePairStaysOutOfPocketHorizon() {
        player.width = 560
        wait(50)
        const like = findChild(player, "playerLikeControl")
        const dislike = findChild(player, "playerDislikeControl")
        verify(like !== null)
        verify(dislike !== null)
        verify(!like.visible)
        verify(!dislike.visible)
        verifyZonesContained(560)
    }
}
