from typing import List, Optional
from pydantic import BaseModel

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
