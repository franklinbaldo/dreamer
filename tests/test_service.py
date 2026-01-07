import base64
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.dreamer.models import ProductionDesign, Storyboard
from src.dreamer.service import GeminiService


@pytest.fixture
def mock_genai_client():
    with patch("src.dreamer.service.genai.Client") as mock:
        yield mock


def test_service_init(mock_genai_client):
    service = GeminiService(api_key="fake-key")
    mock_genai_client.assert_called_with(api_key="fake-key")
    assert service.client is not None


def test_service_init_missing_key():
    with pytest.raises(ValueError, match="API Key is missing"):
        GeminiService(api_key="")


def test_analyze_audio(mock_genai_client, tmp_path):
    # Setup mock
    mock_response = MagicMock()
    # Mocking the .parsed property behavior
    storyboard_obj = Storyboard(
        title="Test",
        production_design=ProductionDesign(
            art_style="Test Style",
            recurring_elements=[],
        ),
        scenes=[],
    )
    mock_response.parsed = storyboard_obj

    mock_client_instance = mock_genai_client.return_value
    mock_client_instance.models.generate_content.return_value = mock_response

    # Create dummy audio file
    audio_file = tmp_path / "test.mp3"
    audio_file.write_bytes(b"audio data")

    service = GeminiService(api_key="key")
    result = service.analyze_audio(audio_file)

    assert result == storyboard_obj
    mock_client_instance.models.generate_content.assert_called_once()


def test_analyze_audio_fallback_parsing(mock_genai_client, tmp_path):
    # Setup mock for fallback (no .parsed)
    mock_response = MagicMock()
    # Ensure AttributeError or similar if accessed, or just None?
    # Actually 'parsed' might just be None or missing.
    # The code checks `if hasattr(response, 'parsed') and response.parsed:`
    mock_response.parsed = None

    json_str = """
    {
        "title": "Fallback",
        "production_design": {
            "art_style": "Fallback Style",
            "recurring_elements": []
        },
        "scenes": []
    }
    """
    mock_response.text = json_str

    mock_client_instance = mock_genai_client.return_value
    mock_client_instance.models.generate_content.return_value = mock_response

    audio_file = tmp_path / "test.wav"
    audio_file.write_bytes(b"wav data")

    service = GeminiService(api_key="key")
    result = service.analyze_audio(audio_file)

    assert result.title == "Fallback"


def test_analyze_audio_error(mock_genai_client, tmp_path):
    mock_client_instance = mock_genai_client.return_value
    mock_client_instance.models.generate_content.side_effect = Exception("API Error")

    audio_file = tmp_path / "test.mp3"
    audio_file.write_bytes(b"data")

    service = GeminiService(api_key="key")
    with pytest.raises(RuntimeError, match="Failed to interpret audio storyboard"):
        service.analyze_audio(audio_file)


def test_generate_image_success(mock_genai_client, tmp_path):
    mock_response = MagicMock()
    mock_response.bytes = b"image data"

    mock_client_instance = mock_genai_client.return_value
    mock_client_instance.models.generate_content.return_value = mock_response

    service = GeminiService(api_key="key")
    output_path = tmp_path / "out.png"

    result = service.generate_image("prompt", output_path=output_path)

    assert result == str(output_path)
    assert output_path.read_bytes() == b"image data"


def test_generate_image_inline_data_fallback(mock_genai_client, tmp_path):
    mock_response = MagicMock()
    mock_response.bytes = None

    # Mock inline data
    b64_data = base64.b64encode(b"inline data").decode("utf-8")

    part = MagicMock()
    part.inline_data.data = b64_data

    candidate = MagicMock()
    candidate.content.parts = [part]

    mock_response.candidates = [candidate]

    mock_client_instance = mock_genai_client.return_value
    mock_client_instance.models.generate_content.return_value = mock_response

    service = GeminiService(api_key="key")
    output_path = tmp_path / "out_inline.png"

    result = service.generate_image("prompt", output_path=output_path)

    assert result == str(output_path)
    assert output_path.read_bytes() == b"inline data"


def test_generate_image_with_references(mock_genai_client, tmp_path):
    mock_response = MagicMock()
    mock_response.bytes = b"img"
    mock_client_instance = mock_genai_client.return_value
    mock_client_instance.models.generate_content.return_value = mock_response

    ref_img = tmp_path / "ref.png"
    ref_img.write_bytes(b"ref")

    service = GeminiService(api_key="key")
    output_path = tmp_path / "out.png"

    service.generate_image(
        "prompt",
        reference_image_paths=[str(ref_img)],
        output_path=output_path,
    )

    # Verify call args include the reference image
    call_args = mock_client_instance.models.generate_content.call_args
    # contents is the named arg or first arg
    contents = call_args.kwargs.get("contents") or call_args.args[1]
    # Structure is contents=[types.Content(parts=[...])]
    parts = contents[0].parts
    # Should have 1 image part (ref) and 1 text part (prompt)
    assert len(parts) == 2
    # Verify the part is an image part (checking inline_data or just existence)
    # The SDK Part object structure might vary,
    # but we can check if it has inline_data with mime_type
    assert parts[0].inline_data.mime_type == "image/png"


def test_generate_image_failure_after_retries(mock_genai_client):
    mock_client_instance = mock_genai_client.return_value
    mock_client_instance.models.generate_content.side_effect = Exception("Fail")

    service = GeminiService(api_key="key")

    # To speed up test, patch time.sleep
    with patch("time.sleep"), pytest.raises(Exception, match="Fail"):
        service.generate_image(
            "prompt",
            output_path=Path("out.png"),
            retries=1,
        )


def test_generate_image_fallback_missing_candidates(mock_genai_client, tmp_path):
    mock_response = MagicMock()
    mock_response.bytes = None
    mock_response.candidates = []  # No candidates

    mock_client_instance = mock_genai_client.return_value
    mock_client_instance.models.generate_content.return_value = mock_response

    service = GeminiService(api_key="key")

    # This should fail after retries because it raises
    # RuntimeError "No image data in response"
    # and then retries loop catches it.
    with (
        patch("time.sleep"),
        pytest.raises(RuntimeError, match="No image data in response"),
    ):
        service.generate_image(
            "prompt",
            output_path=Path("out.png"),
            retries=0,
        )


def test_generate_image_inline_data_success(mock_genai_client, tmp_path):
    # This tests the branch where response.bytes is None,
    # but inline_data exists and write is called.
    mock_response = MagicMock()
    mock_response.bytes = None

    b64_data = base64.b64encode(b"inline img").decode("utf-8")

    part = MagicMock()
    part.inline_data.data = b64_data

    mock_response.candidates = [MagicMock(content=MagicMock(parts=[part]))]

    mock_client_instance = mock_genai_client.return_value
    mock_client_instance.models.generate_content.return_value = mock_response

    service = GeminiService(api_key="key")
    output_path = tmp_path / "inline.png"

    result = service.generate_image("prompt", output_path=output_path)

    assert result == str(output_path)
    assert output_path.read_bytes() == b"inline img"
