"""Pydantic data models for the SonicVision Studio."""

from pydantic import BaseModel


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
