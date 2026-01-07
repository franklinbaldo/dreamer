"""Service for interacting with the Google Gemini API."""

import base64
import mimetypes
from pathlib import Path

from google import genai
from google.genai import types
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .models import AnalysisConfig, ImageGenerationConfig, Storyboard


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

    def analyze_audio(
        self,
        audio_path: Path,
        config: AnalysisConfig | None = None,
    ) -> Storyboard:
        """Phase 1: Analyzes audio to create a textual production design and storyboard.

        Args:
            audio_path: Path to the audio file.
            config: Configuration for analysis.

        Returns:
            Storyboard: The generated storyboard.

        Raises:
            RuntimeError: If the analysis fails.
            ValueError: If audio format is not supported.

        """
        if config is None:
            config = AnalysisConfig()
        # Read and encode audio
        with audio_path.open("rb") as f:
            audio_data = f.read()

        # Determine mime type
        mime_type, _ = mimetypes.guess_type(audio_path)
        if not mime_type or not mime_type.startswith("audio/"):
            # Fallback based on extension or error out if critical
            # For now, let's trust the user if it looks like audio,
            # but 'audio/wav' as safe default
            # The prompt suggested validating formats.
            if audio_path.suffix.lower() == ".mp3":
                mime_type = "audio/mpeg"
            else:
                mime_type = "audio/wav"

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
                model=config.model,
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
                    temperature=config.temperature,
                ),
            )

            storyboard = None
            if hasattr(response, "parsed") and response.parsed:
                storyboard = response.parsed
            else:
                storyboard = Storyboard.model_validate_json(response.text)

            # Sort scenes by timestamp defensively
            if storyboard and storyboard.scenes:
                storyboard.scenes.sort(key=lambda s: s.timestamp)

        except Exception as e:
            msg = f"Failed to interpret audio storyboard: {e}"
            raise RuntimeError(msg) from e

        return storyboard

    def _save_image(self, data: bytes, output_path: Path) -> str:
        # Create directory if it doesn't exist
        output_path.parent.mkdir(parents=True, exist_ok=True)
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

        if response.candidates and response.candidates[0].content.parts:
            part = response.candidates[0].content.parts[0]
            if part.inline_data:
                img_bytes = base64.b64decode(part.inline_data.data)
                return self._save_image(img_bytes, output_path)

        msg = "No image data in response"
        raise RuntimeError(msg)

    def generate_image(
        self,
        prompt: str,
        config: ImageGenerationConfig | None = None,
        reference_image_paths: list[str] | None = None,
        output_path: Path | None = None,
    ) -> str | None:
        """Generate an image using the Gemini API.

        Args:
            prompt: Text prompt for image generation.
            config: Configuration for image generation.
            reference_image_paths: List of paths to reference images.
            output_path: Path to save the generated image.

        Returns:
            str: The path to the saved image.

        Raises:
            RetryError: If generation fails after retries.

        """
        if config is None:
            config = ImageGenerationConfig()
        if reference_image_paths is None:
            reference_image_paths = []
        parts = []

        for ref_path_str in reference_image_paths:
            ref_path = Path(ref_path_str)
            if ref_path_str and ref_path.exists():
                with ref_path.open("rb") as f:
                    img_data = f.read()
                parts.append(
                    types.Part.from_bytes(data=img_data, mime_type="image/png"),
                )

        parts.append(types.Part.from_text(text=prompt))

        # Use tenacity Retrying context manager for dynamic retry config
        # reraise=True so the underlying exception is raised after retries
        retryer = Retrying(
            stop=stop_after_attempt(config.retries + 1),
            wait=wait_exponential(
                multiplier=2,
                min=config.min_wait,
                max=config.max_wait,
            ),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        )

        def _attempt() -> str:
            return self._generate_image_attempt(config.model, parts, output_path)

        return retryer(_attempt)
