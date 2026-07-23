"""CLI Application for Dreamer V2."""

import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from typer.testing import CliRunner

from .adapters.gemini import GeminiAdapter
from .database import DatabaseManager
from .models import (
    ArtifactState,
    ArtifactStatus,
    ProjectConfig,
)

# Initialize console
console = Console()

TINY_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"


app = typer.Typer(
    name="dreamer",
    help="Dreamer V2: Audio to Visual Storyboard CLI",
    add_completion=False,
)


def _get_audio_hash(audio_path: Path) -> str:
    """Calculate the SHA-256 hash of an audio file."""
    sha256 = hashlib.sha256()
    with audio_path.open("rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Dreamer V2: Audio to Visual Storyboard CLI."""
    if ctx.invoked_subcommand is None:
        console.print("[bold cyan]Dreamer V2[/bold cyan] - Use --help for usage details.")


@app.command()
def init(
    audio_path_str: str = typer.Argument(..., metavar="AUDIO_FILE", help="Path to input audio file"),
    output_dir_str: str = typer.Option(None, "--output", "-o", help="Path to the output project directory"),
) -> None:
    """Initialize a new project directory for storyboarding."""
    audio_path = Path(audio_path_str)
    if not audio_path.exists():
        console.print(f"[bold red]Error:[/bold red] Audio file '{audio_path}' does not exist.")
        raise typer.Exit(code=1)

    # Determine project directory name if not specified
    if not output_dir_str:
        project_dir = audio_path.parent / f"{audio_path.stem}_project"
    else:
        project_dir = Path(output_dir_str)

    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "bible").mkdir(exist_ok=True)
    (project_dir / "drafts").mkdir(exist_ok=True)
    (project_dir / "renders").mkdir(exist_ok=True)
    (project_dir / "exports").mkdir(exist_ok=True)

    # Copy audio or keep reference
    audio_dest = project_dir / f"source{audio_path.suffix}"
    if not audio_dest.exists() or _get_audio_hash(audio_dest) != _get_audio_hash(audio_path):
        audio_dest.write_bytes(audio_path.read_bytes())

    audio_hash = _get_audio_hash(audio_dest)

    # Write initial project.toml
    config = ProjectConfig(
        name=project_dir.name,
        audio_hash=audio_hash,
    )

    config_path = project_dir / "project.toml"
    with config_path.open("w", encoding="utf-8") as f:
        f.write(f'name = "{config.name}"\n')
        f.write(f'audio_hash = "{config.audio_hash}"\n')
        f.write(f'mode = "{config.mode}"\n')
        f.write(f'aspect_ratio = "{config.aspect_ratio}"\n')
        f.write(f"max_cost_usd = {config.max_cost_usd}\n")
        f.write(f'audio_analysis_model = "{config.audio_analysis_model}"\n')
        f.write(f'image_generation_model = "{config.image_generation_model}"\n')
        f.write(f"persist_transcripts = {'true' if config.persist_transcripts else 'false'}\n")

    # Initialize SQLite Database
    DatabaseManager(project_dir / "run.sqlite")

    console.print(
        Panel(
            f"[bold green]Project Initialized Successfully![/bold green]\n\n"
            f"[bold]Project Path:[/bold] {project_dir.absolute()}\n"
            f"[bold]Audio Source:[/bold] {audio_dest.name}\n"
            f"[bold]Audio SHA-256:[/bold] {audio_hash}",
            title="Success",
            border_style="green",
        ),
    )


