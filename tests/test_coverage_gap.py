
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from src.dreamer.cli import app
from src.dreamer.models import ProductionDesign, Scene, Storyboard, VisualElement
from src.dreamer.service import GeminiService

runner = CliRunner()

@pytest.fixture
def mock_service():
    with patch("src.dreamer.cli.GeminiService") as mock:
        yield mock

@pytest.fixture
def dummy_storyboard():
    return Storyboard(
        title="Test",
        production_design=ProductionDesign(
            art_style="Style",
            recurring_elements=[
                VisualElement(name="Hero", description="A hero"),
                VisualElement(name="Villain", description="A villain"),
            ],
        ),
        scenes=[
            Scene(
                timestamp=0.0,
                timing_rationale="Start",
                description="Scene 1",
                visual_prompt="Prompt 1",
            ),
             Scene(
                timestamp=5.0,
                timing_rationale="End",
                description="Scene 2",
                visual_prompt="Prompt 2",
            ),
        ],
    )

def test_generate_invalid_audio_extension():
    # Create a temporary file with invalid extension
    with runner.isolated_filesystem():
        Path("test.txt").write_text("dummy audio")

        result = runner.invoke(app, ["analyze", "test.txt"])

        assert result.exit_code == 1
        assert "Unsupported audio format: .txt" in result.stdout

def test_generate_element_generation_failure(mock_service, dummy_storyboard):
    # Setup mock service
    service_instance = mock_service.return_value
    service_instance.analyze_audio.return_value = dummy_storyboard

    # Mock generate_image to fail for the first element, succeed for second
    service_instance.generate_image.side_effect = [
        Exception("API Error 1"), # Element 1 fails
        "path/to/villain.png",    # Element 2 succeeds
        "path/to/scene1.png",     # Scene 1
        "path/to/scene2.png",     # Scene 2
    ]

    with runner.isolated_filesystem():
        # Create valid audio file
        Path("audio.mp3").write_bytes(b"mp3")

        result = runner.invoke(app, ["analyze", "audio.mp3", "--api-key", "key"])

        assert result.exit_code == 0
        assert (
            "Warning: Failed to generate element 'Hero': API Error 1" in result.stdout
        )
        # Ensure process continued
        assert "Storyboard saved to" in result.stdout

def test_generate_scene_generation_failure(mock_service, dummy_storyboard):
    # Setup mock service
    service_instance = mock_service.return_value
    service_instance.analyze_audio.return_value = dummy_storyboard

    # Mock generate_image to succeed for elements, fail for first scene
    service_instance.generate_image.side_effect = [
        "path/to/hero.png",       # Element 1
        "path/to/villain.png",    # Element 2
        Exception("API Error Scene"), # Scene 1 fails
        "path/to/scene2.png",     # Scene 2
    ]

    with runner.isolated_filesystem():
        Path("audio.mp3").write_bytes(b"mp3")

        result = runner.invoke(app, ["analyze", "audio.mp3", "--api-key", "key"])

        assert result.exit_code == 0
        assert "Warning: Failed to generate scene 0: API Error Scene" in result.stdout
        assert "Storyboard saved to" in result.stdout

def test_service_mime_type_fallback(tmp_path):
    # Mock mimetypes.guess_type to return None
    with patch("mimetypes.guess_type", return_value=(None, None)):
        service = GeminiService(api_key="key")

        # Mock client
        service.client = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = Storyboard(
            title="T",
            production_design=ProductionDesign(
                art_style="S", recurring_elements=[]
            ),
            scenes=[],
        )
        service.client.models.generate_content.return_value = mock_response

        # Test mp3 fallback
        mp3_file = tmp_path / "test.mp3"
        mp3_file.write_bytes(b"data")
        service.analyze_audio(mp3_file)

        call_args = service.client.models.generate_content.call_args
        contents = call_args.kwargs["contents"]
        # The Part object created via Part.from_bytes usually puts data into inline_data
        # We need to check if inline_data.mime_type is correct
        assert contents[0].parts[0].inline_data.mime_type == "audio/mpeg"

        # Test wav fallback
        wav_file = tmp_path / "test.wav"
        wav_file.write_bytes(b"data")
        service.analyze_audio(wav_file)

        call_args = service.client.models.generate_content.call_args
        contents = call_args.kwargs["contents"]
        assert contents[0].parts[0].inline_data.mime_type == "audio/wav"
