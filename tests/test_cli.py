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


def test_analyze_missing_file() -> None:
    result = runner.invoke(app, ["analyze", "nonexistent.mp3"])
    assert result.exit_code == 1
    assert "File nonexistent.mp3 not found" in result.stdout


def test_analyze_success(mock_service, tmp_path) -> None:
    audio_file = tmp_path / "audio.mp3"
    audio_file.write_bytes(b"audio")

    mock_instance = mock_service.return_value
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

    result = runner.invoke(
        app,
        [
            "analyze",
            str(audio_file),
            "--output-dir",
            str(tmp_path / "output"),
            "--api-key",
            "key",
        ],
    )

    assert result.exit_code == 0
    assert "Storyboard Generated" in result.stdout
    assert (tmp_path / "output/storyboard.json").exists()


def test_design_success(mock_service, tmp_path) -> None:
    # Let's test resume, which covers design phase.
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    storyboard_path = output_dir / "storyboard.json"
    storyboard = Storyboard(
        title="Test",
        production_design=ProductionDesign(
            art_style="Style",
            recurring_elements=[VisualElement(name="Hero", description="A hero")],
        ),
        scenes=[],
    )
    storyboard_path.write_text(storyboard.model_dump_json())

    mock_instance = mock_service.return_value
    mock_instance.generate_image.return_value = str(
        tmp_path / "output/elements/Hero.png",
    )

    result = runner.invoke(
        app,
        [
            "resume",
            str(output_dir),
            "--api-key",
            "key",
        ],
    )

    assert result.exit_code == 0
    # The output might vary but we expect success
    assert (tmp_path / "output/elements").exists()


def test_render_success(mock_service, tmp_path) -> None:
    storyboard_path = tmp_path / "storyboard.json"
    storyboard = Storyboard(
        title="Test",
        production_design=ProductionDesign(
            art_style="Style",
            recurring_elements=[],
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
    storyboard_path.write_text(storyboard.model_dump_json())

    mock_instance = mock_service.return_value
    mock_instance.generate_image.return_value = str(tmp_path / "scenes/scene_0.png")

    result = runner.invoke(
        app,
        [
            "render",
            str(storyboard_path),
            "--output-dir",
            str(tmp_path / "scenes"),
            "--api-key",
            "key",
        ],
    )

    assert result.exit_code == 0
    assert "Production Complete" in result.stdout
    assert (tmp_path / "scenes").exists()
    assert (tmp_path / "storyboard_final.json").exists()


def test_resume(mock_service, tmp_path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    storyboard_path = output_dir / "storyboard.json"
    storyboard = Storyboard(
        title="Test",
        production_design=ProductionDesign(
            art_style="Style",
            recurring_elements=[VisualElement(name="Hero", description="A hero")],
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
    storyboard_path.write_text(storyboard.model_dump_json())

    mock_instance = mock_service.return_value
    # 1 element + 1 scene
    mock_instance.generate_image.side_effect = [
        str(output_dir / "elements/Hero.png"),
        str(output_dir / "scenes/scene_0.png"),
    ]

    result = runner.invoke(app, ["resume", str(output_dir), "--api-key", "key"])

    assert result.exit_code == 0
    assert "Resuming processing" in result.stdout
