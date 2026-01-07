"""Service for interacting with the Google Gemini API."""

import base64
from pathlib import Path

from google import genai
from google.genai import types
from rich.console import Console
from tenacity import (
    RetryError,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .models import Storyboard

console = Console()


class GeminiService:
    """Service to interact with Google Gemini API."""

    def __init__(self, api_key: str) -> None:
        """Initialize the service with an API key."""
        if not api_key:
            msg = (
                "API Key is missing. "
                "Set GEMINI_API_KEY env var or pass it as an argument."
            )
            raise ValueError(msg)
        self.client = genai.Client(api_key=api_key)

    def analyze_audio(self, audio_path: Path) -> Storyboard:
        """Phase 1: Analyzes audio to create a textual production design and storyboard.

        Args:
            audio_path: Path to the audio file.

        Returns:
            Storyboard: The generated storyboard.

        Raises:
            RuntimeError: If the analysis fails.

        """
        # Read and encode audio
        with audio_path.open("rb") as f:
            audio_data = f.read()

        # Determine mime type based on extension
        mime_type = "audio/mpeg" if audio_path.suffix.lower() == ".mp3" else "audio/wav"

        prompt = (
            "You are a world-class production designer.\n"
            "Listen to this audio and plan a highly COHERENT visual experience.\n\n"
            "PHASE 1: VISUAL DESIGN\n"
            "Define a consistent 'art_style'.\n"
            "Identify 'recurring_elements' (characters/objects). "
            "Provide a detailed description for each.\n\n"
            "PHASE 2: STORYBOARDING\n"
            "Create scenes precisely synchronized with the audio.\n"
            "For each scene, provide a 'visual_prompt' that references "
            "the 'recurring_elements' by name."
        )

        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",  # Using 2.5 Flash for audio analysis
                contents=[
                    types.Content(
                        parts=[
                            types.Part.from_bytes(data=audio_data, mime_type=mime_type),
                            types.Part.from_text(text=prompt),
                        ],
                    ),
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=Storyboard,  # Pass the Pydantic class directly
                    temperature=0.4,
                ),
            )

            # The SDK handles parsing into the Pydantic model automatically
            # if supported, otherwise we parse the text.
            if hasattr(response, "parsed") and response.parsed:
                return response.parsed
            return Storyboard.model_validate_json(response.text)
        except Exception as e:
            msg = f"Failed to interpret audio storyboard: {e}"
            raise RuntimeError(msg) from e

    def _save_image(self, data: bytes, output_path: Path) -> str:
        with output_path.open("wb") as f:
            f.write(data)
        return str(output_path)

    def _generate_image_attempt(
        self,
        model_name: str,
        parts: list[types.Part],
        output_path: Path,
    ) -> str:
        response = self.client.models.generate_content(
            model=model_name,
            contents=[types.Content(parts=parts)],
            config=types.GenerateContentConfig(response_mime_type="image/png"),
        )

        if response.bytes:
            return self._save_image(response.bytes, output_path)

        # Fallback for some models that return base64 inside inlineData
        if response.candidates and response.candidates[0].content.parts:
            part = response.candidates[0].content.parts[0]
            if part.inline_data:
                img_bytes = base64.b64decode(part.inline_data.data)
                return self._save_image(img_bytes, output_path)

        msg = "No image data in response"
        raise RuntimeError(msg)
        return ""  # Should be unreachable

    def generate_image(
        self,
        prompt: str,
        reference_image_paths: list[str] | None = None,
        output_path: Path | None = None,
        retries: int = 2,
    ) -> str | None:
        """Generate an image using the Gemini API.

        If reference_image_paths are provided, they are sent as context to the model
        (Requires a model that supports Image-to-Image or Multimodal input).

        Args:
            prompt: Text prompt for image generation.
            reference_image_paths: List of paths to reference images.
            output_path: Path to save the generated image.
            retries: Number of retries on failure.

        Returns:
            str | None: The path to the saved image or None if failed.

        """
        if reference_image_paths is None:
            reference_image_paths = []
        parts = []

        # Load reference images
        for ref_path_str in reference_image_paths:
            ref_path = Path(ref_path_str)
            if ref_path_str and ref_path.exists():
                with ref_path.open("rb") as f:
                    img_data = f.read()
                parts.append(
                    types.Part.from_bytes(data=img_data, mime_type="image/png"),
                )

        parts.append(types.Part.from_text(text=prompt))
        model_name = "gemini-2.5-flash-image"

        try:
            # Use tenacity Retrying context manager for dynamic retry config
            # reraise=False means it raises RetryError on failure
            retryer = Retrying(
                stop=stop_after_attempt(retries + 1),
                wait=wait_exponential(multiplier=2, min=2, max=10),
                retry=retry_if_exception_type(Exception),
                reraise=False,
            )

            def _attempt() -> str:
                return self._generate_image_attempt(model_name, parts, output_path)

            return retryer(_attempt)

        except RetryError as e:
            # RetryError wraps the last exception
            original_exception = e.last_attempt.exception()
            console.print(
                f"[yellow]Warning: Failed to generate image after retries: "
                f"{original_exception}[/yellow]",
            )
            return None
