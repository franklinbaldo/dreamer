import os
import base64
import time
from pathlib import Path
from typing import List, Optional

from rich.console import Console
from google import genai
from google.genai import types

from .models import Storyboard

console = Console()

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
