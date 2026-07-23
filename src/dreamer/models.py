"""Pydantic data models for Dreamer V2."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ElementKind(StrEnum):
    """Supported kinds of visual elements."""

    CHARACTER = "character"
    OBJECT = "object"
    LOCATION = "location"


class Element(BaseModel):
    """A recurring visual element in the storyboard."""

    id: str
    kind: ElementKind
    canonical_description: str
    visual_constraints: list[str] = Field(default_factory=list)
    reference_asset_path: str | None = None


class ScenePlan(BaseModel):
    """The plan/intent for a single storyboard scene."""

    id: str
    sequence_id: str
    start_ms: int
    end_ms: int
    audio_cue: str = Field(description="Segmento transcrito ou evento de áudio correspondente")
    narrative_purpose: str = Field(description="Objetivo dramático da cena")
    shot_type: str = Field(description="Ex: Wide Shot, Close-up, Extreme Close-up")
    camera_angle: str = Field(description="Ex: High-angle, Eye-level, Dutch Angle")
    lighting: str = Field(description="Ex: Golden hour, High-key, Moody Dark")
    element_ids: list[str] = Field(default_factory=list, description="IDs dos Elementos presentes na cena")
    visual_prompt: str
    continuity_notes: str | None = None
    depends_on_scene_ids: list[str] = Field(default_factory=list, description="Dependências explícitas de continuidade visual")


class ArtifactStatus(StrEnum):
    """Status of a rendering asset/artifact."""

    PENDING = "pending"
    GENERATING = "generating"
    GENERATED = "generated"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class ArtifactState(BaseModel):
    """Runtime tracking of rendering artifacts."""

    artifact_id: str
    status: ArtifactStatus = ArtifactStatus.PENDING
    path: str | None = None
    content_hash: str | None = None
    error: str | None = None


class ProjectConfig(BaseModel):
    """Project-wide settings (project.toml schema)."""

    name: str
    audio_hash: str
    mode: Literal["narrative", "podcast", "music", "soundscape"] = "narrative"
    aspect_ratio: str = "16:9"
    max_cost_usd: float = 10.0
    audio_analysis_model: str = "gemini-3.5-flash"
    image_generation_model: str = "gemini-3.1-flash-image"
    persist_transcripts: bool = True


class AnalysisResponse(BaseModel):
    """Schema for structured Gemini output during Phase 1."""

    title: str
    art_style: str
    visual_constraints: list[str] = Field(default_factory=list)
    elements: list[Element] = Field(default_factory=list)
    scenes: list[ScenePlan] = Field(default_factory=list)
