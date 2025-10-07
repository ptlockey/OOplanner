from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import streamlit as st
import streamlit.components.v1 as components

from planner import (
    BoardSpecification,
    describe_board,
    hornby_track_library,
    inventory_from_placements,
    layout_resistance_ohms,
    estimate_layout_power,
    total_run_length_mm,
)


_COMPONENT_DIR = Path(__file__).parent / "_layout_designer_component"
_COMPONENT_DIR.mkdir(exist_ok=True)
_COMPONENT_INDEX = _COMPONENT_DIR / "index.html"
_layout_designer_component = components.declare_component(
    "layout_designer",
    path=str(_COMPONENT_DIR),
)


st.set_page_config(page_title="Hornby OO Layout Planner", layout="wide")
st.title("Hornby OO Gauge Layout Planner")
st.write(
    """Lay out your own Hornby OO gauge plan directly on the baseboard outline.\n"
    "Define the board you are building, drag track from the library, rotate or flip pieces,"
    " and snap them together while the planner keeps an eye on inventory and total run length."""
)


def _normalise_layout_payload(
    data: object,
) -> Tuple[List[Dict[str, object]], Optional[float], Optional[Tuple[float, float]]]:
    """Extract placements and optional viewport data from payload."""

    placements_payload: object
    zoom_value: Optional[float] = None
    pan_value: Optional[Tuple[float, float]] = None
    if isinstance(data, dict):
        placements_payload = data.get("placements")
        zoom_raw = data.get("zoom")
        if isinstance(zoom_raw, (int, float)):
            zoom_value = float(zoom_raw)
        pan_raw = data.get("pan")
        if isinstance(pan_raw, dict):
            pan_x = pan_raw.get("x")
            pan_y = pan_raw.get("y")
            if isinstance(pan_x, (int, float)) and isinstance(pan_y, (int, float)):
                pan_value = (float(pan_x), float(pan_y))
    else:
        placements_payload = data

    if not isinstance(placements_payload, list):
        raise ValueError("Layout JSON must contain a list of placements.")

    def _to_float(value: object, default: float = 0.0) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return default
        return default

    normalised: List[Dict[str, object]] = []
    saw_item = False
    for idx, raw_item in enumerate(placements_payload):
        saw_item = True
        if not isinstance(raw_item, dict):
            continue
        code = raw_item.get("code")
        if not isinstance(code, str) or not code:
            continue
        placement_id = raw_item.get("id")
        if not isinstance(placement_id, str) or not placement_id:
            placement_id = f"placement-{idx}"

        x_val = _to_float(raw_item.get("x"), 0.0)
        y_val = _to_float(raw_item.get("y"), 0.0)
        rotation_val = _to_float(raw_item.get("rotation"), 0.0)
        flipped_val = bool(raw_item.get("flipped", False))

        normalised.append(
            {
                "id": placement_id,
                "code": code,
                "x": x_val,
                "y": y_val,
                "rotation": rotation_val,
                "flipped": flipped_val,
            }
        )

    if saw_item and not normalised:
        raise ValueError("No valid placements were found in the layout JSON.")

    return normalised, zoom_value, pan_value


def _board_controls(container) -> BoardSpecification:
    container.header("Board outline")
    shape = container.selectbox(
        "Board shape",
        ["Rectangle", "L-Shape", "Custom polygon"],
        index=0,
    )

    if shape == "Rectangle":
        width = container.number_input("Width (mm)", min_value=600.0, value=1800.0, step=50.0)
        height = container.number_input("Depth (mm)", min_value=450.0, value=1200.0, step=50.0)
        polygon = [
            (0.0, 0.0),
            (width, 0.0),
            (width, height),
            (0.0, height),
        ]
        return BoardSpecification(shape="rectangle", width=width, height=height, polygon=polygon)

    if shape == "L-Shape":
        long_leg = container.number_input("Long leg length (mm)", min_value=1000.0, value=2400.0, step=50.0)
        short_leg = container.number_input("Short leg length (mm)", min_value=800.0, value=1500.0, step=50.0)
        shelf_width = container.number_input("Shelf width (mm)", min_value=450.0, value=900.0, step=25.0)
        polygon = [
            (0.0, 0.0),
            (long_leg, 0.0),
            (long_leg, shelf_width),
            (shelf_width, shelf_width),
            (shelf_width, short_leg),
            (0.0, short_leg),
        ]
        return BoardSpecification(
            shape="l-shape",
            width=long_leg,
            height=short_leg,
            polygon=polygon,
        )

    container.markdown(
        "Enter the corner points of your board outline in millimetres. "
        "Provide one point per line in the format `x,y`."
    )
    default_points: List[Tuple[float, float]] = [
        (0.0, 0.0),
        (2400.0, 0.0),
        (2400.0, 1200.0),
        (0.0, 1200.0),
    ]
    default_text = "\n".join(f"{x:.0f},{y:.0f}" for x, y in default_points)
    polygon_text = container.text_area(
        "Corner points",
        value=default_text,
        key="custom_polygon",
        height=160,
    )
    polygon: List[Tuple[float, float]] = []
    invalid_lines = 0
    for line in polygon_text.splitlines():
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) != 2:
            invalid_lines += 1
            continue
        try:
            x_val = float(parts[0].strip())
            y_val = float(parts[1].strip())
        except ValueError:
            invalid_lines += 1
            continue
        polygon.append((x_val, y_val))
    if invalid_lines:
        container.warning(
            f"Skipped {invalid_lines} line{'s' if invalid_lines != 1 else ''} with invalid coordinates."
        )
    width = max((p[0] for p in polygon), default=0.0)
    height = max((p[1] for p in polygon), default=0.0)
    return BoardSpecification(shape="custom", width=width, height=height, polygon=polygon)


