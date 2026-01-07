"""Pydantic data models for the SonicVision Studio."""

from pydantic import BaseModel, model_validator


class VisualElement(BaseModel):
    """Represents a visual element (character or object)."""

    name: str
    description: str
    image_url: str | None = None  # Stores local path in CLI version


class Scene(BaseModel):
    """Represents a scene in the storyboard."""

    timestamp: float
    timing_rationale: str
    description: str
    visual_prompt: str
    image_url: str | None = None  # Stores local path


class ProductionDesign(BaseModel):
    """Represents the overall production design."""

    art_style: str
    recurring_elements: list[VisualElement]


class Storyboard(BaseModel):
    """Represents the complete storyboard."""

    title: str
    production_design: ProductionDesign
    scenes: list[Scene]

    @model_validator(mode="after")
    def sort_scenes(self) -> "Storyboard":
        """Sort scenes by timestamp."""
        self.scenes.sort(key=lambda s: s.timestamp)
        return self


class AnalysisConfig(BaseModel):
    """Configuration for audio analysis."""

    model: str = "gemini-1.5-pro"
    temperature: float = 0.4


class ImageGenerationConfig(BaseModel):
    """Configuration for image generation."""

    model: str = "imagen-3.0-generate-001"
    retries: int = 2
    min_wait: int = 2
    max_wait: int = 10
