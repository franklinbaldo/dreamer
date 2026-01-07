"""CLI Application for SonicVision Studio."""

from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from .models import Storyboard
from .service import GeminiService

# Load environment variables
load_dotenv()

# Setup Typer and Console
app = typer.Typer(help="SonicVision Studio CLI - Audio to Visual Storyboard")
console = Console()


def _analyze_audio(service: GeminiService, audio_file: Path) -> Storyboard:
    console.rule("[bold blue]Phase 1: Audio Analysis")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Listening and Storyboarding...", total=None)
        storyboard = service.analyze_audio(audio_file)
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
) -> list[str]:
    console.rule("[bold purple]Phase 2: Character & Element Design")

    elements = storyboard.production_design.recurring_elements
    ref_image_paths = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("Generating References...", total=len(elements))

        for el in elements:
            safe_name = "".join(
                [c for c in el.name if c.isalnum() or c in (" ", "-", "_")],
            ).strip().replace(" ", "_")
            img_path = elements_dir / f"{safe_name}.png"

            prompt = (
                f"Production Design: Element Reference Sheet. "
                f"Style: {storyboard.production_design.art_style}. "
                f"Subject: {el.name}. "
                f"Description: {el.description}. "
                f"Show only this subject against a neutral background for reference."
            )

            # Generate
            saved_path = service.generate_image(prompt, output_path=img_path)

            if saved_path:
                el.image_url = saved_path
                ref_image_paths.append(saved_path)

            progress.advance(task)
    return ref_image_paths


def _render_scenes(
    service: GeminiService,
    storyboard: Storyboard,
    scenes_dir: Path,
    ref_image_paths: list[str],
) -> None:
    console.rule("[bold cyan]Phase 3: Scene Production")

    scenes = storyboard.scenes

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

            scene_prompt = (
                f"Using the provided visual references for "
                f"character/element consistency "
                f"and following the style '{storyboard.production_design.art_style}', "
                f"create this scene: {scene.visual_prompt}. "
                f"Maintain perfect visual coherence with the references."
            )

            # Generate with references
            saved_path = service.generate_image(
                prompt=scene_prompt,
                reference_image_paths=ref_image_paths,  # Sending references!
                output_path=img_path,
            )

            if saved_path:
                scene.image_url = saved_path

            progress.advance(task)


@app.command()
def generate(
    audio_file: Path = typer.Argument(
        ...,
        help="Path to the input audio file (mp3/wav)",
    ),
    output_dir: Path = typer.Option(Path("./output"), help="Directory to save results"),
    api_key: str = typer.Option(
        None,
        envvar="GEMINI_API_KEY",
        help="Google Gemini API Key",
    ),
) -> None:
    """Transform audio into a synchronized visual storyboard using Gemini."""
    if not audio_file.exists():
        console.print(f"[bold red]Error:[/bold red] File {audio_file} not found.")
        raise typer.Exit(code=1)

    # Setup directories
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "elements").mkdir(exist_ok=True)
    (output_dir / "scenes").mkdir(exist_ok=True)

    try:
        service = GeminiService(api_key)

        storyboard = _analyze_audio(service, audio_file)

        # Save JSON metadata
        with (output_dir / "storyboard.json").open("w") as f:
            f.write(storyboard.model_dump_json(indent=2))

        ref_image_paths = _generate_elements(
            service,
            storyboard,
            output_dir / "elements",
        )

        _render_scenes(service, storyboard, output_dir / "scenes", ref_image_paths)

        # Update JSON with image paths
        with (output_dir / "storyboard_final.json").open("w") as f:
            f.write(storyboard.model_dump_json(indent=2))

        console.rule("[bold green]Production Complete")
        console.print(
            f"Output saved to: [underline]{output_dir.absolute()}[/underline]",
        )
        console.print("Check 'storyboard_final.json' for the complete timeline.")

    except Exception as e:
        console.print(f"[bold red]Fatal Error:[/bold red] {e}")
        raise typer.Exit(code=1) from e


if __name__ == "__main__":
    app()  # pragma: no cover
