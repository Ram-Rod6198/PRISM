# PRISM - Panoramic Recording & Integrated Stream Multiplexer

A desktop GUI application with two modes, both rendered through FFmpeg:

- **Combine** - tile multiple video feeds into one frame (2x2, five-camera and custom layouts)
- **Edit** - cut clips together on a timeline, trim them, and lay another video's audio underneath

Built for users who need a simple visual workflow without opening a full video editor.

![2x2 Layout Demo](video_combiner/assets/images/2x2Demo.png)

![Custom Layout with Text Overlay](video_combiner/assets/images/2And3Demo.png)

## Features

### Edit mode (timeline)

- **Timeline** - add clips and they play one after another; drag a clip to reorder it
- **Trim** - drag either end of a clip, or type exact times in the clip panel
- **Split and remove** - cut a clip at the playhead (`S`) and delete the part you don't want (`Del`)
- **Audio from another video** - drop any video or audio file on the audio track, slide it into place, trim it, set its volume; mute the clips' own sound with one tick
- **Frame preview** - the frame under the playhead, updated as you scrub; Quick Preview renders a small draft and opens it in your player
- **Undo / redo** - every edit, `Ctrl+Z` / `Ctrl+Y`
- **One-click export** - H.264 MP4 at the first clip's size or a chosen frame size, with progress and Cancel

### Combine mode (tiles)

- **Multi-video layouts** - Combine videos into 2x2 4K, 2x2 1080p, 5-camera, and custom tiled layouts
- **Video trimming** - Trim individual clips with precise start/end timecodes
- **Canvas preview** - Visual thumbnail preview of your layout before rendering
- **Per-tile controls** - Adjust position, size, order, timing, and trim per tile
- **Audio mixing** - Mix all audio tracks, use a single tile's audio, or render silent
- **Text overlays** - Add timed text overlays with configurable positioning
- **H.264 export** - Render to MP4 via FFmpeg with full codec control
- **Portable build** - Package as a standalone Windows executable via PyInstaller

## Requirements

- Python 3.10+
- FFmpeg and FFprobe (must be on your system PATH)
- Pillow

### Installing FFmpeg

Download from [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html) and add the `bin` folder to your system PATH.

Verify installation:
```
ffmpeg -version
ffprobe -version
```

## Run From Source

```powershell
git clone https://github.com/Ram-Rod6198/PRISM.git
cd PRISM
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r video_combiner\requirements.txt
.\.venv\Scripts\python.exe Main.py
```

`Main.py --edit` opens straight into Edit mode.

Run the tests (no extra packages needed; the FFmpeg tests skip themselves if FFmpeg is not on PATH):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

## Usage: Edit mode

Open the **Edit (timeline)** tab.

1. **Add Clips** - pick one or more videos. They are appended to the video track in the order chosen.
2. **Arrange** - drag a clip left or right to change the order. Drag a clip's left or right end to trim it. Click a clip and press `S` to split it at the playhead, `Del` to remove the selected clip.
3. **Add Audio** - pick the video (or audio file) whose sound you want. It lands on the audio track at the playhead; drag it to line it up, drag its ends to trim. Adding the first audio clip mutes the clips' own sound; untick *Mute the clips' own audio* to hear both mixed.
4. **Check** - click or drag on the timeline to move the playhead and see that frame. *Quick Preview* renders a fast low-resolution draft and opens it, so you can check the audio against the picture.
5. **Export MP4** - choose where to save. The frame size defaults to the first clip's; clips of a different shape are fitted with black bars. Audio that runs past the last clip is cut off (shown shaded on the timeline).

| Key | Action |
|-----|--------|
| `S` | Split at the playhead |
| `Del` | Remove the selected clip |
| `Ctrl+Z` / `Ctrl+Y` | Undo / redo |
| `Left` / `Right` | Step one frame (`Shift`: one second) |
| `Home` / `End` | Jump to the start / end |
| `Ctrl` + mouse wheel | Zoom the timeline |

