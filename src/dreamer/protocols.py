"""Defines interface protocols for Dreamer V2 components."""

from pathlib import Path
from typing import Protocol

from dreamer.models import AnalysisResponse


class AudioAnalyzer(Protocol):
    """Protocol for audio analysis components."""

    def analyze(
        self,
        audio_path: Path,
        model: str,
        mode: str,
    ) -> tuple[AnalysisResponse, int, int]:
        """Analyze the audio file.

        Returns:
            A tuple of (AnalysisResponse, input_tokens, output_tokens).

        """
        ...



class ImageRenderer(Protocol):
    """Protocol for single-image rendering components."""

    def render_single(
        self,
        prompt: str,
        reference_images: list[Path],
        resolution: str,
        model: str,
    ) -> bytes:
        """Render a single image with optional references."""
        ...


class BatchImageRenderer(Protocol):
    """Protocol for batch image rendering components."""

    def render_batch(
        self,
        prompts: list[str],
        reference_images: list[Path],
        resolution: str,
        model: str,
    ) -> list[bytes]:
        """Render multiple images in parallel."""
        ...
