# Dreamer - SonicVision Studio CLI

**Dreamer** is a powerful Python CLI tool that transforms audio files into synchronized visual storyboards. By leveraging Google Gemini's advanced multimodal capabilities, it analyzes audio content to generate coherent narratives, consistent character designs, and fully rendered scenes.

## Features

- **Phase 1: Audio Analysis**
  - Listens to audio input (MP3/WAV) to understand context, mood, and narrative.
  - Generates a structured storyboard with titles, art styles, and scene breakdowns.
  - Timestamps scenes based on audio cues.

- **Phase 2: Character & Element Design**
  - Identifies recurring characters and visual elements.
  - Generates reference images (character sheets) to maintain visual consistency throughout the storyboard.

- **Phase 3: Scene Production**
  - Renders individual scene images using the generated storyboard and reference assets.
  - Ensures style consistency across all frames.

## Prerequisites

- **Python 3.12+**
- **Google Gemini API Key** (with access to `gemini-1.5-pro` and `imagen-3.0-generate-001`)
- **uv** (Python package manager)

## Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd <repository_name>
    ```

2.  **Install dependencies using `uv`:**
    ```bash
    uv sync
    ```

## Configuration

You need a Google Gemini API key to run the application.

1.  **Environment Variable:**
    Set the `GEMINI_API_KEY` environment variable in your terminal:
    ```bash
    export GEMINI_API_KEY="your_api_key_here"
    ```

2.  **`.env` File:**
    Alternatively, create a `.env` file in the project root:
    ```env
    GEMINI_API_KEY=your_api_key_here
    ```

## Usage

Run the CLI using `uv`:

```bash
uv run dreamer generate <path_to_audio_file> [OPTIONS]
```

### Arguments

- `audio_file`: Path to the input audio file (supported formats: `.mp3`, `.wav`).

### Options

- `--output-dir`: Directory to save the generated assets (default: `./output`).
- `--api-key`: Explicitly pass the API key (overrides environment variable).
- `--help`: Show the help message.

### Example

```bash
uv run dreamer generate ./input/story.mp3 --output-dir ./results/story_board
```

## Output Structure

The tool generates the following artifacts in the output directory:

```text
output/
├── elements/           # Reference images for characters/objects
│   ├── hero.png
│   └── artifact.png
├── scenes/             # Generated scene images
│   ├── scene_000_00.0s.png
│   ├── scene_001_15.5s.png
│   └── ...
├── storyboard.json     # Initial storyboard metadata
└── storyboard_final.json # Final manifest with image paths
```

## Development

This project uses `uv` for dependency management and `hatchling` for building.

- **Run Tests:**
  ```bash
  uv run pytest
  ```

- **Linting & Formatting:**
  ```bash
  uv run ruff check
  ```
