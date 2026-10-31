import os
from unittest.mock import patch

from ampere.main import _configure_quick_runtime


def test_quick_runtime_uses_threaded_scene_graph_by_default():
    with patch.dict(os.environ, {}, clear=True):
        _configure_quick_runtime()

        assert os.environ["QT_QUICK_CONTROLS_STYLE"] == "Basic"
        assert os.environ["QSG_RENDER_LOOP"] == "threaded"


def test_quick_runtime_preserves_explicit_render_loop_override():
    with patch.dict(os.environ, {"QSG_RENDER_LOOP": "basic"}, clear=True):
        _configure_quick_runtime()

        assert os.environ["QSG_RENDER_LOOP"] == "basic"
