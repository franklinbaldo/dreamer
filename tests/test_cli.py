"""Unit tests for the CLI commands."""

import json
from pathlib import Path

from typer.testing import CliRunner

from dreamer.cli import app
from dreamer.models import AnalysisResponse, Element, ElementKind, ScenePlan


def test_cli_init_and_analyze(tmp_path: Path, mocker) -> None:
    """Verify cli init/analyze config, privacy, and cost policies."""
    # 1. Setup mock audio and run init command
    audio_file = tmp_path / "test_audio.mp3"
    audio_file.write_bytes(b"dummy audio content")

    project_dir = tmp_path / "test_project"
    runner = CliRunner()

    init_result = runner.invoke(
        app, ["init", str(audio_file), "--output", str(project_dir)]
    )
    assert init_result.exit_code == 0
    assert (project_dir / "project.toml").exists()
    assert (project_dir / "run.sqlite").exists()

    # 2. Modify config to test persist_transcripts = false
    config_path = project_dir / "project.toml"
    config_content = config_path.read_text()
    config_content = config_content.replace(
        "persist_transcripts = true", "persist_transcripts = false"
    )
    config_path.write_text(config_content)

    # 3. Mock the GeminiAdapter
    mock_adapter_class = mocker.patch("dreamer.cli.GeminiAdapter")
    mock_adapter = mock_adapter_class.return_value

    mock_response = AnalysisResponse(
        title="Test Story",
        art_style="Watercolor",
        visual_constraints=["Warm colors"],
        elements=[
            Element(
                id="char_01",
                kind=ElementKind.CHARACTER,
                canonical_description="Protagonist",
            )
        ],
        scenes=[
            ScenePlan(
                id="scene_01",
                sequence_id="seq_1",
                start_ms=0,
                end_ms=2000,
                audio_cue="Knight walking in forest",
                narrative_purpose="Introduction",
                shot_type="Wide Shot",
                camera_angle="Eye-level",
                lighting="Daylight",
                element_ids=["char_01"],
                visual_prompt="A knight in armor walking through green trees",
            )
        ],
    )

    mock_adapter.analyze.return_value = (mock_response, 100000, 50000)

    # Mock environment variable
    mocker.patch("os.getenv", return_value="fake_api_key")

    # Run analyze command
    analyze_result = runner.invoke(app, ["analyze", str(project_dir)])
    assert analyze_result.exit_code == 0

    # 4. Assert storyboard.json has cleared audio_cue due to persist_transcripts=false
    storyboard_path = project_dir / "storyboard.json"
    assert storyboard_path.exists()
    storyboard_data = json.loads(storyboard_path.read_text())
    assert storyboard_data["title"] == "Test Story"
    assert storyboard_data["scenes"][0]["audio_cue"] == ""  # Cleared!

    # 5. Assert visual_bible.json has style and constraints preserved
    bible_path = project_dir / "visual_bible.json"
    assert bible_path.exists()
    bible_data = json.loads(bible_path.read_text())
    assert bible_data["art_style"] == "Watercolor"
    assert bible_data["visual_constraints"] == ["Warm colors"]
    assert bible_data["elements"][0]["id"] == "char_01"

    # 6. Assert manifest.json exists
    assert (project_dir / "manifest.json").exists()


def test_cli_budget_limit_check(tmp_path: Path, mocker) -> None:
    """Verify that the CLI aborts and records the cost if the budget is exceeded."""
    audio_file = tmp_path / "test_audio.mp3"
    audio_file.write_bytes(b"dummy audio content")

    project_dir = tmp_path / "test_project"
    runner = CliRunner()

    runner.invoke(app, ["init", str(audio_file), "--output", str(project_dir)])

    # Setup config with a very low budget
    config_path = project_dir / "project.toml"
    config_content = config_path.read_text()
    config_content = config_content.replace(
        "max_cost_usd = 10.0", "max_cost_usd = 0.0001"
    )
    config_path.write_text(config_content)

    mock_adapter_class = mocker.patch("dreamer.cli.GeminiAdapter")
    mock_adapter = mock_adapter_class.return_value

    mock_response = AnalysisResponse(
        title="Test Story",
        art_style="Watercolor",
        visual_constraints=[],
        elements=[],
        scenes=[],
    )

    # Cost is calculated based on input and output tokens.
    # For 1M input/output tokens, cost exceeds the low budget limit.
    mock_adapter.analyze.return_value = (mock_response, 1000000, 1000000)
    mocker.patch("os.getenv", return_value="fake_api_key")

    analyze_result = runner.invoke(app, ["analyze", str(project_dir)])
    assert analyze_result.exit_code == 1  # Aborted!
    assert "Cost budget exceeded" in analyze_result.output


