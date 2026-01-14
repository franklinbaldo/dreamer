"""CLI Application for SonicVision Studio."""

import hashlib
import os
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from .models import AnalysisConfig, ImageGenerationConfig, Storyboard
from .service import GeminiService

# Setup Typer and Console
app = typer.Typer(
    name="dreamer",
    help="SonicVision Studio CLI - Audio to Visual Storyboard",
    add_completion=False,
)
console = Console()


@app.callback(invoke_without_command=True)
def main() -> None:
    """SonicVision Studio CLI - Audio to Visual Storyboard."""


def _get_service(api_key: str | None = None) -> GeminiService:
    """Get the Gemini service."""
    load_dotenv()
    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        console.print(
            "[bold red]Error:[/bold red] GEMINI_API_KEY not found in env or arguments.",
        )
        raise typer.Exit(code=1)
    return GeminiService(api_key)


def _analyze_audio(
    service: GeminiService,
    audio_file: Path,
    config: AnalysisConfig,
) -> Storyboard:
    console.rule("[bold blue]Phase 1: Audio Analysis")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Listening and Storyboarding...", total=None)
        storyboard = service.analyze_audio(
            audio_file,
            config=config,
        )
        progress.update(task, completed=100)

    console.print(
        Panel(
            f"[bold]Title:[/bold] {storyboard.title}\n"
            f"[bold]Style:[/bold] {storyboard.production_design.art_style}\n"
            f"[bold]Scenes:[/bold] {len(storyboard.scenes)} detected",
            title="Storyboard Generated",
            border_style="green",
        ),
    )
    return storyboard


def _generate_elements(
    service: GeminiService,
    storyboard: Storyboard,
    elements_dir: Path,
    config: ImageGenerationConfig,
) -> list[str]:
    console.rule("[bold purple]Phase 2: Character & Element Design")

    elements = storyboard.production_design.recurring_elements
    ref_image_paths = []
    elements_dir.mkdir(parents=True, exist_ok=True)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("Generating References...", total=len(elements))

        for el in elements:
            safe_name = (
                "".join(
                    [c for c in el.name if c.isalnum() or c in (" ", "-", "_")],
                )
                .strip()
                .replace(" ", "_")
            )
            img_path = elements_dir / f"{safe_name}.png"

            # Skip if image already exists
            if img_path.exists():
                el.image_url = str(img_path)
                ref_image_paths.append(str(img_path))
                progress.advance(task)
                continue

            prompt = (
                f"Production Design: Element Reference Sheet. "
                f"Style: {storyboard.production_design.art_style}. "
                f"Subject: {el.name}. "
                f"Description: {el.description}. "
                f"Show only this subject against a neutral background for reference."
            )

            # Generate
            try:
                saved_path = service.generate_image(
                    prompt,
                    output_path=img_path,
                    config=config,
                )

                if saved_path:
                    el.image_url = str(saved_path)
                    ref_image_paths.append(str(saved_path))
            except Exception as e:  # noqa: BLE001
                console.print(
                    f"[yellow]Warning: Failed to generate element "
                    f"'{el.name}': {e}[/yellow]",
                )

            progress.advance(task)
    return ref_image_paths


def _render_scenes(
    service: GeminiService,
    storyboard: Storyboard,
    scenes_dir: Path,
    ref_image_paths: list[str],
    config: ImageGenerationConfig,
) -> None:
    console.rule("[bold cyan]Phase 3: Scene Production")

    scenes = storyboard.scenes
    scenes_dir.mkdir(parents=True, exist_ok=True)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("Rendering Scenes...", total=len(scenes))

        for i, scene in enumerate(scenes):
            timestamp_str = f"{scene.timestamp:06.1f}".replace(".", "_")
            img_path = scenes_dir / f"scene_{i:03d}_{timestamp_str}s.png"

            if img_path.exists():
                scene.image_url = str(img_path)
                progress.advance(task)
                continue

            scene_prompt = (
                "Using the provided visual references for "
                "character/element consistency "
                f"and following the style '{storyboard.production_design.art_style}', "
                f"create this scene: {scene.visual_prompt}. "
                "Maintain perfect visual coherence with the references."
            )

            # Generate with references
            try:
                saved_path = service.generate_image(
                    prompt=scene_prompt,
                    reference_image_paths=ref_image_paths,
                    output_path=img_path,
                    config=config,
                )

                if saved_path:
                    scene.image_url = str(saved_path)
            except Exception as e:  # noqa: BLE001
                console.print(
                    f"[yellow]Warning: Failed to generate scene {i}: {e}[/yellow]",
                )

            progress.advance(task)