@app.command()
def analyze(
    project_dir_str: str = typer.Argument(..., metavar="PROJECT_DIR", help="Path to project directory"),
) -> None:
    """Analyze the audio file and generate the base storyboard.json."""
    load_dotenv()
    project_dir = Path(project_dir_str)
    config_path = project_dir / "project.toml"
    if not config_path.exists():
        console.print(f"[bold red]Error:[/bold red] Project config not found at '{config_path}'")
        raise typer.Exit(code=1)

    # Simple TOML parser
    config_data: dict[str, Any] = {}
    with config_path.open("r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                k, v = line.split("=", 1)
                config_data[k.strip()] = v.strip().strip('"').strip("'")

    audio_files = list(project_dir.glob("source.*"))
    if not audio_files:
        console.print("[bold red]Error:[/bold red] Source audio file not found in project.")
        raise typer.Exit(code=1)
    audio_path = audio_files[0]

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        console.print("[bold red]Error:[/bold red] GEMINI_API_KEY env var not set.")
        raise typer.Exit(code=1)

    adapter = GeminiAdapter(api_key=api_key)
    db_manager = DatabaseManager(project_dir / "run.sqlite")

    console.print("[yellow]Starting audio analysis (Phase 1)...[/yellow]")
    model = config_data.get("audio_analysis_model", "gemini-3.5-flash")
    mode = config_data.get("mode", "narrative")

    try:
        result, input_tokens, output_tokens = adapter.analyze(
            audio_path=audio_path,
            model=model,
            mode=mode,
        )

        # Parse config for persist_transcripts
        persist_transcripts = config_data.get("persist_transcripts", "true").lower() == "true"

        # Prepare scenes & elements dicts
        scenes_data = []
        for scene in result.scenes:
            sc_dict = scene.model_dump()
            if not persist_transcripts:
                sc_dict["audio_cue"] = ""
            scenes_data.append(sc_dict)

        elements_data = [el.model_dump() for el in result.elements]

        # Calculate actual cost (Gemini 3.5 Flash: input=$0.075/1M, output=$0.30/1M)
        cost_usd = (input_tokens * 0.075 / 1_000_000) + (output_tokens * 0.30 / 1_000_000)

        # Budget Check
        max_cost = float(config_data.get("max_cost_usd", 10.0))
        current_cost = db_manager.get_total_cost()
        if current_cost + cost_usd > max_cost:
            console.print(
                f"[bold red]Error:[/bold red] Cost budget exceeded. "
                f"Budget: ${max_cost:.4f}, Current: ${current_cost:.4f}, Phase cost: ${cost_usd:.4f}"
            )
            # Record the cost that was actually incurred anyway
            db_manager.record_cost(
                phase="Phase 1: Audio Analysis (Exceeded budget)",
                model=model,
                tokens_input=input_tokens,
                tokens_output=output_tokens,
                cost_usd=cost_usd,
            )
            raise typer.Exit(code=1)

        # Write storyboard.json (editorial plano)
        storyboard_path = project_dir / "storyboard.json"
        with storyboard_path.open("w", encoding="utf-8") as f:
            json.dump({"title": result.title, "scenes": scenes_data}, f, indent=2)

        # Write visual_bible.json (elementos canônicos + style)
        bible_path = project_dir / "visual_bible.json"
        with bible_path.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "art_style": result.art_style,
                    "visual_constraints": result.visual_constraints,
                    "elements": elements_data,
                },
                f,
                indent=2,
            )

        # Write manifest.json (metadados de execução)
        manifest_path = project_dir / "manifest.json"
        manifest = {
            "title": result.title,
            "audio_hash": config_data.get("audio_hash"),
            "model_used": model,
            "mode": mode,
            "timestamp_analyzed": str(Path(audio_path).stat().st_mtime),
        }
        with manifest_path.open("w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        # Record SQLite initialization of artifacts
        for element in elements_data:
            state = ArtifactState(
                artifact_id=element["id"],
                status=ArtifactStatus.PENDING,
            )
            db_manager.upsert_artifact(state)

        for scene in scenes_data:
            state = ArtifactState(
                artifact_id=scene["id"],
                status=ArtifactStatus.PENDING,
            )
            db_manager.upsert_artifact(state)

        # Record cost
        db_manager.record_cost(
            phase="Phase 1: Audio Analysis",
            model=model,
            tokens_input=input_tokens,
            tokens_output=output_tokens,
            cost_usd=cost_usd,
        )

        console.print(
            Panel(
                f"[bold green]Analysis Complete![/bold green]\n\n"
                f"[bold]Title:[/bold] {result.title}\n"
                f"[bold]Scenes Analyzed:[/bold] {len(scenes_data)}\n"
                f"[bold]Elements Found:[/bold] {len(elements_data)}\n"
                f"[bold]Cost Incurred:[/bold] ${cost_usd:.5f} USD\n"
                f"[bold]Storyboard File:[/bold] {storyboard_path.name}\n"
                f"[bold]Visual Bible File:[/bold] {bible_path.name}",
                title="Success",
                border_style="green",
            ),
        )

    except Exception as e:
        console.print(f"[bold red]Analysis failed:[/bold red] {e}")
        raise typer.Exit(code=1) from e


@app.command()
def bible(
    project_dir_str: str = typer.Argument(..., metavar="PROJECT_DIR", help="Path to project directory"),
    mock: bool = typer.Option(False, "--mock", help="Use mock image generation instead of Gemini API"),
) -> None:
    """Generate visual assets for recurring elements in the storyboard."""
    load_dotenv()
    project_dir = Path(project_dir_str)
    config_path = project_dir / "project.toml"
    if not config_path.exists():
        console.print(f"[bold red]Error:[/bold red] Project config not found at '{config_path}'")
        raise typer.Exit(code=1)

    # Simple TOML parser
    config_data: dict[str, Any] = {}
    with config_path.open("r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                k, v = line.split("=", 1)
                config_data[k.strip()] = v.strip().strip('"').strip("'")

    bible_path = project_dir / "visual_bible.json"
    if not bible_path.exists():
        console.print("[bold red]Error:[/bold red] visual_bible.json not found. Run analyze first.")
        raise typer.Exit(code=1)

    with bible_path.open("r", encoding="utf-8") as f:
        bible_data = json.load(f)

    elements = bible_data.get("elements", [])
    if not elements:
        console.print("No elements to generate in visual_bible.json.")
        return

    db_manager = DatabaseManager(project_dir / "run.sqlite")
    if not mock:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            console.print("[bold red]Error:[/bold red] GEMINI_API_KEY env var not set.")
            raise typer.Exit(code=1)
        adapter = GeminiAdapter(api_key=api_key)
    else:
        adapter = None

    art_style = bible_data.get("art_style", "Standard Style")
    visual_constraints = bible_data.get("visual_constraints", [])
    image_model = config_data.get("image_generation_model", "gemini-3.1-flash-image")

    # Filter elements that are not already generated
    to_generate = []
    for el in elements:
        dest_path = project_dir / "bible" / f"{el['id']}.png"
        if not dest_path.exists():
            to_generate.append((el, dest_path))

    if not to_generate:
        console.print("All visual bible elements are already generated.")
        return

    # Check budget
    price_per_img = 0.075  # 1K image cost
    total_new_cost = len(to_generate) * price_per_img
    max_cost = float(config_data.get("max_cost_usd", 10.0))
    current_cost = db_manager.get_total_cost()

    if current_cost + total_new_cost > max_cost:
        console.print(
            f"[bold red]Error:[/bold red] Geração de elementos excede o orçamento de custo. "
            f"Orçamento: ${max_cost:.4f}, Atual: ${current_cost:.4f}, Novo Custo: ${total_new_cost:.4f}"
        )
        raise typer.Exit(code=1)

    console.print(f"[yellow]Generating reference assets for {len(to_generate)} elements...[/yellow]")

    prompts = []
    for el, _ in to_generate:
        constraints_str = ", ".join(visual_constraints) if visual_constraints else "None"
        prompt = (
            f"Visual Bible reference sheet. Style: {art_style}. "
            f"Visual constraints: {constraints_str}. "
            f"Subject: {el['id']} - {el['canonical_description']}. "
            f"Single character or object centered against a neutral studio background."
        )
        prompts.append(prompt)

    try:
        if mock:
            images_bytes = [TINY_PNG] * len(to_generate)
        else:
            images_bytes = adapter.render_batch(
                prompts=prompts,
                reference_images=[],
                resolution="1K",
                model=image_model,
            )

        for (el, dest_path), img_bytes in zip(to_generate, images_bytes):
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(img_bytes)
            # Update visual_bible.json element path
            el["reference_asset_path"] = str(dest_path.relative_to(project_dir))
            # Update database
            db_manager.upsert_artifact(
                ArtifactState(
                    artifact_id=el["id"],
                    status=ArtifactStatus.APPROVED,
                    path=str(dest_path),
                )
            )

        # Write updated visual_bible.json
        with bible_path.open("w", encoding="utf-8") as f:
            json.dump(bible_data, f, indent=2)

        # Record SQLite costs
        db_manager.record_cost(
            phase="Phase 2: Visual Bible Generation",
            model=image_model,
            images_count=len(to_generate),
            resolution="1K",
            cost_usd=total_new_cost,
        )

        console.print(f"[bold green]Visual Bible populated! Cost: ${total_new_cost:.4f} USD[/bold green]")

    except Exception as e:
        console.print(f"[bold red]Visual bible generation failed:[/bold red] {e}")
        raise typer.Exit(code=1) from e


@app.command()
def review(
    project_dir_str: str = typer.Argument(..., metavar="PROJECT_DIR", help="Path to project directory"),
) -> None:
    """Launch the local storyboard editor/review tool."""
    console.print("[yellow]Launching local review tool... (Staged for development)[/yellow]")


@app.command()
def render(
    project_dir_str: str = typer.Argument(..., metavar="PROJECT_DIR", help="Path to project directory"),
    stage: str = typer.Option("draft", "--stage", help="Render stage: draft or final"),
    scene_id: str = typer.Option(None, "--scene", help="Render specific scene ID"),
    mock: bool = typer.Option(False, "--mock", help="Use mock image generation instead of Gemini API"),
) -> None:
    """Render scenes (draft or final)."""
    load_dotenv()
    project_dir = Path(project_dir_str)
    config_path = project_dir / "project.toml"
    if not config_path.exists():
        console.print(f"[bold red]Error:[/bold red] Project config not found at '{config_path}'")
        raise typer.Exit(code=1)

    # Simple TOML parser
    config_data: dict[str, Any] = {}
    with config_path.open("r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                k, v = line.split("=", 1)
                config_data[k.strip()] = v.strip().strip('"').strip("'")

    storyboard_path = project_dir / "storyboard.json"
    if not storyboard_path.exists():
        console.print("[bold red]Error:[/bold red] storyboard.json not found. Run analyze first.")
        raise typer.Exit(code=1)

    with storyboard_path.open("r", encoding="utf-8") as f:
        storyboard_data = json.load(f)

    scenes = storyboard_data.get("scenes", [])
    if not scenes:
        console.print("No scenes found in storyboard.json.")
        return

    bible_path = project_dir / "visual_bible.json"
    if not bible_path.exists():
        console.print("[bold red]Error:[/bold red] visual_bible.json not found. Run bible first.")
        raise typer.Exit(code=1)

    with bible_path.open("r", encoding="utf-8") as f:
        bible_data = json.load(f)

    elements_map = {el["id"]: el for el in bible_data.get("elements", [])}
    art_style = bible_data.get("art_style", "Standard Style")
    visual_constraints = bible_data.get("visual_constraints", [])
    image_model = config_data.get("image_generation_model", "gemini-3.1-flash-image")

    # Filter to render
    to_render = []
    for sc in scenes:
        if scene_id and sc["id"] != scene_id:
            continue

        folder = "drafts" if stage == "draft" else "renders"
        suffix = "_draft.png" if stage == "draft" else "_final.png"
        dest_path = project_dir / folder / f"{sc['id']}{suffix}"

        if not dest_path.exists():
            to_render.append((sc, dest_path))

    if not to_render:
        console.print(f"All scenes are already rendered for stage '{stage}'.")
        return

    # Check budget
    resolution = "512px" if stage == "draft" else "2K"
    price_per_img = 0.045 if stage == "draft" else 0.101
    total_new_cost = len(to_render) * price_per_img
    max_cost = float(config_data.get("max_cost_usd", 10.0))
    db_manager = DatabaseManager(project_dir / "run.sqlite")
    current_cost = db_manager.get_total_cost()

    if current_cost + total_new_cost > max_cost:
        console.print(
            f"[bold red]Error:[/bold red] Rendering would exceed cost budget. "
            f"Budget: ${max_cost:.4f}, Current: ${current_cost:.4f}, New Cost: ${total_new_cost:.4f}"
        )
        raise typer.Exit(code=1)

    console.print(f"[yellow]Rendering {len(to_render)} scenes at resolution {resolution}...[/yellow]")

    if not mock:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            console.print("[bold red]Error:[/bold red] GEMINI_API_KEY env var not set.")
            raise typer.Exit(code=1)
        adapter = GeminiAdapter(api_key=api_key)
    else:
        adapter = None

    async def _render_all() -> None:
        sem = asyncio.Semaphore(4)

        async def _sem_one(sc: dict, dest: Path) -> None:
            async with sem:
                ref_paths = []
                for el_id in sc.get("element_ids", []):
                    if el_id in elements_map:
                        ref_path_str = elements_map[el_id].get("reference_asset_path")
                        if ref_path_str:
                            ref_path = project_dir / ref_path_str
                            if ref_path.exists():
                                ref_paths.append(ref_path)

                constraints_str = ", ".join(visual_constraints) if visual_constraints else "None"
                prompt = (
                    f"Create storyboard scene in '{art_style}' style. "
                    f"Visual constraints: {constraints_str}. "
                    f"Visual prompt: {sc['visual_prompt']}. "
                    f"Maintain visual coherence with reference assets."
                )

                try:
                    if mock:
                        img_bytes = TINY_PNG
                    else:
                        img_bytes = await asyncio.to_thread(
                            adapter.render_single,
                            prompt,
                            ref_paths,
                            resolution,
                            image_model,
                        )
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(img_bytes)
                    db_manager.upsert_artifact(
                        ArtifactState(
                            artifact_id=sc["id"],
                            status=ArtifactStatus.APPROVED if stage == "final" else ArtifactStatus.GENERATED,
                            path=str(dest),
                        )
                    )
                except Exception as ex:
                    console.print(f"[yellow]Warning: Scene {sc['id']} failed to render: {ex}[/yellow]")
                    db_manager.upsert_artifact(
                        ArtifactState(
                            artifact_id=sc["id"],
                            status=ArtifactStatus.FAILED,
                            error=str(ex),
                        )
                    )

        tasks = [_sem_one(sc, dest) for sc, dest in to_render]
        await asyncio.gather(*tasks)

    asyncio.run(_render_all())

    # Record SQLite costs
    db_manager.record_cost(
        phase=f"Phase 3: Scene Rendering ({stage})",
        model=image_model,
        images_count=len(to_render),
        resolution=resolution,
        cost_usd=total_new_cost,
    )

    console.print(f"[bold green]Scene rendering completed! Cost: ${total_new_cost:.4f} USD[/bold green]")



@app.command()
def resume(
    project_dir_str: str = typer.Argument(..., metavar="PROJECT_DIR", help="Path to project directory"),
) -> None:
    """Resume execution of the next pending stage in the pipeline."""
    console.print("[yellow]Resuming pipeline execution... (Staged for development)[/yellow]")


@app.command()
def status(
    project_dir_str: str = typer.Argument(..., metavar="PROJECT_DIR", help="Path to project directory"),
) -> None:
    """Show status of rendering jobs, costs, and project artifacts."""
    project_dir = Path(project_dir_str)
    db_path = project_dir / "run.sqlite"
    if not db_path.exists():
        console.print(f"[bold red]Error:[/bold red] Project sqlite file not found at {db_path}")
        raise typer.Exit(code=1)

    db_manager = DatabaseManager(db_path)
    total_cost = db_manager.get_total_cost()

    console.print(
        Panel(
            f"[bold cyan]Project Status[/bold cyan]\n\n"
            f"[bold]Total Cost Ledger:[/bold] ${total_cost:.4f} USD\n"
            f"[bold]Database Path:[/bold] {db_path.absolute()}",
            title="Status",
            border_style="cyan",
        ),
    )


@app.command()
def estimate(
    project_dir_str: str = typer.Argument(..., metavar="PROJECT_DIR", help="Path to project directory"),
) -> None:
    """Estimate costs before running image generation commands."""
    console.print("[yellow]Estimating project costs... (Staged for development)[/yellow]")


@app.command()
def export(
    project_dir_str: str = typer.Argument(..., metavar="PROJECT_DIR", help="Path to project directory"),
    format_str: str = typer.Option("mp4", "--format", help="Export format: mp4, pdf, or otio"),
) -> None:
    """Export the visual storyboard to the desired format."""
    project_dir = Path(project_dir_str)
    storyboard_path = project_dir / "storyboard.json"
    if not storyboard_path.exists():
        console.print("[bold red]Error:[/bold red] storyboard.json not found.")
        raise typer.Exit(code=1)

    with storyboard_path.open("r", encoding="utf-8") as f:
        storyboard_data = json.load(f)

    scenes = storyboard_data.get("scenes", [])
    if not scenes:
        console.print("No scenes found in storyboard.json.")
        return

    audio_files = list(project_dir.glob("source.*"))
    if not audio_files:
        console.print("[bold red]Error:[/bold red] Source audio file not found in project.")
        raise typer.Exit(code=1)
    audio_path = audio_files[0]

    if format_str == "mp4":
        ffmpeg_bin = project_dir.parent / "dreamer-v2" / "bin" / "ffmpeg.exe"
        if not ffmpeg_bin.exists():
            ffmpeg_bin = Path("C:\\Users\\frank\\workspace\\dreamer-v2\\bin\\ffmpeg.exe")

        if not ffmpeg_bin.exists():
            console.print("[bold red]Error:[/bold red] ffmpeg.exe not found.")
            raise typer.Exit(code=1)

        concat_lines = []
        for sc in scenes:
            dest_path = project_dir / "renders" / f"{sc['id']}_final.png"
            if not dest_path.exists():
                dest_path = project_dir / "drafts" / f"{sc['id']}_draft.png"

            if not dest_path.exists():
                console.print(f"[yellow]Warning: Scene image for {sc['id']} not found. Skipping.[/yellow]")
                continue

            duration = (sc["end_ms"] - sc["start_ms"]) / 1000.0
            if duration <= 0:
                duration = 2.0

            safe_path = str(dest_path.absolute()).replace("\\", "/")
            concat_lines.append(f"file '{safe_path}'")
            concat_lines.append(f"duration {duration}")

        if not concat_lines:
            console.print("[bold red]Error:[/bold red] No scene images found to export.")
            raise typer.Exit(code=1)

        # Repetir o último arquivo (requisito do ffmpeg concat)
        concat_lines.append(concat_lines[-2])

        concat_path = project_dir / "input.txt"
        concat_path.write_text("\n".join(concat_lines), encoding="utf-8")

        output_video = project_dir / "exports" / "output.mp4"
        output_video.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(ffmpeg_bin.absolute()),
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_path.absolute()),
            "-i", str(audio_path.absolute()),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-vf", "scale=1280:720",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-shortest",
            str(output_video.absolute())
        ]

        console.print("[yellow]Running ffmpeg to generate MP4 video...[/yellow]")
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if result.returncode == 0:
            console.print(
                Panel(
                    f"[bold green]Video Export Complete![/bold green]\n\n"
                    f"[bold]Output Video:[/bold] {output_video.absolute()}",
                    title="Success",
                    border_style="green",
                )
            )
        else:
            console.print(f"[bold red]FFmpeg failed with exit code {result.returncode}:[/bold red]\n{result.stderr}")
            raise typer.Exit(code=1)
    else:
        console.print(f"Format '{format_str}' is staged for development.")


@app.command()
def run(
    audio_path_str: str = typer.Argument(..., metavar="AUDIO_FILE", help="Path to input audio file"),
) -> None:
    """Convenience shortcut to run full pipeline up to human review gate."""
    load_dotenv()
    project_dir = Path("./project_run")
    runner = CliRunner()
    # Execute commands in sequence
    runner.invoke(app, ["init", audio_path_str, "--output", str(project_dir)])
    runner.invoke(app, ["analyze", str(project_dir)])
    runner.invoke(app, ["bible", str(project_dir)])
    runner.invoke(app, ["render", str(project_dir), "--stage", "draft"])



if __name__ == "__main__":
    app()
