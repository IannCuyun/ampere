from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_waveform_canvases_use_qt6_supported_threaded_image_rendering():
    source = (ROOT / "qml" / "WaveSeek.qml").read_text()

    assert source.count("renderTarget: Canvas.Image") == 2
    assert source.count("renderStrategy: Canvas.Threaded") == 2
    assert "Canvas.FramebufferObject" not in source
    assert "Canvas.Cooperative" not in source


def test_waveform_defers_framebuffer_rebuilds_during_native_resize():
    source = (ROOT / "qml" / "WaveSeek.qml").read_text()
    gallery = (ROOT / "qml" / "GalleryNowPlayingView.qml").read_text()

    assert "property bool resizeActive: false" in source
    assert "onResizeActiveChanged: if (!resizeActive) scheduleRebuild()" in source
    assert source.count("visible: !ws.resizeActive") == 2
    assert "visible: ws.resizeActive" in source
    assert "resizeActive: view.windowGeometryChanging" in gallery