def test_cli_bible(tmp_path: Path, mocker) -> None:
    """Verify that the bible command generates assets and records costs."""
    audio_file = tmp_path / "test_audio.mp3"
    audio_file.write_bytes(b"dummy audio content")

    project_dir = tmp_path / "test_project"
    runner = CliRunner()

    runner.invoke(app, ["init", str(audio_file), "--output", str(project_dir)])

    # Write mock visual_bible.json
    bible_path = project_dir / "visual_bible.json"
    bible_data = {
        "art_style": "Watercolor",
        "visual_constraints": ["Warm colors"],
        "elements": [
            {
                "id": "char_01",
                "kind": "character",
                "canonical_description": "Protagonist",
                "reference_asset_path": ""
            }
        ]
    }
    with bible_path.open("w", encoding="utf-8") as f:
        json.dump(bible_data, f)

    # Mock the GeminiAdapter
    mock_adapter_class = mocker.patch("dreamer.cli.GeminiAdapter")
    mock_adapter = mock_adapter_class.return_value
    mock_adapter.render_batch.return_value = [b"mock_image_bytes"]
    mocker.patch("os.getenv", return_value="fake_api_key")

    bible_result = runner.invoke(app, ["bible", str(project_dir)])
    assert bible_result.exit_code == 0
    assert (project_dir / "bible" / "char_01.png").exists()

    with bible_path.open("r", encoding="utf-8") as f:
        updated_data = json.load(f)
    ref_path = updated_data["elements"][0]["reference_asset_path"]
    assert ref_path in ["bible/char_01.png", "bible\\char_01.png"]


def test_cli_render(tmp_path: Path, mocker) -> None:
    """Verify scene rendering command, respecting budget."""
    audio_file = tmp_path / "test_audio.mp3"
    audio_file.write_bytes(b"dummy")

    project_dir = tmp_path / "test_project"
    runner = CliRunner()
    runner.invoke(app, ["init", str(audio_file), "--output", str(project_dir)])

    # Write mock visual_bible.json and storyboard.json
    bible_path = project_dir / "visual_bible.json"
    with bible_path.open("w", encoding="utf-8") as f:
        json.dump({
            "art_style": "Watercolor",
            "visual_constraints": [],
            "elements": [{"id": "char_01", "reference_asset_path": "bible/char_01.png"}]
        }, f)

    storyboard_path = project_dir / "storyboard.json"
    with storyboard_path.open("w", encoding="utf-8") as f:
        json.dump({
            "scenes": [{
                "id": "scene_01",
                "sequence_id": "seq_1",
                "start_ms": 0,
                "end_ms": 2000,
                "element_ids": ["char_01"],
                "visual_prompt": "A knight in armor"
            }]
        }, f)

    mock_adapter_class = mocker.patch("dreamer.cli.GeminiAdapter")
    mock_adapter = mock_adapter_class.return_value
    mock_adapter.render_single.return_value = b"rendered_scene_bytes"
    mocker.patch("os.getenv", return_value="fake_api_key")

    # Render draft
    draft_result = runner.invoke(app, ["render", str(project_dir), "--stage", "draft"])
    assert draft_result.exit_code == 0
    assert (project_dir / "drafts" / "scene_01_draft.png").exists()


def test_cli_export(tmp_path: Path, mocker) -> None:
    """Verify that the export command invokes ffmpeg correctly to build the video."""
    audio_file = tmp_path / "source.mp3"
    audio_file.write_bytes(b"dummy")

    project_dir = tmp_path / "test_project"
    runner = CliRunner()
    runner.invoke(app, ["init", str(audio_file), "--output", str(project_dir)])

    # Place a dummy source.mp3 in the project directory
    (project_dir / "source.mp3").write_bytes(b"dummy")

    # Mock storyboard with scenes
    storyboard_path = project_dir / "storyboard.json"
    with storyboard_path.open("w", encoding="utf-8") as f:
        json.dump({
            "scenes": [{
                "id": "scene_01",
                "start_ms": 0,
                "end_ms": 2000
            }]
        }, f)

    # Place a dummy draft scene png
    draft_scene = project_dir / "drafts" / "scene_01_draft.png"
    draft_scene.parent.mkdir(parents=True, exist_ok=True)
    draft_scene.write_bytes(b"dummy_png")

    # Mock ffmpeg file check and subprocess
    mocker.patch("pathlib.Path.exists", return_value=True)
    mock_sub = mocker.patch("subprocess.run")
    mock_sub.return_value.returncode = 0

    export_result = runner.invoke(app, ["export", str(project_dir)])
    assert export_result.exit_code == 0
    assert mock_sub.called