def _designer(
    board: BoardSpecification,
    placements: List[Dict[str, object]],
    initial_zoom: float,
    initial_pan: Tuple[float, float],
) -> Tuple[List[Dict[str, object]], float, Tuple[float, float]]:
    library = hornby_track_library()
    board_polygon = board.polygon_points()
    min_zoom = 0.4
    max_zoom = 3.0
    try:
        initial_zoom_value = float(initial_zoom)
    except (TypeError, ValueError):
        initial_zoom_value = 1.0
    current_zoom = max(min(initial_zoom_value, max_zoom), min_zoom)
    try:
        pan_x = float(initial_pan[0])
        pan_y = float(initial_pan[1])
    except (TypeError, ValueError, IndexError):
        pan_x = 0.0
        pan_y = 0.0
    current_pan = (pan_x, pan_y)
    board_payload = {
        "polygon": board_polygon,
        "description": describe_board(board),
        "orientation": float(st.session_state.get("board_orientation", 0.0)),
    }
    track_payload = [
        {
            "code": piece.code,
            "name": piece.name,
            "kind": piece.kind,
            "length": piece.length,
            "angle": piece.angle,
            "radius": piece.radius,
            "displayLength": piece.arc_length() if piece.kind == "curve" else piece.length,
        }
        for piece in library.values()
    ]

    component_value = _layout_designer_component(
        key="layout-designer",
        default=None,
        board=board_payload,
        library=track_payload,
        placements=placements,
        zoom=current_zoom,
        pan={"x": pan_x, "y": pan_y},
    )
    state_changed = False

    if component_value is None:
        return placements, current_zoom, current_pan, state_changed

    if not isinstance(component_value, str):
        return placements, current_zoom, current_pan, state_changed

    try:
        parsed = json.loads(component_value)
    except json.JSONDecodeError:
        return placements, current_zoom, current_pan, state_changed

    if not isinstance(parsed, dict):
        return placements, current_zoom, current_pan, state_changed

    state_changed = True

    board_state = parsed.get("board")
    if isinstance(board_state, dict):
        orientation_value = board_state.get("orientation")
        if isinstance(orientation_value, (int, float)):
            st.session_state["board_orientation"] = float(orientation_value)

    payload = parsed.get("placements")
    zoom_value = parsed.get("zoom")
    pan_value = parsed.get("pan")

    if isinstance(zoom_value, (int, float)):
        current_zoom = max(min(float(zoom_value), max_zoom), min_zoom)

    updated = placements
    if isinstance(payload, list):
        updated = [p for p in payload if isinstance(p, dict)]

    if isinstance(pan_value, dict):
        pan_x_value = pan_value.get("x")
        pan_y_value = pan_value.get("y")
        if isinstance(pan_x_value, (int, float)) and isinstance(pan_y_value, (int, float)):
            current_pan = (float(pan_x_value), float(pan_y_value))

    return updated, current_zoom, current_pan, state_changed





controls_column, planning_column = st.columns([3, 2])

board = _board_controls(controls_column)
controls_column.success(describe_board(board))

planning_column.header("Power planning")
supply_voltage = planning_column.number_input(
    "DCC supply voltage (V)",
    min_value=10.0,
    max_value=22.0,
    value=16.0,
    step=0.5,
)
expected_current = planning_column.number_input(
    "Expected simultaneous load (A)",
    min_value=0.1,
    max_value=5.0,
    value=1.5,
    step=0.1,
)