The clip panel on the right takes exact times (`HH:MM:SS`, `MM:SS` or seconds) for trim, audio start and volume.

## Usage: Combine mode

### Adding Videos
- Click **Add Video** and select one or more video files
- Videos appear in the list panel on the right with filename and duration
- Thumbnails are automatically generated and displayed on the preview canvas

### Arranging Tiles
- Use **Up/Down** buttons or drag-and-drop to reorder videos in the list
- The first videos in the list map to tiles in the layout (e.g., first 4 for a 2x2 grid)
- Click a tile or list item to open the inspector panel showing coordinates, duration, and controls

### Tile Inspector
- Adjust individual tile position, size, and order
- Set per-tile start/end trim times
- View tile coordinates and mapped video info

### Audio Options
- **Mix all** - Combine audio from all tiles
- **<Tile> only** - Use only that tile's audio track
- **No audio** - Render without audio

### Text Overlays
- Add timed text overlays positioned anywhere on the canvas
- Configure text content, position, and display timing

### Rendering
- Select an output path and click **Render**
- Output is H.264 MP4 via FFmpeg (libx264, yuv420p, CRF 18)
- Output FPS matches the first video in the list
- Shorter videos display black after they end; output duration matches the longest video
- Progress shows in the status bar, with Cancel; **FFmpeg Log** shows the exact command and FFmpeg's output

### Layout Presets
| Preset | Output Resolution | Tile Size |
|--------|-------------------|-----------|
| 2x2 4K | 3840x2160 | 1920x1080 per tile |
| 2x2 1080p | 1920x1080 | 960x540 per tile |
| 5-video | Custom | Mixed sizes |

## Build Portable Windows EXE

Place FFmpeg binaries under `video_combiner/assets/ffmpeg/bin/` then run:

```powershell
.\build_portable.ps1
```

Output is written to `dist/`. Attach the exe or zip to a GitHub Release rather than committing binaries.

## Project Structure

```
PRISM/
  Main.py                        # Entry point
  tests/                         # unittest suite (python -m unittest discover -s tests -t .)
  video_combiner/
    app.py                       # The window: one tab per mode over a shared export bar
    ffmpeg.py                    # All FFmpeg/FFprobe access: load media, still frames, encodes
    export.py                    # ExportBar: runs encodes in the background, progress, cancel, log
    media_picker.py              # "Choose files" dialog that returns only usable media
    timecode.py                  # Parsing and formatting of times
    widgets.py                   # Shared Tk widgets (layer list, scroll area, UI-thread calls)
    combiner/                    # Combine mode
      project.py                 # CombinerProject: tiles, videos, text overlays
      composer.py                # project -> FFmpeg arguments
      presets.py                 # Built-in and saved canvas presets
      workspace.py               # The Combine tab
      preview.py                 # Clickable canvas preview
      inspector.py               # Editors for the selected video / tile / text
      canvas_bar.py              # Preset and canvas-size controls
    editor/                      # Edit mode
      timeline.py                # Timeline: clips, trim, split, reorder, undo
      composer.py                # timeline -> FFmpeg arguments
      workspace.py               # The Edit tab
      timeline_view.py           # Mouse-editable timeline
      frame_preview.py           # Frame under the playhead, fetched in the background
      clip_inspector.py          # Exact trim / start / volume for the selected clip
```

## Architecture

Each mode is a self-contained package with the same three layers:

- **Document** (`CombinerProject`, `Timeline`) - plain Python state plus the rules that keep it valid. No Tk, no FFmpeg.
- **Composer** (`compose(document)`) - turns a document into FFmpeg arguments. A pure function, so it is tested by comparing strings.
- **Workspace** - the Tk tab. Panels edit the document directly and report back with a single "something changed" callback.

Both modes share `ffmpeg.py` (the only module that knows where the binaries are, how to launch them and how to read their output) and `ExportBar` (the only place encodes are run from the UI). Adding a mode means adding a package and one line in `app.py`.

## Tech Stack

Python | Tkinter | FFmpeg | FFprobe | Pillow | PyInstaller

## License

MIT
