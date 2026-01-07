import typer
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.panel import Panel
from dotenv import load_dotenv

from .service import GeminiService

# Load environment variables
load_dotenv()

# Setup Typer and Console
app = typer.Typer(help="SonicVision Studio CLI - Audio to Visual Storyboard")
console = Console()

@app.command()
def generate(
    audio_file: Path = typer.Argument(..., help="Path to the input audio file (mp3/wav)"),
    output_dir: Path = typer.Option(Path("./output"), help="Directory to save results"),
    api_key: str = typer.Option(None, envvar="GEMINI_API_KEY", help="Google Gemini API Key"),
):
    """
    Transform audio into a synchronized visual storyboard using Gemini.
    """

    if not audio_file.exists():
        console.print(f"[bold red]Error:[/bold red] File {audio_file} not found.")
        raise typer.Exit(code=1)

    # Setup directories
    output_dir.mkdir(parents=True, exist_ok=True)
    elements_dir = output_dir / "elements"
    elements_dir.mkdir(exist_ok=True)
    scenes_dir = output_dir / "scenes"
    scenes_dir.mkdir(exist_ok=True)

    try:
        service = GeminiService(api_key)

        # --- Phase 1: Analyze Audio ---
        console.rule("[bold blue]Phase 1: Audio Analysis")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Listening and Storyboarding...", total=None)
            storyboard = service.analyze_audio(audio_file)
            progress.update(task, completed=100)

        console.print(Panel(
            f"[bold]Title:[/bold] {storyboard.title}\n"
            f"[bold]Style:[/bold] {storyboard.production_design.art_style}\n"
            f"[bold]Scenes:[/bold] {len(storyboard.scenes)} detected",
            title="Storyboard Generated",
            border_style="green"
        ))

        # Save JSON metadata
        with open(output_dir / "storyboard.json", "w") as f:
            f.write(storyboard.model_dump_json(indent=2))

        # --- Phase 2: Design Elements ---
        console.rule("[bold purple]Phase 2: Character & Element Design")

        elements = storyboard.production_design.recurring_elements
        ref_image_paths = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            console=console
        ) as progress:
            task = progress.add_task("Generating References...", total=len(elements))

            for el in elements:
                safe_name = "".join([c for c in el.name if c.isalnum() or c in (' ', '-', '_')]).strip().replace(' ', '_')
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
                    el.imageUrl = saved_path
                    ref_image_paths.append(saved_path)

                progress.advance(task)

        # --- Phase 3: Scene Generation ---
        console.rule("[bold cyan]Phase 3: Scene Production")

        scenes = storyboard.scenes

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            console=console
        ) as progress:
            task = progress.add_task("Rendering Scenes...", total=len(scenes))

            for i, scene in enumerate(scenes):
                timestamp_str = f"{scene.timestamp:06.1f}".replace('.', '_')
                img_path = scenes_dir / f"scene_{i:03d}_{timestamp_str}s.png"

                scene_prompt = (
                    f"Using the provided visual references for character/element consistency "
                    f"and following the style '{storyboard.production_design.art_style}', "
                    f"create this scene: {scene.visual_prompt}. "
                    f"Maintain perfect visual coherence with the references."
                )

                # Generate with references
                saved_path = service.generate_image(
                    prompt=scene_prompt,
                    reference_image_paths=ref_image_paths, # Sending references!
                    output_path=img_path
                )

                if saved_path:
                    scene.imageUrl = saved_path

                progress.advance(task)

        # Update JSON with image paths
        with open(output_dir / "storyboard_final.json", "w") as f:
            f.write(storyboard.model_dump_json(indent=2))

        console.rule("[bold green]Production Complete")
        console.print(f"Output saved to: [underline]{output_dir.absolute()}[/underline]")
        console.print("Check 'storyboard_final.json' for the complete timeline.")

    except Exception as e:
        console.print(f"[bold red]Fatal Error:[/bold red] {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
