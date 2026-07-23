"""Basic unit tests for Dreamer V2 models and database."""

from pathlib import Path
from unittest.mock import MagicMock

from dreamer.adapters.gemini import GeminiAdapter
from dreamer.database import DatabaseManager
from dreamer.models import (
    AnalysisResponse,
    ArtifactState,
    ArtifactStatus,
    Element,
    ElementKind,
    ScenePlan,
)


def test_models_validation() -> None:
    """Verify that models validate correct fields."""
    el = Element(
        id="char_001",
        kind=ElementKind.CHARACTER,
        canonical_description="A brave knight with shiny armor.",
    )
    assert el.id == "char_001"
    assert el.kind == ElementKind.CHARACTER
    assert el.reference_asset_path is None

    scene = ScenePlan(
        id="scene_001",
        sequence_id="seq_01",
        start_ms=0,
        end_ms=5000,
        audio_cue="Intro music playing",
        narrative_purpose="Introduce the knight",
        shot_type="Wide Shot",
        camera_angle="Eye-level",
        lighting="Golden hour",
        element_ids=["char_001"],
        visual_prompt="A knight standing on a hill during golden hour.",
    )
    assert scene.id == "scene_001"
    assert "char_001" in scene.element_ids


def test_database_manager(tmp_path: Path) -> None:
    """Verify that SQLite operations work correctly."""
    db_file = tmp_path / "run.sqlite"
    db = DatabaseManager(db_file)

    # Initial state
    assert db.get_total_cost() == 0.0
    assert db.get_artifact("scene_001") is None

    # Upsert artifact
    state = ArtifactState(
        artifact_id="scene_001",
        status=ArtifactStatus.APPROVED,
        path="/path/to/img.png",
    )
    db.upsert_artifact(state)

    retrieved = db.get_artifact("scene_001")
    assert retrieved is not None
    assert retrieved.status == ArtifactStatus.APPROVED
    assert retrieved.path == "/path/to/img.png"

    # Record cost
    db.record_cost(
        phase="Phase 1",
        model="gemini-3.5-flash",
        cost_usd=0.005,
    )
    assert db.get_total_cost() == 0.005


def test_gemini_adapter_analyze(mocker) -> None:
    """Verify that the Gemini adapter analyze method works with mocked Client API."""
    mock_client_cls = mocker.patch("dreamer.adapters.gemini.genai.Client")
    mock_client = mock_client_cls.return_value

    # Mock file upload
    mock_file = MagicMock()
    mock_file.name = "files/test-audio-id"
    mock_client.files.upload.return_value = mock_file

    # Mock response
    mock_response = MagicMock()
    mock_response.parsed = AnalysisResponse(
        title="Test Title",
        art_style="Pixel Art",
        visual_constraints=["No high tech"],
        elements=[],
        scenes=[],
    )
    mock_response.usage_metadata = MagicMock(
        prompt_token_count=1000,
        candidates_token_count=500,
    )
    mock_client.models.generate_content.return_value = mock_response

    adapter = GeminiAdapter(api_key="fake-key")
    result, in_tokens, out_tokens = adapter.analyze(
        audio_path=Path(__file__),  # dummy path that exists
        model="gemini-3.5-flash",
        mode="narrative",
    )

    assert result.title == "Test Title"
    assert result.art_style == "Pixel Art"
    assert in_tokens == 1000
    assert out_tokens == 500
    mock_client.files.upload.assert_called_once()
    mock_client.files.delete.assert_called_once_with(name="files/test-audio-id")


def test_gemini_adapter_render_single(mocker) -> None:
    """Verify render_single parses inline data from SDK response."""
    mock_client_cls = mocker.patch("dreamer.adapters.gemini.genai.Client")
    mock_client = mock_client_cls.return_value

    mock_response = MagicMock()
    mock_part = MagicMock()
    mock_part.inline_data = MagicMock(data=b"fake-image-bytes")

    mock_candidate = MagicMock()
    mock_candidate.content.parts = [mock_part]
    mock_response.candidates = [mock_candidate]
    mock_response.bytes = None
    mock_client.models.generate_content.return_value = mock_response

    adapter = GeminiAdapter(api_key="fake-key")
    img_bytes = adapter.render_single(
        prompt="A cute cat",
        reference_images=[],
        resolution="512px",
        model="gemini-3.1-flash-image",
    )

    assert img_bytes == b"fake-image-bytes"
