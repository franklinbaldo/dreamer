import os
import base64
import json
import time
from typing import List, Optional
from pathlib import Path
from enum import Enum

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.panel import Panel
from rich.json import JSON
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# Load environment variables
load_dotenv()

# Setup Typer and Console
app = typer.Typer(help="SonicVision Studio CLI - Audio to Visual Storyboard")
console = Console()

# --- Pydantic Schemas (Types) ---

class VisualElement(BaseModel):
    name: str
    description: str
    imageUrl: Optional[str] = None # Stores local path in CLI version

class Scene(BaseModel):
    timestamp: float
    timing_rationale: str
    description: str
    visual_prompt: str
    imageUrl: Optional[str] = None # Stores local path

class ProductionDesign(BaseModel):
    art_style: str
    recurring_elements: List[VisualElement]

class Storyboard(BaseModel):
    title: str
    production_design: ProductionDesign
    scenes: List[Scene]

# --- Gemini Service ---

class GeminiService:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("API Key is missing. Set GEMINI_API_KEY env var or pass it as an argument.")
        self.client = genai.Client(api_key=api_key)

    def analyze_audio(self, audio_path: Path) -> Storyboard:
        """Phase 1: Analyzes audio to create a textual production design and storyboard."""

        # Read and encode audio
        with open(audio_path, "rb") as f:
            audio_data = f.read()

        # Determine mime type based on extension
        mime_type = "audio/mpeg" if audio_path.suffix.lower() == ".mp3" else "audio/wav"

        prompt = """
        You are a world-class production designer.
        Listen to this audio and plan a highly COHERENT visual experience.

        PHASE 1: VISUAL DESIGN
        Define a consistent 'art_style'.
        Identify 'recurring_elements' (characters/objects). Provide a detailed description for each.

        PHASE 2: STORYBOARDING
        Create scenes precisely synchronized with the audio.
        For each scene, provide a 'visual_prompt' that references the 'recurring_elements' by name.
        """

        response = self.client.models.generate_content(
            model="gemini-1.5-pro", # Using 1.5 Pro for best reasoning on audio
            contents=[
                types.Content(
                    parts=[
                        types.Part.from_bytes(data=audio_data, mime_type=mime_type),
                        types.Part.from_text(text=prompt)
                    ]
                )
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=Storyboard, # Pass the Pydantic class directly
                temperature=0.4
            )
        )

        try:
            # The SDK handles parsing into the Pydantic model automatically if supported,
            # otherwise we parse the text.
            if hasattr(response, 'parsed') and response.parsed:
                return response.parsed
            else:
                return Storyboard.model_validate_json(response.text)
        except Exception as e:
            raise RuntimeError(f"Failed to interpret audio storyboard: {e}")

    def generate_image(self, prompt: str, reference_image_paths: List[str] = [], output_path: Path = None, retries: int = 2) -> Optional[str]:
        """
        Generates an image.
        If reference_image_paths are provided, they are sent as context to the model
        (Requires a model that supports Image-to-Image or Multimodal input for generation).
        """

        parts = []

        # Load reference images
        for ref_path in reference_image_paths:
            if ref_path and os.path.exists(ref_path):
                with open(ref_path, "rb") as f:
                    img_data = f.read()
                parts.append(types.Part.from_bytes(data=img_data, mime_type="image/png"))

        parts.append(types.Part.from_text(text=prompt))

        # Note: 'gemini-2.5-flash-image' from the React code is a specific/preview model.
        # Fallback to 'imagen-3.0-generate-001' or 'gemini-2.0-flash' depending on access.
        # Using a model variable here.
        model_name = "imagen-3.0-generate-001"

        for attempt in range(retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=[types.Content(parts=parts)],
                    config=types.GenerateContentConfig(
                        response_mime_type="image/png"
                    )
                )

                if response.bytes:
                    with open(output_path, "wb") as f:
                        f.write(response.bytes)
                    return str(output_path)

                # Fallback for some models that return base64 inside inlineData
                if response.candidates and response.candidates[0].content.parts:
                    part = response.candidates[0].content.parts[0]
                    if part.inline_data:
                        img_bytes = base64.b64decode(part.inline_data.data)
                        with open(output_path, "wb") as f:
                            f.write(img_bytes)
                        return str(output_path)

                raise RuntimeError("No image data in response")

            except Exception as e:
                if attempt == retries:
                    console.print(f"[yellow]Warning: Failed to generate image after retries: {e}[/yellow]")
                    return None
                time.sleep(2 * (attempt + 1))
        return None

# --- CLI Commands ---

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
