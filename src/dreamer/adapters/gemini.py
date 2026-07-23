"""Google Gemini API adapter implementation."""

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from dreamer.models import AnalysisResponse
from dreamer.protocols import AudioAnalyzer, BatchImageRenderer, ImageRenderer

logger = logging.getLogger(__name__)


class GeminiAdapter(AudioAnalyzer, ImageRenderer, BatchImageRenderer):
    """Adapter for Google Gemini API services."""

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize the Gemini Client."""
        # Client automatically picks up GEMINI_API_KEY from environment if api_key is None
        self.client = genai.Client(api_key=api_key)

    def analyze(
        self,
        audio_path: Path,
        model: str,
        mode: str,
    ) -> tuple[AnalysisResponse, int, int]:
        """Upload audio via Files API, analyze content, and clean up afterwards."""
        if not audio_path.exists():
            msg = f"Audio file not found: {audio_path}"
            raise FileNotFoundError(msg)

        logger.info("Uploading audio file to Gemini Files API: %s", audio_path)
        # Uploading the file
        uploaded_file = self.client.files.upload(file=audio_path)
        logger.info("Uploaded file name: %s", uploaded_file.name)

        prompt = (
            f"You are a world-class production designer. "
            f"Listen to this audio and plan a visual experience in '{mode}' mode.\n\n"
            "PHASE 1: VISUAL STYLE & BIBLE\n"
            "Define an 'art_style'. Identify recurring elements (characters, objects, locations) "
            "with unique IDs, kinds, and descriptions. Define any global visual constraints (colors, rules).\n\n"
            "PHASE 2: STORYBOARDING\n"
            "This is the core: You must transcribe the spoken voiceover or dialogue in the audio segment-by-segment. "
            "For each spoken segment, create a storyboard scene. The scene must have:\n"
            "- 'start_ms' and 'end_ms': The exact start and end times of the spoken voiceover/dialogue segment.\n"
            "- 'audio_cue': The literal transcription of the spoken words in this segment.\n"
            "- 'visual_prompt': A descriptive prompt of what should be drawn/rendered on screen to accompany this spoken text.\n"
            "- 'shot_type', 'camera_angle', 'lighting', 'element_ids': Production design choices that match the segment."
        )

        try:
            logger.info("Analyzing audio with model %s...", model)
            response = self.client.models.generate_content(
                model=model,
                contents=[uploaded_file, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=AnalysisResponse,
                    temperature=0.2,
                ),
            )

            # Extract the structured response
            if hasattr(response, "parsed") and response.parsed:
                result = response.parsed
            else:
                result = AnalysisResponse.model_validate_json(response.text)

            # Track tokens/costs if available in response metadata
            # (In client, response.usage_metadata holds token counts)
            input_tokens = 0
            output_tokens = 0
            if response.usage_metadata:
                input_tokens = response.usage_metadata.prompt_token_count
                output_tokens = response.usage_metadata.candidates_token_count
                logger.info(
                    "Usage: prompt_tokens=%d, candidates_tokens=%d",
                    input_tokens,
                    output_tokens,
                )

            return result, input_tokens, output_tokens

        finally:
            logger.info("Deleting remote file from Gemini Files API: %s", uploaded_file.name)
            try:
                self.client.files.delete(name=uploaded_file.name)
            except Exception:
                logger.exception("Failed to delete uploaded file from Files API")

    def render_single(
        self,
        prompt: str,
        reference_images: list[Path],
        resolution: str,
        model: str,
    ) -> bytes:
        """Render a single image using the Gemini/Imagen model with references."""
        # For gemini-3.1-flash-image / Imagen, we build parts
        parts: list[Any] = []

        # Load reference images
        for ref_path in reference_images:
            if ref_path.exists():
                img_bytes = ref_path.read_bytes()
                parts.append(
                    types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                )

        parts.append(types.Part.from_text(text=prompt))

        # Using generate_content for image models or dedicated Imagen API
        # To match modern 2026 specs and support gemini-3.1-flash-image:
        logger.info("Generating image with prompt: %s (Resolution: %s)", prompt, resolution)

        models_to_try = [model]
        fallbacks = [
            "gemini-3.1-flash-image",
            "gemini-3.1-flash-lite-image",
            "gemini-2.5-flash-image",
            "gemini-3-pro-image",
        ]
        for f in fallbacks:
            if f not in models_to_try:
                models_to_try.append(f)

        last_error = None
        for m in models_to_try:
            backoff = 10
            for attempt in range(4):
                try:
                    logger.info("Attempting generation with model: %s (attempt %d)", m, attempt + 1)
                    if m.startswith("imagen-"):
                        response = self.client.models.generate_images(
                            model=m,
                            prompt=prompt,
                            config=types.GenerateImagesConfig(
                                number_of_images=1,
                                aspect_ratio="16:9" if resolution == "2K" else "1:1",
                                output_mime_type="image/png",
                            )
                        )
                        if response.generated_images:
                            return response.generated_images[0].image.image_bytes
                        msg = "No image data returned from Imagen model"
                        raise RuntimeError(msg)

                    response = self.client.models.generate_content(
                        model=m,
                        contents=parts,
                    )

                    if hasattr(response, "bytes") and response.bytes:
                        return response.bytes

                    if response.candidates and response.candidates[0].content.parts:
                        part = response.candidates[0].content.parts[0]
                        if part.inline_data:
                            return part.inline_data.data

                    msg = "No image data returned from model"
                    raise RuntimeError(msg)
                except Exception as ex:
                    err_str = str(ex).lower()
                    if "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str:
                        logger.warning("Rate limit hit for model %s. Sleeping for %d seconds...", m, backoff)
                        time.sleep(backoff)
                        backoff *= 2
                        last_error = ex
                        continue
                    logger.warning("Model %s failed: %s.", m, ex)
                    last_error = ex
                    break

        msg = f"All models failed. Last error: {last_error}"
        raise RuntimeError(msg)

    def render_batch(
        self,
        prompts: list[str],
        reference_images: list[Path],
        resolution: str,
        model: str,
    ) -> list[bytes]:
        """Render multiple images in parallel using asyncio."""
        async def _run() -> list[bytes]:
            sem = asyncio.Semaphore(4)

            async def _sem_one(p: str) -> bytes:
                async with sem:
                    return await asyncio.to_thread(
                        self.render_single,
                        p,
                        reference_images,
                        resolution,
                        model,
                    )

            tasks = [_sem_one(p) for p in prompts]
            return await asyncio.gather(*tasks)

        return asyncio.run(_run())

