from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from src.dreamer.cli import app
from src.dreamer.models import ProductionDesign, Scene, Storyboard, VisualElement

runner = CliRunner()


@pytest.fixture
def mock_service() -> MagicMock:
    """Fixture to mock the GeminiService."""
    with patch("src.dreamer.cli.GeminiService") as mock:
        yield mock


@pytest.fixture
def mock_storyboard() -> Storyboard:
    """Fixture to create a sample storyboard."""
    return Storyboard(
        title="Test Storyboard",
        production_design=ProductionDesign(
            art_style="Sketch",
            recurring_elements=[
                VisualElement(name="Hero", description="A brave hero"),
            ],
        ),
        scenes=[
            Scene(
                timestamp=0.0,
                timing_rationale="Start of the story",
                description="The hero wakes up.",
                visual_prompt="A hero character waking up in a stylized bedroom.",
            ),
        ],
    )


def test_generate_missing_file() -> None:
    """Test the generate command with a nonexistent audio file."""
    result = runner.invoke(app, ["generate", "nonexistent.mp3"])
    assert result.exit_code == 1
    assert "File nonexistent.mp3 not found" in result.stdout


def test_generate_success(
    mock_service: MagicMock,
    mock_storyboard: Storyboard,
    tmp_path,
) -> None:
    """Test the full `generate` pipeline from scratch."""
    audio_file = tmp_path / "audio.mp3"
    audio_file.touch()
    output_dir = tmp_path / "output"

    mock_instance = mock_service.return_value
    mock_instance.analyze_audio.return_value = mock_storyboard
    # Mock image generation for the element and the scene
    mock_instance.generate_image.side_effect = [
        str(output_dir / "elements" / "Hero.png"),
        str(output_dir / "scenes" / "scene_000_00_0s.png"),
    ]

    result = runner.invoke(
        app,
        [
            "generate",
            str(audio_file),
            "--output-dir",
            str(output_dir),
            "--api-key",
            "fake-key",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Storyboard Generated" in result.stdout
    assert "Production Complete" in result.stdout

    # Verify mocks were called
    mock_instance.analyze_audio.assert_called_once()
    assert mock_instance.generate_image.call_count == 2

    # Verify files were created
    assert (output_dir / "storyboard.json").exists()
    assert (output_dir / "storyboard_final.json").exists()


def test_generate_resume_success(
    mock_service: MagicMock,
    mock_storyboard: Storyboard,
    tmp_path,
) -> None:
    """Test that `generate` resumes correctly if a storyboard exists."""
    audio_file = tmp_path / "audio.mp3"
    audio_file.touch()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    storyboard_path = output_dir / "storyboard.json"
    storyboard_path.write_text(mock_storyboard.model_dump_json())

    mock_instance = mock_service.return_value
    # Mock image generation for the element and the scene
    mock_instance.generate_image.side_effect = [
        str(output_dir / "elements" / "Hero.png"),
        str(output_dir / "scenes" / "scene_000_00_0s.png"),
    ]

    result = runner.invoke(
        app,
        [
            "generate",
            str(audio_file),
            "--output-dir",
            str(output_dir),
            "--api-key",
            "fake-key",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Found existing storyboard" in result.stdout
    assert "Production Complete" in result.stdout

    # Verify analysis was NOT called, but image generation was
    mock_instance.analyze_audio.assert_not_called()
    assert mock_instance.generate_image.call_count == 2
