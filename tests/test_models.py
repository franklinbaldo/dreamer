"""Tests for the Pydantic models."""

from src.dreamer.models import ProductionDesign, Scene, Storyboard, VisualElement


def test_models_instantiation() -> None:
    element = VisualElement(name="Hero", description="A brave hero")
    assert element.name == "Hero"
    assert element.description == "A brave hero"
    assert element.image_url is None

    design = ProductionDesign(art_style="Cyberpunk", recurring_elements=[element])
    assert design.art_style == "Cyberpunk"
    assert len(design.recurring_elements) == 1

    scene = Scene(
        timestamp=10.5,
        timing_rationale="Intro",
        description="Hero enters",
        visual_prompt="Hero walking in rain",
    )
    assert scene.timestamp == 10.5

    storyboard = Storyboard(title="My Movie", production_design=design, scenes=[scene])
    assert storyboard.title == "My Movie"
    assert len(storyboard.scenes) == 1
