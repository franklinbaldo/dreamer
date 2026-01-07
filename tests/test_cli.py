from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from src.dreamer.cli import app
from src.dreamer.models import ProductionDesign, Scene, Storyboard, VisualElement

runner = CliRunner()


@pytest.fixture
def mock_service():
    with patch("src.dreamer.cli.GeminiService") as mock:
        yield mock


def test_generate_missing_file() -> None:
    result = runner.invoke(app, ["nonexistent.mp3"])
    assert result.exit_code == 1
    assert "File nonexistent.mp3 not found" in result.stdout


def test_generate_success(mock_service, tmp_path) -> None:
    # Setup Audio File
    audio_file = tmp_path / "audio.mp3"
    audio_file.write_bytes(b"audio")

    # Setup Mock Service Response
    mock_instance = mock_service.return_value

    # Mock analyze_audio
    storyboard = Storyboard(
        title="Test Storyboard",
        production_design=ProductionDesign(
            art_style="Sketch",
            recurring_elements=[VisualElement(name="Char1", description="Desc1")],
        ),
        scenes=[
            Scene(
                timestamp=0.0,
                timing_rationale="Start",
                description="Scene1",
                visual_prompt="Draw Scene 1",
            ),
        ],
    )
    mock_instance.analyze_audio.return_value = storyboard

    # Mock generate_image return values
    # First call is for element, second for scene
    mock_instance.generate_image.side_effect = [
        str(tmp_path / "output/elements/Char1.png"),  # Element
        str(tmp_path / "output/scenes/scene_000.png"),  # Scene
    ]

    # Run CLI
    result = runner.invoke(
        app,
        [str(audio_file), "--output-dir", str(tmp_path / "output"), "--api-key", "key"],
    )

    assert result.exit_code == 0
    assert "Storyboard Generated" in result.stdout
    assert "Production Complete" in result.stdout

    # Check directory creation (logic in CLI)
    assert (tmp_path / "output").exists()
    assert (tmp_path / "output/elements").exists()
    assert (tmp_path / "output/scenes").exists()

    # Check JSON files
    assert (tmp_path / "output/storyboard.json").exists()
    assert (tmp_path / "output/storyboard_final.json").exists()


def test_generate_fatal_error(mock_service, tmp_path) -> None:
    audio_file = tmp_path / "audio.mp3"
    audio_file.write_bytes(b"audio")

    mock_instance = mock_service.return_value
    mock_instance.analyze_audio.side_effect = Exception("Boom")

    result = runner.invoke(app, [str(audio_file), "--api-key", "key"])

    assert result.exit_code == 1
    assert "Fatal Error" in result.stdout
    assert "Boom" in result.stdout
