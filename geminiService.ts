
import { GoogleGenAI, Type } from "@google/genai";
import { Scene, Storyboard } from "./types";

const API_KEY = process.env.API_KEY || "";

export class GeminiService {
  private ai: GoogleGenAI;

  constructor() {
    this.ai = new GoogleGenAI({ apiKey: API_KEY });
  }

  /**
   * Phase 1: Analyzes audio to create a textual production design and storyboard.
   */
  async analyzeAudio(audioBase64: string, mimeType: string): Promise<Storyboard> {
    const response = await this.ai.models.generateContent({
      model: "gemini-3-pro-preview",
      contents: [
        {
          inlineData: {
            data: audioBase64,
            mimeType: mimeType
          }
        },
        {
          text: `You are a world-class production designer. 
          Listen to this audio and plan a highly COHERENT visual experience.
          
          PHASE 1: VISUAL DESIGN
          Define a consistent 'art_style'.
          Identify 'recurring_elements' (characters/objects). Provide a detailed description for each.

          PHASE 2: STORYBOARDING
          Create scenes precisely synchronized with the audio.
          For each scene, provide a 'visual_prompt' that references the 'recurring_elements' by name.

          Return JSON:
          - 'title': String
          - 'production_design': { 'art_style', 'recurring_elements': [{ 'name', 'description' }] }
          - 'scenes': [{ 'timestamp', 'timing_rationale', 'description', 'visual_prompt' }]`
        }
      ],
      config: {
        responseMimeType: "application/json",
        responseSchema: {
          type: Type.OBJECT,
          properties: {
            title: { type: Type.STRING },
            production_design: {
              type: Type.OBJECT,
              properties: {
                art_style: { type: Type.STRING },
                recurring_elements: {
                  type: Type.ARRAY,
                  items: {
                    type: Type.OBJECT,
                    properties: {
                      name: { type: Type.STRING },
                      description: { type: Type.STRING }
                    },
                    required: ["name", "description"]
                  }
                }
              },
              required: ["art_style", "recurring_elements"]
            },
            scenes: {
              type: Type.ARRAY,
              items: {
                type: Type.OBJECT,
                properties: {
                  timestamp: { type: Type.NUMBER },
                  timing_rationale: { type: Type.STRING },
                  description: { type: Type.STRING },
                  visual_prompt: { type: Type.STRING }
                },
                required: ["timestamp", "timing_rationale", "description", "visual_prompt"]
              }
            }
          },
          required: ["title", "production_design", "scenes"]
        }
      }
    });

    try {
      const result = JSON.parse(response.text || "{}");
      if (result.scenes) {
        result.scenes.sort((a: any, b: any) => a.timestamp - b.timestamp);
      }
      return result as Storyboard;
    } catch (e) {
      throw new Error("Failed to interpret audio storyboard.");
    }
  }

  /**
   * Generates a single image (for an element or a scene).
   * If referenceImages (base64) are provided, they are sent as parts to the model.
   */
  async generateImage(prompt: string, referenceImages: string[] = [], retries = 2): Promise<string> {
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const parts: any[] = referenceImages.map(img => ({
          inlineData: {
            data: img.split(',')[1] || img,
            mimeType: "image/png"
          }
        }));

        parts.push({ text: prompt });

        const response = await this.ai.models.generateContent({
          model: "gemini-2.5-flash-image",
          contents: { parts },
          config: {
            imageConfig: { aspectRatio: "16:9" }
          }
        });

        const candidate = response.candidates?.[0];
        if (!candidate) throw new Error("No output candidate.");

        for (const part of candidate.content?.parts || []) {
          if (part.inlineData) {
            return `data:image/png;base64,${part.inlineData.data}`;
          }
        }
        throw new Error("No image data in response.");
      } catch (err) {
        if (attempt === retries) throw err;
        await new Promise(r => setTimeout(r, 1500 * (attempt + 1)));
      }
    }
    throw new Error("Generation failed.");
  }
}
