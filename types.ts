
export interface VisualElement {
  name: string;
  description: string;
  imageUrl?: string;
}

export interface Scene {
  timestamp: number;
  description: string;
  visual_prompt: string;
  timing_rationale: string;
  imageUrl?: string;
}

export enum AppState {
  IDLE = 'IDLE',
  ANALYZING = 'ANALYZING',
  DESIGNING_ELEMENTS = 'DESIGNING_ELEMENTS',
  GENERATING_IMAGES = 'GENERATING_IMAGES',
  READY = 'READY',
  ERROR = 'ERROR'
}

export interface Storyboard {
  title: string;
  production_design: {
    art_style: string;
    recurring_elements: VisualElement[];
  };
  scenes: Scene[];
}
