import QtQuick
import QtTest
import "../../qml"

TestCase {
    id: testCase
    name: "AccessibleNavigationBehavior"
    when: windowShown
    visible: true
    width: 900
    height: 640

    property string navigatedMode: ""
    property string pickedId: ""

    WhisperRail {
        id: rail
        anchors.fill: parent
        onNavigate: mode => testCase.navigatedMode = mode
    }

    SignalSpy {
        id: backSpy
        target: rail
        signalName: "navigateBack"
    }

    SignalSpy {
        id: forwardSpy
        target: rail
        signalName: "navigateForward"
    }

    ArchiveMenu {
        id: menu
        options: [
            { id: "artist", label: "Artist" },
            { id: "year", label: "Year" },
            { id: "plays", label: "Plays" }
        ]
        onPicked: id => testCase.pickedId = id
    }

    function init() {
        navigatedMode = ""
        pickedId = ""
        testCase.width = 900
        testCase.height = 640
        rail.currentMode = "home"
        rail.searchOpen = false
        rail.canGoBack = false
        rail.canGoForward = false
        backSpy.clear()
        forwardSpy.clear()
        if (menu.opened) menu.close()
        if (rail.menuOpen) rail.closeMenu()
        wait(0)
    }

    function test_visibleHistoryControlsDispatchAvailableDirections() {
        testCase.width = 720
        rail.canGoBack = true
        rail.canGoForward = false
        wait(0)

        var controls = findChild(rail, "historyControls")
        var back = findChild(rail, "historyBackButton")
        var forward = findChild(rail, "historyForwardButton")
        verify(controls !== null)
        verify(back !== null)
        verify(forward !== null)
        verify(controls.visible)
        verify(back.enabled)
        verify(!forward.enabled)
        verify(back.width >= 44 && back.height >= 44)
        verify(forward.width >= 44 && forward.height >= 44)

        var origin = controls.mapToItem(rail, 0, 0)
        verify(origin.x >= 0)
        verify(origin.x + controls.width <= rail.width)

        back.forceActiveFocus()
        tryCompare(back, "activeFocus", true)
        keyClick(Qt.Key_Return)
        compare(backSpy.count, 1)
        compare(forwardSpy.count, 0)

        rail.canGoForward = true
        forward.forceActiveFocus()
        tryCompare(forward, "activeFocus", true)
        keyClick(Qt.Key_Space)
        compare(forwardSpy.count, 1)
    }

    function test_archiveMenuSelectsHighlightedOptionByKeyboard() {
        menu.popupAt(testCase, 20, 20)
        tryVerify(function() { return menu.opened })
        compare(menu.currentIndex, 0)

        keyClick(Qt.Key_Down)
        compare(menu.currentIndex, 1)
        keyClick(Qt.Key_Space)

        compare(pickedId, "year")
        verify(!menu.opened)
    }

    function test_desktopDestinationsAreVisibleAndKeyboardActivatable() {
        // rail anchors.fill's its parent, so resize the TestCase itself
        // rather than fighting the anchor with a direct rail.width write.
        testCase.width = 1200
        wait(0)

        var home = findChild(rail, "homeButton")
        verify(home !== null)
        verify(home.activeFocusOnTab)
        verify(home.width >= 44 && home.height >= 44)
        home.forceActiveFocus()
        tryCompare(home, "activeFocus", true)
        keyClick(Qt.Key_Return)
        compare(navigatedMode, "home")

        rail.currentMode = "home"
        wait(0)
        var row = findChild(rail, "destinationRow")
        var controls = findChild(rail, "historyControls")
        verify(row !== null)
        verify(controls !== null)
        verify(row.visible)

        var libraryDest = findChild(rail, "dest-library")
        var featuresDest = findChild(rail, "dest-features")
        verify(libraryDest !== null)
        verify(featuresDest !== null)
        verify(libraryDest.width >= 44 && libraryDest.height >= 44)
        verify(featuresDest.width >= 44 && featuresDest.height >= 44)
        verify(findChild(rail, "dest-home") === null)
        verify(findChild(rail, "dest-now") === null)

        var homeOrigin = home.mapToItem(rail, 0, 0)
        var libraryOrigin = row.mapToItem(rail, 0, 0)
        var historyOrigin = controls.mapToItem(rail, 0, 0)
        verify(libraryOrigin.x >= homeOrigin.x + home.width)
        var featuresOrigin = featuresDest.mapToItem(rail, 0, 0)
        verify(featuresOrigin.x >= libraryOrigin.x + libraryDest.width)
        verify(historyOrigin.x >= libraryOrigin.x + row.width)

        rail.currentMode = "browse"
        wait(0)
        verify(row.visible)
        verify(libraryDest.current)

        libraryDest.forceActiveFocus()
        tryCompare(libraryDest, "activeFocus", true)
        keyClick(Qt.Key_Return)
        compare(navigatedMode, "library")

        rail.currentMode = "features"
        wait(0)
        verify(featuresDest.current)
        featuresDest.forceActiveFocus()
        tryCompare(featuresDest, "activeFocus", true)
        keyClick(Qt.Key_Space)
        compare(navigatedMode, "features")
    }

    function test_tallDesktopHeaderKeepsOneRaisedTopBand() {
        testCase.width = 1200
        testCase.height = 1080
        wait(0)

        rail.currentMode = "home"
        wait(0)
        var home = findChild(rail, "homeButton")
        var controls = findChild(rail, "historyControls")
        var destinations = findChild(rail, "destinationRow")
        verify(home !== null)
        verify(controls !== null)
        verify(destinations !== null)
        compare(home.y, 16)
        compare(controls.y, 16)
        compare(destinations.y, 16)
        verify(destinations.x >= home.x + home.width)
        verify(controls.x >= destinations.x + destinations.width)
        verify(controls.y + controls.height <= 60)
    }

    function test_compactKeepsLibraryBeforeHistoryAndSettingsUtilityOnly() {
        rail.currentMode = "browse"
        testCase.width = 720
        wait(0)

        var row = findChild(rail, "destinationRow")
        var home = findChild(rail, "homeButton")
        var controls = findChild(rail, "historyControls")
        verify(row !== null)
        verify(home !== null && controls !== null)
        verify(row.visible)
        verify(row.x >= home.x + home.width)
        verify(controls.x >= row.x + row.width)
        verify(controls.x + controls.width <= rail.width)

        var searchButton = findChild(rail, "searchButton")
        var settingsButton = findChild(rail, "settingsButton")
        verify(searchButton !== null && settingsButton !== null)
        verify(searchButton.width >= 44 && searchButton.height >= 44)
        verify(settingsButton.width >= 44 && settingsButton.height >= 44)

        rail.openMenu()
        verify(rail.menuOpen)
        var utilityMenu = findChild(rail, "utilityMenu")
        verify(utilityMenu !== null)
        compare(utilityMenu.options.length, 4)
        var ids = utilityMenu.options.map(function (o) { return o.id })
        compare(ids.join(","), "disliked,doctor,eq,settings")
        compare(utilityMenu.options[0].label, "Out of Rotation")
        rail.closeMenu()

        rail.currentMode = "ampy"
        wait(0)
        verify(row.visible)
        verify(findChild(rail, "dest-library") !== null)

        rail.searchOpen = true
        wait(0)
        verify(!row.visible)
        compare(controls.x, home.x + home.width + 8)
    }
}
