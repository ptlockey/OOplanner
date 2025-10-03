# OOplanner
Design OO gauge layout based on user selectable board shape and size
The user designs the board and the code returns possible layout options based on user selectable variables such as maximising track density, maximising straights, loops etc

## Running the planner

1. Install the dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Launch the Streamlit interface:

   ```bash
   streamlit run app.py
   ```

3. Open the provided local URL in your browser to explore layout suggestions based on your board and priorities.

## Layout JSON format

You can back up and reload plans via the sidebar uploader/downloader or the **Save layout** button in the canvas. Layout files
use UTF-8 encoded JSON with the following structure:

```json
{
  "placements": [
    {
      "id": "placement-0",
      "code": "R600",
      "x": 1200.0,
      "y": 600.0,
      "rotation": 0.0,
      "flipped": false
    }
  ],
  "board": {
    "description": "Rectangle · 1800 mm × 1200 mm",
    "polygon": [[0, 0], [1800, 0], [1800, 1200], [0, 1200]]
  },
  "zoom": 1.0
}
```

Each entry in `placements` records the catalogue `code` for the track piece alongside its position (`x`, `y` in millimetres),
orientation (`rotation` in degrees) and whether it is `flipped`. The optional `id` field uniquely identifies the piece for
the editor; if omitted it will be regenerated on import. Additional top-level fields such as `board` and `zoom` are preserved
when present so you can restore a plan exactly as you left it.