planning_column.subheader("Layout data")
uploaded_layout = planning_column.file_uploader("Load layout JSON", type=["json"])

download_placeholder = planning_column.empty()


if "placements" not in st.session_state:
    st.session_state["placements"] = []

if "zoom" not in st.session_state:
    st.session_state["zoom"] = 1.0

if "board_orientation" not in st.session_state:
    st.session_state["board_orientation"] = 0.0

if "pan" not in st.session_state:
    st.session_state["pan"] = (0.0, 0.0)

if uploaded_layout is not None:
    try:
        raw_text = uploaded_layout.getvalue().decode("utf-8")
        parsed_payload = json.loads(raw_text)
        loaded_placements, loaded_zoom, loaded_pan = _normalise_layout_payload(parsed_payload)
    except UnicodeDecodeError:
        planning_column.error("Could not decode the uploaded file. Please upload UTF-8 JSON.")
    except (json.JSONDecodeError, ValueError) as exc:
        planning_column.error(f"Unable to load layout: {exc}")
    else:
        st.session_state["placements"] = loaded_placements
        if loaded_zoom is not None:
            st.session_state["zoom"] = loaded_zoom
        if loaded_pan is not None:
            st.session_state["pan"] = loaded_pan
        if isinstance(parsed_payload, dict):
            board_payload = parsed_payload.get("board")
            if isinstance(board_payload, dict):
                orientation_value = board_payload.get("orientation")
                if isinstance(orientation_value, (int, float)):
                    st.session_state["board_orientation"] = float(orientation_value)
        planning_column.success(f"Loaded {len(loaded_placements)} placement{'s' if len(loaded_placements) != 1 else ''} from layout.")

placements: List[Dict[str, object]] = st.session_state["placements"]
current_zoom: float = float(st.session_state.get("zoom", 1.0))
initial_pan: Tuple[float, float] = tuple(st.session_state.get("pan", (0.0, 0.0)))  # type: ignore[arg-type]
placements, current_zoom, current_pan, state_changed = _designer(
    board, placements, current_zoom, initial_pan
)
st.session_state["placements"] = placements
st.session_state["zoom"] = current_zoom
st.session_state["pan"] = current_pan
if state_changed:
    st.rerun()

layout_payload = {
    "placements": placements,
    "board": {
        "description": describe_board(board),
        "polygon": board.polygon_points(),
        "orientation": float(st.session_state.get("board_orientation", 0.0)),
    },
    "zoom": current_zoom,
    "pan": {"x": float(current_pan[0]), "y": float(current_pan[1])},
}
download_placeholder.download_button(
    "Download layout JSON",
    data=json.dumps(layout_payload, indent=2),
    file_name="layout.json",
    mime="application/json",
)


library = hornby_track_library()
inventory = inventory_from_placements(placements)
total_length_mm = total_run_length_mm(placements)
total_length_m = total_length_mm / 1000.0
track_resistance = layout_resistance_ohms(total_length_mm)
estimated_power = estimate_layout_power(
    total_length_mm,
    supply_voltage=supply_voltage,
    expected_current_draw=expected_current,
)
rail_loss = (expected_current ** 2) * track_resistance

st.subheader("Inventory summary")
cols = st.columns(4)
cols[0].metric("Pieces placed", sum(inventory.values()))
cols[1].metric("Unique catalogue items", len(inventory))
cols[2].metric("Run length", f"{total_length_m:.2f} m")
cols[3].metric("Rail resistance", f"{track_resistance:.2f} Ω")

st.subheader("Power estimate")
power_cols = st.columns(2)
power_cols[0].metric("Estimated booster power", f"{estimated_power:.1f} W")
power_cols[1].metric("Rail losses", f"{rail_loss:.1f} W")
st.caption(
    "Assumes nickel-silver rail, uniform cross-section and a simultaneous load of "
    f"{expected_current:.1f} A at {supply_voltage:.1f} V."
)

if total_length_m > 30:
    st.warning(
        "The track run exceeds 30 m. DCC power will dissipate over this distance; "
        "consider adding power districts or additional feeders."
    )

if inventory:
    rows = []
    for code, count in sorted(inventory.items()):
        piece = library.get(code)
        rows.append(
            {
                "Catalogue": code,
                "Piece": piece.name if piece else "Unknown",
                "Quantity": count,
                "Length (mm)": f"{piece.arc_length():.0f}" if piece and piece.kind == "curve" else (f"{piece.length:.0f}" if piece else "-"),
            }
        )
    st.dataframe(rows, hide_index=True, use_container_width=True)
else:
    st.info("Add pieces from the library to begin building your layout.")