@app.command()
def generate(
    audio_file_str: str = typer.Argument(
        ...,
        metavar="AUDIO_FILE",
        help="Path to the input audio file (mp3/wav/etc)",
    ),
    output_dir: Path = typer.Option(
        Path("./output"),
        help="Directory to save generated assets",
    ),
    api_key: str | None = typer.Option(
        None,
        envvar="GEMINI_API_KEY",
        help="Google Gemini API Key",
    ),
    analysis_model: str = typer.Option(
        "gemini-1.5-pro",
        "--analysis-model",
        help="Gemini model for audio analysis",
    ),
    temperature: float = typer.Option(
        0.4,
        help="Temperature for creative analysis",
    ),
    image_model: str = typer.Option(
        "imagen-3.0-generate-001",
        "--image-model",
        help="Model for image generation",
    ),
    retries: int = typer.Option(2, help="Number of retries for image generation"),
    min_wait: int = typer.Option(2, help="Minimum wait time between retries"),
    max_wait: int = typer.Option(10, help="Maximum wait time between retries"),
) -> None:
    """
    Transform audio into a synchronized visual storyboard.

    This command orchestrates the entire pipeline:
    1.  Analyzes audio to create a storyboard (if none exists).
    2.  Generates reference images for characters and elements.
    3.  Renders each scene based on the storyboard and references.

    If a 'storyboard.json' is found in the output directory, it resumes
    from the last completed step, avoiding redundant processing.
    """
    audio_file = Path(audio_file_str)
    if not audio_file.exists():
        console.print(f"[bold red]Error:[/bold red] File {audio_file} not found.")
        raise typer.Exit(code=1)

    supported_formats = [".mp3", ".wav", ".flac", ".aac", ".ogg"]
    if audio_file.suffix.lower() not in supported_formats:
        console.print(
            f"[bold red]Error:[/bold red] Unsupported audio format: "
            f"'{audio_file.suffix}'. Supported formats are: "
            f"{', '.join(supported_formats)}",
        )
        raise typer.Exit(code=1)

    # Setup directories and paths
    output_dir.mkdir(parents=True, exist_ok=True)
    storyboard_path = output_dir / "storyboard.json"
    final_storyboard_path = output_dir / "storyboard_final.json"
    elements_dir = output_dir / "elements"
    scenes_dir = output_dir / "scenes"

    try:
        service = _get_service(api_key)

        analysis_config = AnalysisConfig(model=analysis_model, temperature=temperature)
        image_config = ImageGenerationConfig(
            model=image_model,
            retries=retries,
            min_wait=min_wait,
            max_wait=max_wait,
        )

        # Phase 1: Analysis (or load existing)
        if storyboard_path.exists():
            console.print(f"Found existing storyboard at {storyboard_path}, resuming...")
            with storyboard_path.open("r") as f:
                storyboard = Storyboard.model_validate_json(f.read())
        else:
            storyboard = _analyze_audio(
                service,
                audio_file,
                config=analysis_config,
            )
            # Save initial storyboard
            with storyboard_path.open("w") as f:
                f.write(storyboard.model_dump_json(indent=2))
            console.print(f"Storyboard saved to {storyboard_path}")

        # Phase 2: Element Generation
        ref_image_paths = _generate_elements(
            service,
            storyboard,
            elements_dir,
            config=image_config,
        )
        # Update storyboard with element image paths and save
        with storyboard_path.open("w") as f:
            f.write(storyboard.model_dump_json(indent=2))

        # Phase 3: Scene Rendering
        _render_scenes(
            service,
            storyboard,
            scenes_dir,
            ref_image_paths,
            config=image_config,
        )

        # Save final manifest with all image URLs
        with final_storyboard_path.open("w") as f:
            f.write(storyboard.model_dump_json(indent=2))

        console.rule("[bold green]Production Complete")
        console.print(f"Output saved to: [underline]{output_dir.absolute()}[/underline]")

    except Exception as e:
        console.print(f"[bold red]Fatal Error:[/bold red] {e}")
        raise typer.Exit(code=1) from e


# Jules Integration
try:
    from jules.cli import app as jules_app
    app.add_typer(jules_app, name="jules")
except ImportError:
    pass


if __name__ == "__main__":
    app()
