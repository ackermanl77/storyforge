"""StoryForgeApp.show_update: la versión nueva se avisa y abre la página de descarga solo con Sí."""
from unittest.mock import MagicMock, patch

import pytest

from app import gui
from app.update_check import UpdateInfo


@pytest.mark.parametrize("answer", [True, False])
def test_update_notice_opens_the_download_page_only_on_yes(answer):
    info = UpdateInfo("9.0.0", "https://example.com/get", "Escenas más largas")
    with patch.object(gui.messagebox, "askyesno", return_value=answer) as ask, \
            patch.object(gui.webbrowser, "open") as open_page:
        gui.StoryForgeApp.show_update(MagicMock(), info)
    assert "9.0.0" in ask.call_args.args[1] and "Escenas más largas" in ask.call_args.args[1]
    assert open_page.called is answer
