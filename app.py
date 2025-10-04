from __future__ import annotations

import json
from pathlib import Path
from string import Template
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
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], Optional[float]]:
    """Extract placements, planning circles and optional zoom from payload."""

    placements_payload: object
    circles_payload: object = []
    zoom_value: Optional[float] = None
    if isinstance(data, dict):
        placements_payload = data.get("placements")
        circles_payload = data.get("circles")
        zoom_raw = data.get("zoom")
        if isinstance(zoom_raw, (int, float)):
            zoom_value = float(zoom_raw)
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

    circles: List[Dict[str, object]] = []
    if isinstance(circles_payload, list):
        for idx, raw_circle in enumerate(circles_payload):
            if not isinstance(raw_circle, dict):
                continue
            circle_id = raw_circle.get("id")
            if not isinstance(circle_id, str) or not circle_id:
                circle_id = f"circle-{idx}"
            radius = _to_float(raw_circle.get("radius"), 0.0)
            if radius <= 0:
                continue
            x_val = _to_float(raw_circle.get("x"), 0.0)
            y_val = _to_float(raw_circle.get("y"), 0.0)
            color_val = raw_circle.get("color")
            label_val = raw_circle.get("label")
            circle: Dict[str, object] = {
                "id": circle_id,
                "radius": radius,
                "x": x_val,
                "y": y_val,
            }
            if isinstance(color_val, str) and color_val:
                circle["color"] = color_val
            if isinstance(label_val, str) and label_val:
                circle["label"] = label_val
            circles.append(circle)

    return normalised, circles, zoom_value


def _board_controls() -> BoardSpecification:
    st.sidebar.header("Board outline")
    shape = st.sidebar.selectbox(
        "Board shape",
        ["Rectangle", "L-Shape", "Custom polygon"],
        index=0,
    )

    if shape == "Rectangle":
        width = st.sidebar.number_input("Width (mm)", min_value=600.0, value=1800.0, step=50.0)
        height = st.sidebar.number_input("Depth (mm)", min_value=450.0, value=1200.0, step=50.0)
        polygon = [
            (0.0, 0.0),
            (width, 0.0),
            (width, height),
            (0.0, height),
        ]
        return BoardSpecification(shape="rectangle", width=width, height=height, polygon=polygon)

    if shape == "L-Shape":
        long_leg = st.sidebar.number_input("Long leg length (mm)", min_value=1000.0, value=2400.0, step=50.0)
        short_leg = st.sidebar.number_input("Short leg length (mm)", min_value=800.0, value=1500.0, step=50.0)
        shelf_width = st.sidebar.number_input("Shelf width (mm)", min_value=450.0, value=900.0, step=25.0)
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

    st.sidebar.markdown(
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
    polygon_text = st.sidebar.text_area(
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
        st.sidebar.warning(
            f"Skipped {invalid_lines} line{'s' if invalid_lines != 1 else ''} with invalid coordinates."
        )
    width = max((p[0] for p in polygon), default=0.0)
    height = max((p[1] for p in polygon), default=0.0)
    return BoardSpecification(shape="custom", width=width, height=height, polygon=polygon)


def _designer(
    board: BoardSpecification,
    placements: List[Dict[str, object]],
    circles: List[Dict[str, object]],
    initial_zoom: float,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], float]:
    library = hornby_track_library()
    board_polygon = board.polygon_points()
    min_zoom = 0.4
    max_zoom = 3.0
    try:
        initial_zoom_value = float(initial_zoom)
    except (TypeError, ValueError):
        initial_zoom_value = 1.0
    clamped_initial_zoom = max(min(initial_zoom_value, max_zoom), min_zoom)
    current_zoom = clamped_initial_zoom
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

    library_cards = []
    for item in track_payload:
        extra_controls = ""
        if item["kind"] == "curve" and item.get("radius"):
            extra_controls = (
                f"<button data-radius=\"{item['radius']}\" data-label=\"{item['code']} ({item['radius']:.0f} mm)\" "
                "class=\"add-circle\">Add guide circle</button>"
            )
        radius_fragment = f" · Radius {item['radius']:.0f} mm" if item.get("radius") else ""
        card = (
            "<div class=\"library-item\">"
            f"<div class=\"library-heading\"><strong>{item['code']}</strong><span>{item['name']}</span></div>"
            f"<small>{item['kind'].title()} · {item['displayLength']:.0f} mm{radius_fragment}</small>"
            f"<div class=\"library-actions\">"
            f"<button data-code=\"{item['code']}\" class=\"add-piece\">Add to board</button>"
            f"{extra_controls}"
            "</div>"
            "</div>"
        )
        library_cards.append(card)

    html_template = Template(
        """
    <style>
    :root {
        color-scheme: light;
    }
    html, body {
        height: 100%;
    }
    body {
        margin: 0;
        font-family: 'Source Sans Pro', sans-serif;
        background: linear-gradient(180deg, #eef1f5 0%, #e2e7f0 100%);
        display: flex;
        justify-content: center;
        padding: 1.5rem;
        box-sizing: border-box;
        overflow: hidden;
    }
    .designer-wrapper {
        display: grid;
        grid-template-columns: minmax(0, 2.2fr) minmax(280px, 1fr);
        gap: 1.25rem;
        align-items: stretch;
        width: 100%;
        max-width: 1480px;
        height: 100%;
        overflow: hidden;
    }
    .board-column {
        display: flex;
        flex-direction: column;
        gap: 1rem;
        height: 100%;
        overflow: hidden;
        min-height: 0;
    }
    .board-canvas {
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        flex: 1;
        min-height: 0;
    }
    .board-surface {
        position: relative;
        border: 2px solid #d0d0d0;
        border-radius: 0.5rem;
        background: #ffffff;
        overflow: hidden;
        min-height: 580px;
        height: min(900px, 72vh);
        flex: 1;
        min-height: 0;
        box-shadow: 0 10px 28px rgba(31, 55, 90, 0.12);
    }
    #boardCanvas {
        width: 100%;
        height: 100%;
        touch-action: none;
        display: block;
    }
    .view-controls,
    .board-controls {
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
        align-items: center;
    }
    .view-controls label,
    .board-controls span.label {
        font-weight: 600;
        font-size: 0.9rem;
    }
    .view-controls input[type="range"] {
        flex: 1;
        min-width: 160px;
    }
    .view-controls span,
    .board-controls span.value {
        min-width: 3rem;
        text-align: right;
        font-variant-numeric: tabular-nums;
    }
    .view-controls button,
    .board-controls button {
        padding: 0.3rem 0.75rem;
        border-radius: 0.4rem;
        border: 1px solid #666666;
        background: #f8f8f8;
        cursor: pointer;
    }
    .board-controls {
        justify-content: flex-start;
    }
    .board-controls span.value {
        font-weight: 600;
    }
    .piece-controls {
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
        align-items: center;
    }
    .piece-controls button {
        padding: 0.4rem 0.75rem;
        border-radius: 0.4rem;
        border: 1px solid #666666;
        background: #f2f2f2;
        cursor: pointer;
    }
    .piece-controls button.primary {
        border-color: #1f77b4;
        background: #1f77b4;
        color: white;
    }
    .piece-controls span {
        font-weight: 600;
    }
    .hint {
        font-size: 0.85rem;
        color: #555555;
    }
    .export-controls {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 0.5rem;
    }
    .export-controls button {
        padding: 0.45rem 0.9rem;
        border-radius: 0.4rem;
        border: 1px solid #1f77b4;
        background: #1f77b4;
        color: #ffffff;
        cursor: pointer;
        font-weight: 600;
    }
    .export-controls .hint {
        margin: 0;
    }
    .library-panel {
        border: 1px solid #d0d0d0;
        border-radius: 0.75rem;
        background: #f8f9fb;
        padding: 1rem;
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        position: sticky;
        top: 0;
        max-height: 100%;
        overflow: auto;
    }
    .library-panel h3 {
        margin: 0;
        font-size: 1.1rem;
    }
    .library-grid {
        display: grid;
        gap: 0.5rem;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    }
    .library-item {
        border: 1px solid #d7d7d7;
        border-radius: 0.45rem;
        padding: 0.6rem;
        background: #ffffff;
        display: flex;
        flex-direction: column;
        gap: 0.35rem;
    }
    .library-heading {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 0.5rem;
    }
    .library-heading span {
        font-size: 0.9rem;
        color: #444444;
    }
    .library-item small {
        color: #666666;
    }
    .library-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 0.4rem;
    }
    .library-actions button {
        flex: 1 1 auto;
        padding: 0.35rem 0.5rem;
        border-radius: 0.3rem;
        border: 1px solid #1f77b4;
        background: #1f77b4;
        color: white;
        cursor: pointer;
        font-size: 0.85rem;
    }
    .library-actions button.add-circle {
        border-color: #9467bd;
        background: #9467bd;
    }
    .circle-panel {
        margin-top: 1rem;
        border-top: 1px solid #d0d0d0;
        padding-top: 0.75rem;
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }
    .circle-list {
        display: flex;
        flex-direction: column;
        gap: 0.4rem;
    }
    .circle-item {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 0.5rem;
        border: 1px solid #d7d7d7;
        border-radius: 0.45rem;
        padding: 0.4rem 0.6rem;
        background: #ffffff;
    }
    .circle-item.selected {
        border-color: #9467bd;
        box-shadow: 0 0 0 2px rgba(148, 103, 189, 0.25);
    }
    .circle-swatch {
        width: 18px;
        height: 18px;
        border-radius: 50%;
        border: 2px solid rgba(0, 0, 0, 0.1);
    }
    .circle-meta {
        flex: 1 1 auto;
        min-width: 160px;
        font-size: 0.85rem;
    }
    .circle-actions button {
        padding: 0.3rem 0.6rem;
        border-radius: 0.3rem;
        border: 1px solid #d62728;
        background: #d62728;
        color: white;
        cursor: pointer;
        font-size: 0.8rem;
    }
    @media (max-width: 1100px) {
        body {
            overflow: auto;
            padding: 1rem;
        }
        .designer-wrapper {
            display: flex;
            flex-direction: column;
            height: auto;
        }
        .board-column {
            height: auto;
        }
        .library-panel {
            position: static;
            max-height: none;
        }
    }
    </style>
    <div class="designer-wrapper">
        <div class="board-column">
            <div class="board-canvas">
                <div class="board-surface">
                    <canvas id="boardCanvas"></canvas>
                </div>
                <div class="view-controls">
                    <label for="zoomSlider">Zoom</label>
                    <input type="range" id="zoomSlider" min="0.4" max="3" step="0.01" value="1" />
                    <span id="zoomValue">100%</span>
                    <button id="resetView" type="button">Reset view</button>
                </div>
                <div class="board-controls">
                    <span class="label">Board orientation</span>
                    <button id="boardRotateLeft" type="button">↺ 90°</button>
                    <button id="boardRotateRight" type="button">↻ 90°</button>
                    <span class="value" id="boardOrientationLabel">0°</span>
                </div>
                <div class="piece-controls">
                    <span id="selectionLabel">No piece selected</span>
                    <button id="rotateLeft">⟲ Rotate -15°</button>
                    <button id="rotateRight">⟳ Rotate +15°</button>
                    <button id="flipPiece">Flip</button>
                    <button id="nudgeUp">▲ Nudge</button>
                    <button id="nudgeDown">▼ Nudge</button>
                    <button id="nudgeLeft">◀ Nudge</button>
                    <button id="nudgeRight">▶ Nudge</button>
                    <button id="snapPiece" class="primary">Snap to piece</button>
                    <button id="snapGrid">Snap to 10 mm</button>
                    <button id="toggleSectionMode">Section move: Off</button>
                    <button id="deletePiece">🗑 Remove</button>
                </div>
                <p class="hint">Tip: drag pieces directly on the board. Use "Snap to piece" to connect endpoints, or toggle section move to reposition an entire connected run.</p>
                <div class="export-controls">
                    <button id="saveLayout" type="button">💾 Save layout</button>
                    <p class="hint">Download a JSON backup of the current plan.</p>
                </div>
            </div>
        </div>
        <aside class="library-panel">
            <h3>Track library and curve guides</h3>
            <p class="hint">Click "Add to board" to drop a piece. Curved pieces also offer a planning circle that you can drag on the board.</p>
            <div class="library-grid">$library_cards</div>
            <div class="circle-panel">
                <h4>Planning circles</h4>
                <p class="hint">Drag circles on the canvas to position them. Use them to visualise curve radii and loops.</p>
                <div id="circleList" class="circle-list"></div>
            </div>
        </aside>
    </div>
    <script src="https://unpkg.com/streamlit-component-lib/dist/index.js"></script>
    <script>
    let boardData = $board_json;
    let trackLibrary = $track_json;
    const initialPlacements = $placements_json;
    const initialCircles = $circles_json;
    const initialZoom = $initial_zoom_json;
    const colorPalette = ['#ff7f0e', '#9467bd', '#2ca02c', '#d62728', '#17becf', '#1f77b4'];
    const queryParams = new URLSearchParams(window.location.search);
    const componentId = queryParams.get('componentId');

    let libraryByCode = Object.fromEntries(trackLibrary.map(item => [item.code, item]));
    let placements = initialPlacements.map((item, idx) => ({
        id: item.id || ('placement-' + idx),
        code: item.code,
        x: typeof item.x === 'number' ? item.x : 0,
        y: typeof item.y === 'number' ? item.y : 0,
        rotation: typeof item.rotation === 'number' ? item.rotation : 0,
        flipped: Boolean(item.flipped),
    }));
    let nextId = placements.length;
    let selectedId = placements.length ? placements[placements.length - 1].id : null;

    let boardOrientation = typeof boardData.orientation === 'number' ? boardData.orientation : 0;
    const padding = 60;

    function clonePoint(point) {
        if (Array.isArray(point) && point.length >= 2) {
            const x = Number(point[0]);
            const y = Number(point[1]);
            return [Number.isFinite(x) ? x : 0, Number.isFinite(y) ? y : 0];
        }
        if (point && typeof point === 'object') {
            const x = Number(point.x);
            const y = Number(point.y);
            return [Number.isFinite(x) ? x : 0, Number.isFinite(y) ? y : 0];
        }
        return [0, 0];
    }

    function defaultPolygon() {
        return [[0, 0], [2400, 0], [2400, 1200], [0, 1200]];
    }

    let polygon = (boardData.polygon && boardData.polygon.length ? boardData.polygon : defaultPolygon()).map(clonePoint);
    let minX = 0;
    let maxX = 0;
    let minY = 0;
    let maxY = 0;
    let widthMm = 1;
    let heightMm = 1;
    let boardCenter = { x: 0, y: 0 };

    function recalculateBoardGeometry() {
        if (!polygon.length) {
            polygon = defaultPolygon();
        }
        polygon = polygon.map(clonePoint);
        const xs = polygon.map(pt => pt[0]);
        const ys = polygon.map(pt => pt[1]);
        minX = Math.min(...xs);
        maxX = Math.max(...xs);
        minY = Math.min(...ys);
        maxY = Math.max(...ys);
        widthMm = Math.max(maxX - minX, 1);
        heightMm = Math.max(maxY - minY, 1);
        boardCenter = { x: (minX + maxX) / 2, y: (minY + maxY) / 2 };
        boardData.polygon = polygon.map(pt => pt.slice());
        boardData.orientation = boardOrientation;
    }

    recalculateBoardGeometry();

    function postToStreamlit(type, payload = {}) {
        if (window.Streamlit) {
            if (type === 'streamlit:setComponentValue' && 'value' in payload) {
                window.Streamlit.setComponentValue(payload.value);
                return;
            }
            if (type === 'streamlit:setFrameHeight' && 'height' in payload) {
                window.Streamlit.setFrameHeight(payload.height);
                return;
            }
            if (type === 'streamlit:componentReady') {
                window.Streamlit.setComponentReady();
                if ('height' in payload) {
                    window.Streamlit.setFrameHeight(payload.height);
                }
                return;
            }
        }
        const message = Object.assign({
            isStreamlitMessage: true,
            type,
        }, payload);
        if (type === 'streamlit:componentReady' && !('apiVersion' in message)) {
            message.apiVersion = 1;
        }
        if (componentId) {
            message.componentId = componentId;
        }
        window.parent.postMessage(message, '*');
    }
    let nextCircleColor = 0;
    let sectionMode = false;
    let activeSectionIds = null;
    const sectionInitialPositions = new Map();
    const MIN_ZOOM = 0.4;
    const MAX_ZOOM = 3;
    let zoom = Number.isFinite(initialZoom) ? Math.min(Math.max(initialZoom, MIN_ZOOM), MAX_ZOOM) : 1;
    let pan = { x: 0, y: 0 };

    const canvas = document.getElementById('boardCanvas');
    const ctx = canvas.getContext('2d');
    const zoomSlider = document.getElementById('zoomSlider');
    const zoomValueLabel = document.getElementById('zoomValue');
    const resetViewButton = document.getElementById('resetView');
    const orientationLabel = document.getElementById('boardOrientationLabel');
    const rotateBoardLeftButton = document.getElementById('boardRotateLeft');
    const rotateBoardRightButton = document.getElementById('boardRotateRight');

    function buildGuideCircleList(source) {
        nextCircleColor = 0;
        return (Array.isArray(source) ? source : []).map((circle, idx) => {
            if (!circle || typeof circle !== 'object') { return null; }
            const radius = typeof circle.radius === 'number' ? circle.radius : 0;
            if (!radius || radius <= 0) { return null; }
            const x = typeof circle.x === 'number' ? circle.x : boardCenter.x;
            const y = typeof circle.y === 'number' ? circle.y : boardCenter.y;
            return {
                id: circle.id || ('circle-' + idx),
                radius,
                x,
                y,
                color: typeof circle.color === 'string' && circle.color ? circle.color : colorPalette[nextCircleColor++ % colorPalette.length],
                label: typeof circle.label === 'string' && circle.label ? circle.label : `Radius $${radius.toFixed(0)} mm`,
            };
        }).filter(Boolean);
    }

    let guideCircles = buildGuideCircleList(initialCircles);
    let circleCounter = guideCircles.length;
    let selectedCircleId = guideCircles.length ? guideCircles[guideCircles.length - 1].id : null;
    let draggingCircleId = null;
    let circleDragOffset = { x: 0, y: 0 };
    const SNAP_DISTANCE_MM = 200;
    const CONNECTION_TOLERANCE_MM = 3;
    const ANGLE_TOLERANCE_RAD = Math.PI / 36;

    function updateBoardOrientationLabel() {
        if (!orientationLabel) { return; }
        const value = ((boardOrientation % 360) + 360) % 360;
        orientationLabel.textContent = `$${Math.round(value)}°`;
    }

    updateBoardOrientationLabel();

    function toRadians(degrees) {
        return (degrees || 0) * Math.PI / 180;
    }

    function toDegrees(radians) {
        return radians * 180 / Math.PI;
    }

    function normalizeRadians(angle) {
        if (!isFinite(angle)) { return 0; }
        const twoPi = Math.PI * 2;
        let value = angle % twoPi;
        if (value <= -Math.PI) {
            value += twoPi;
        }
        if (value > Math.PI) {
            value -= twoPi;
        }
        return value;
    }

    function normalizeDegrees(angle) {
        if (!isFinite(angle)) { return 0; }
        let value = angle % 360;
        if (value <= -180) {
            value += 360;
        }
        if (value > 180) {
            value -= 360;
        }
        return value;
    }

    function rotatePoint(x, y, angle) {
        const cos = Math.cos(angle);
        const sin = Math.sin(angle);
        return {
            x: x * cos - y * sin,
            y: x * sin + y * cos,
        };
    }

    function getPlacementById(id) {
        return placements.find(item => item.id === id) || null;
    }

    function computeBaseScale() {
        const availableWidth = Math.max(canvas.width - padding * 2, 1);
        const availableHeight = Math.max(canvas.height - padding * 2, 1);
        return Math.min(availableWidth / widthMm, availableHeight / heightMm);
    }

    function getScale() {
        return computeBaseScale() * zoom;
    }

    function clampPan() {
        const scale = getScale();
        const contentWidth = widthMm * scale + padding * 2;
        const contentHeight = heightMm * scale + padding * 2;
        const maxPanX = Math.max(contentWidth, canvas.width);
        const maxPanY = Math.max(contentHeight, canvas.height);
        pan.x = Math.min(Math.max(pan.x, -maxPanX), maxPanX);
        pan.y = Math.min(Math.max(pan.y, -maxPanY), maxPanY);
    }

    function updateZoomUI() {
        if (zoomSlider) {
            zoomSlider.value = zoom.toFixed(2);
        }
        if (zoomValueLabel) {
            zoomValueLabel.textContent = Math.round(zoom * 100) + '%';
        }
    }

    function setZoom(targetZoom, focusPoint) {
        const clamped = Math.min(Math.max(targetZoom, MIN_ZOOM), MAX_ZOOM);
        if (!Number.isFinite(clamped) || Math.abs(clamped - zoom) < 1e-4) {
            zoom = clamped;
            updateZoomUI();
            return;
        }
        const focus = focusPoint || { x: canvas.width / 2, y: canvas.height / 2 };
        const mmBefore = canvasToMm(focus.x, focus.y);
        zoom = clamped;
        const after = mmToCanvas(mmBefore.x, mmBefore.y);
        pan.x += focus.x - after.x;
        pan.y += focus.y - after.y;
        clampPan();
        updateZoomUI();
        draw();
        emitState();
    }

    function resetView() {
        zoom = 1;
        pan = { x: 0, y: 0 };
        clampPan();
        updateZoomUI();
        draw();
        emitState();
    }

    function resizeCanvas() {
        const rect = canvas.getBoundingClientRect();
        canvas.width = rect.width;
        canvas.height = rect.height;
        clampPan();
        updateZoomUI();
        draw();
        requestFrameHeight();
    }

    function mmToCanvas(x, y) {
        const scale = getScale();
        const cx = (x - minX) * scale + padding + pan.x;
        const cy = canvas.height - ((y - minY) * scale + padding) + pan.y;
        return { x: cx, y: cy, scale };
    }

    function canvasToMm(x, y) {
        const scale = getScale();
        const mmX = (x - padding - pan.x) / scale + minX;
        const mmY = ((canvas.height - (y - pan.y)) - padding) / scale + minY;
        return { x: mmX, y: mmY, scale };
    }

    function drawBoard() {
        if (!polygon.length) {
            return;
        }
        ctx.save();
        ctx.beginPath();
        polygon.forEach((pt, idx) => {
            const { x, y } = mmToCanvas(pt[0], pt[1]);
            if (idx === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        });
        ctx.closePath();
        ctx.fillStyle = '#f5f7ff';
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = '#5a6aa1';
        ctx.stroke();
        ctx.restore();
    }

    function drawPlacements() {
        placements.forEach(placement => {
            const piece = libraryByCode[placement.code];
            if (!piece) { return; }
            const { x, y, scale } = mmToCanvas(placement.x, placement.y);
            const rotation = (placement.rotation || 0) * Math.PI / 180;
            const selected = placement.id === selectedId;
            const displayLength = piece.displayLength || piece.length || 0;
            const trackWidth = 32 * scale;
            ctx.save();
            ctx.translate(x, y);
            ctx.rotate(-rotation);
            if (piece.kind === 'curve' && piece.radius && piece.angle) {
                const radiusPx = piece.radius * scale;
                const startAngle = piece.angle * Math.PI / 180 / 2;
                ctx.beginPath();
                ctx.strokeStyle = selected ? '#d62728' : '#1f77b4';
                ctx.lineWidth = 6;
                ctx.arc(0, 0, radiusPx, startAngle, -startAngle, true);
                ctx.stroke();
            } else {
                const halfLength = (displayLength / 2) * scale;
                ctx.beginPath();
                ctx.fillStyle = selected ? '#ffe5d1' : '#dce9ff';
                ctx.strokeStyle = selected ? '#d62728' : '#1f77b4';
                ctx.lineWidth = 2;
                ctx.rect(-halfLength, -trackWidth / 2, halfLength * 2, trackWidth);
                ctx.fill();
                ctx.stroke();
            }
            ctx.restore();

            // Connection points
            const points = connectionPoints(placement);
            points.forEach(pt => {
                const { x: px, y: py } = mmToCanvas(pt.x, pt.y);
                ctx.beginPath();
                ctx.fillStyle = '#2ca02c';
                ctx.arc(px, py, 6, 0, 2 * Math.PI);
                ctx.fill();
            });
        });
    }

    function drawGuideCircles() {
        guideCircles.forEach(circle => {
            const { x, y, scale } = mmToCanvas(circle.x, circle.y);
            const radiusPx = circle.radius * scale;
            ctx.save();
            ctx.beginPath();
            ctx.setLineDash([10, 6]);
            ctx.lineWidth = circle.id === selectedCircleId ? 3 : 2;
            ctx.strokeStyle = circle.color || '#ff7f0e';
            ctx.arc(x, y, radiusPx, 0, Math.PI * 2);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = circle.color || '#ff7f0e';
            ctx.globalAlpha = 0.12;
            ctx.beginPath();
            ctx.arc(x, y, 8, 0, Math.PI * 2);
            ctx.fill();
            ctx.globalAlpha = 1;
            ctx.beginPath();
            ctx.arc(x, y, 4, 0, Math.PI * 2);
            ctx.fill();
            ctx.restore();
        });
    }

    function draw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        drawBoard();
        drawGuideCircles();
        drawPlacements();
    }

    function endpointGeometry(placement) {
        const piece = libraryByCode[placement.code];
        if (!piece) { return []; }
        const rotation = toRadians(placement.rotation || 0);
        const flipped = placement.flipped ? -1 : 1;

        if (piece.kind === 'curve' && piece.radius && piece.angle) {
            const halfTheta = toRadians(piece.angle) / 2;
            const orientation = flipped;
            const baseAngles = [halfTheta, -halfTheta];
            return baseAngles.map(baseAngle => {
                const angleLocal = baseAngle * orientation;
                const localPosition = {
                    x: piece.radius * Math.cos(angleLocal),
                    y: piece.radius * Math.sin(angleLocal),
                };
                const rotated = rotatePoint(localPosition.x, localPosition.y, rotation);
                const tangentVector = {
                    x: -Math.sin(angleLocal) * orientation,
                    y: Math.cos(angleLocal) * orientation,
                };
                const tangentLocalAngle = Math.atan2(tangentVector.y, tangentVector.x);
                const radialLocalAngle = Math.atan2(localPosition.y, localPosition.x);
                return {
                    x: placement.x + rotated.x,
                    y: placement.y + rotated.y,
                    tangent: normalizeRadians(tangentLocalAngle + rotation),
                    radial: normalizeRadians(radialLocalAngle + rotation),
                    radialVector: rotated,
                    localPosition,
                    localTangent: tangentLocalAngle,
                    localRadial: radialLocalAngle,
                };
            });
        }

        const displayLength = piece.displayLength || piece.length || 0;
        const halfLength = displayLength / 2;
        const endpoints = [
            {
                localPosition: { x: halfLength, y: 0 },
                localTangent: 0,
            },
            {
                localPosition: { x: -halfLength, y: 0 },
                localTangent: Math.PI,
            },
        ];
        return endpoints.map(endpoint => {
            const rotated = rotatePoint(endpoint.localPosition.x, endpoint.localPosition.y, rotation);
            const radialLocalAngle = Math.atan2(endpoint.localPosition.y, endpoint.localPosition.x);
            return {
                x: placement.x + rotated.x,
                y: placement.y + rotated.y,
                tangent: normalizeRadians(endpoint.localTangent + rotation),
                radial: normalizeRadians(radialLocalAngle + rotation),
                radialVector: rotated,
                localPosition: endpoint.localPosition,
                localTangent: endpoint.localTangent,
                localRadial: radialLocalAngle,
            };
        });
    }

    function connectionPoints(placement) {
        return endpointGeometry(placement).map(endpoint => ({ x: endpoint.x, y: endpoint.y }));
    }

    function endpointsAreConnected(endpointA, endpointB) {
        const dx = endpointA.x - endpointB.x;
        const dy = endpointA.y - endpointB.y;
        const distance = Math.hypot(dx, dy);
        if (distance > CONNECTION_TOLERANCE_MM) {
            return false;
        }
        const tangentDiff = Math.abs(normalizeRadians(endpointA.tangent - endpointB.tangent));
        const radialA = endpointA.radial;
        const radialB = endpointB.radial;
        const radialDiff =
            radialA === undefined || radialB === undefined
                ? Number.POSITIVE_INFINITY
                : Math.abs(normalizeRadians(radialA - radialB));
        const tangentsOpposed = Math.abs(tangentDiff - Math.PI) < ANGLE_TOLERANCE_RAD;
        const radialsAligned = radialDiff < ANGLE_TOLERANCE_RAD;
        return tangentsOpposed || radialsAligned;
    }

    function connectedSectionIds(originId) {
        const visited = new Set();
        const queue = [originId];
        while (queue.length) {
            const currentId = queue.shift();
            if (!currentId || visited.has(currentId)) {
                continue;
            }
            visited.add(currentId);
            const placement = getPlacementById(currentId);
            if (!placement) { continue; }
            const endpoints = endpointGeometry(placement);
            placements.forEach(other => {
                if (other.id === currentId || visited.has(other.id)) { return; }
                const otherEndpoints = endpointGeometry(other);
                for (let i = 0; i < endpoints.length; i += 1) {
                    for (let j = 0; j < otherEndpoints.length; j += 1) {
                        if (endpointsAreConnected(endpoints[i], otherEndpoints[j])) {
                            queue.push(other.id);
                            return;
                        }
                    }
                }
            });
        }
        return Array.from(visited);
    }

    function applySectionTransform(sectionIds, pivotPoint, deltaRotationDeg, deltaX, deltaY) {
        const rotationRad = toRadians(deltaRotationDeg);
        const cos = Math.cos(rotationRad);
        const sin = Math.sin(rotationRad);
        sectionIds.forEach(id => {
            const piece = getPlacementById(id);
            if (!piece) { return; }
            if (deltaRotationDeg) {
                const relX = piece.x - pivotPoint.x;
                const relY = piece.y - pivotPoint.y;
                const rotatedX = relX * cos - relY * sin;
                const rotatedY = relX * sin + relY * cos;
                piece.x = pivotPoint.x + rotatedX;
                piece.y = pivotPoint.y + rotatedY;
                piece.rotation = (piece.rotation + deltaRotationDeg + 360) % 360;
            }
            piece.x += deltaX;
            piece.y += deltaY;
        });
    }

    function findBestSnapTransform(placement) {
        const endpoints = endpointGeometry(placement);
        let best = null;
        placements.forEach(other => {
            if (other.id === placement.id) { return; }
            const otherEndpoints = endpointGeometry(other);
            endpoints.forEach(endpoint => {
                otherEndpoints.forEach(target => {
                    const dx = endpoint.x - target.x;
                    const dy = endpoint.y - target.y;
                    const distance = Math.hypot(dx, dy);
                    if (distance > SNAP_DISTANCE_MM) { return; }
                    const candidateTangents = [
                        normalizeRadians(target.tangent + Math.PI),
                        normalizeRadians(target.tangent),
                    ];
                    candidateTangents.forEach(desiredTangent => {
                        const deltaRotationRad = normalizeRadians(desiredTangent - endpoint.tangent);
                        const deltaRotationDeg = normalizeDegrees(toDegrees(deltaRotationRad));
                        const newRotationDeg = (placement.rotation + deltaRotationDeg + 360) % 360;
                        const newRotationRad = toRadians(newRotationDeg);
                        const rotatedLocal = rotatePoint(endpoint.localPosition.x, endpoint.localPosition.y, newRotationRad);
                        const newCenterX = target.x - rotatedLocal.x;
                        const newCenterY = target.y - rotatedLocal.y;
                        const transformedEndpoint = {
                            x: target.x,
                            y: target.y,
                            tangent: normalizeRadians(endpoint.localTangent + newRotationRad),
                            radial: normalizeRadians(Math.atan2(rotatedLocal.y, rotatedLocal.x)),
                        };
                        if (!endpointsAreConnected(transformedEndpoint, target)) { return; }
                        const deltaX = newCenterX - placement.x;
                        const deltaY = newCenterY - placement.y;
                        const rotationMagnitude = Math.abs(deltaRotationDeg);
                        if (
                            !best ||
                            distance < best.distance - 1e-6 ||
                            (Math.abs(distance - best.distance) < 1e-6 && rotationMagnitude < best.rotationMagnitude - 1e-6)
                        ) {
                            best = {
                                distance,
                                deltaRotationDeg,
                                deltaX,
                                deltaY,
                                rotationMagnitude,
                            };
                        }
                    });
                });
            });
        });
        if (best) {
            delete best.rotationMagnitude;
        }
        return best;
    }

    function rotateBoard(deltaDegrees) {
        if (!Number.isFinite(deltaDegrees)) { return; }
        const radians = toRadians(deltaDegrees);
        const centre = { x: boardCenter.x, y: boardCenter.y };
        polygon = polygon.map(point => {
            const rotated = rotatePoint(point[0] - centre.x, point[1] - centre.y, radians);
            return [centre.x + rotated.x, centre.y + rotated.y];
        });
        placements.forEach(piece => {
            const rotated = rotatePoint(piece.x - centre.x, piece.y - centre.y, radians);
            piece.x = centre.x + rotated.x;
            piece.y = centre.y + rotated.y;
            piece.rotation = (piece.rotation + deltaDegrees + 360) % 360;
        });
        guideCircles.forEach(circle => {
            const rotated = rotatePoint(circle.x - centre.x, circle.y - centre.y, radians);
            circle.x = centre.x + rotated.x;
            circle.y = centre.y + rotated.y;
        });
        boardOrientation = (boardOrientation + deltaDegrees) % 360;
        recalculateBoardGeometry();
        clampPan();
        draw();
        updateBoardOrientationLabel();
        updateSelectionLabel();
        renderCircleList();
        emitState();
    }

    function emitState() {
        const payload = {
            placements: placements.map(item => ({
                id: item.id,
                code: item.code,
                x: item.x,
                y: item.y,
                rotation: item.rotation,
                flipped: item.flipped,
            })),
            circles: guideCircles.map(circle => ({
                id: circle.id,
                radius: circle.radius,
                x: circle.x,
                y: circle.y,
                color: circle.color,
                label: circle.label,
            })),
            board: {
                description: boardData.description,
                polygon: polygon.map(pt => pt.slice()),
                orientation: boardOrientation,
            },
            zoom,
        };
        postToStreamlit("streamlit:setComponentValue", {
            value: JSON.stringify(payload),
        });
        return payload;
    }

    function getCircleById(id) {
        return guideCircles.find(circle => circle.id === id) || null;
    }

    function nextCircleColour() {
        const colour = colorPalette[nextCircleColor % colorPalette.length];
        nextCircleColor += 1;
        return colour;
    }

    function currentFrameHeight() {
        const bodyHeight = document.body ? document.body.scrollHeight : 0;
        const docHeight = document.documentElement ? document.documentElement.scrollHeight : 0;
        return Math.max(bodyHeight, docHeight, window.innerHeight || 0);
    }

    function requestFrameHeight() {
        postToStreamlit("streamlit:setFrameHeight", {
            height: currentFrameHeight(),
        });
    }

    function announceReady() {
        postToStreamlit("streamlit:componentReady", {
            height: currentFrameHeight(),
        });
    }

    function addPiece(code) {
        const piece = libraryByCode[code];
        if (!piece) { return; }
        const newPlacement = {
            id: 'placement-' + nextId++,
            code,
            x: boardCenter.x,
            y: boardCenter.y,
            rotation: 0,
            flipped: false,
        };
        placements.push(newPlacement);
        selectedId = newPlacement.id;
        activeSectionIds = null;
        sectionInitialPositions.clear();
        updateSelectionLabel();
        draw();
        emitState();
    }

    function applyBoardPayload(payload, options = {}) {
        if (!payload || typeof payload !== 'object') { return; }
        const { recenter = false, emit = false } = options;
        if (typeof payload.description === 'string') {
            boardData.description = payload.description;
        }
        if (Array.isArray(payload.polygon) && payload.polygon.length) {
            polygon = payload.polygon.map(clonePoint);
        } else if (!polygon.length) {
            polygon = defaultPolygon();
        }
        if (typeof payload.orientation === 'number') {
            boardOrientation = payload.orientation;
        }
        recalculateBoardGeometry();
        if (recenter) {
            pan = { x: 0, y: 0 };
        }
        clampPan();
        draw();
        updateBoardOrientationLabel();
        if (emit) {
            emitState();
        }
    }

    function applyRenderArgs(args) {
        if (!args || typeof args !== 'object') { return; }
        if (Array.isArray(args.library)) {
            trackLibrary = args.library;
            libraryByCode = Object.fromEntries(trackLibrary.map(item => [item.code, item]));
        }
        if (args.board) {
            applyBoardPayload(args.board);
        } else {
            recalculateBoardGeometry();
        }
        if (Array.isArray(args.placements)) {
            placements = args.placements.map((item, idx) => ({
                id: item.id || ('placement-' + idx),
                code: item.code,
                x: typeof item.x === 'number' ? item.x : 0,
                y: typeof item.y === 'number' ? item.y : 0,
                rotation: typeof item.rotation === 'number' ? item.rotation : 0,
                flipped: Boolean(item.flipped),
            }));
            nextId = placements.length;
        }
        if (Array.isArray(args.circles)) {
            guideCircles = buildGuideCircleList(args.circles);
            circleCounter = guideCircles.length;
            selectedCircleId = guideCircles.length ? guideCircles[guideCircles.length - 1].id : null;
        }
        if (typeof args.zoom === 'number') {
            zoom = Math.min(Math.max(args.zoom, MIN_ZOOM), MAX_ZOOM);
            updateZoomUI();
        }
        selectedId = placements.length ? placements[placements.length - 1].id : null;
        clampPan();
        draw();
        updateBoardOrientationLabel();
        updateSelectionLabel();
        renderCircleList();
        requestFrameHeight();
    }

    function updateSelectionLabel() {
        const label = document.getElementById('selectionLabel');
        const placement = placements.find(p => p.id === selectedId);
        const circle = getCircleById(selectedCircleId);
        if (placement) {
            const piece = libraryByCode[placement.code];
            label.textContent = placement.code + ' · ' + (piece ? piece.name : '');
            return;
        }
        if (circle) {
            label.textContent = circle.label || `Guide circle · $${circle.radius.toFixed(0)} mm`;
            return;
        }
        label.textContent = 'No piece selected';
    }

    document.querySelectorAll('.add-piece').forEach(button => {
        button.addEventListener('click', event => {
            const code = event.currentTarget.getAttribute('data-code');
            addPiece(code);
        });
    });

    document.querySelectorAll('.add-circle').forEach(button => {
        button.addEventListener('click', event => {
            const radius = parseFloat(event.currentTarget.getAttribute('data-radius'));
            if (!Number.isFinite(radius) || radius <= 0) { return; }
            const label = event.currentTarget.getAttribute('data-label') || `Radius $${radius.toFixed(0)} mm`;
            const newCircle = {
                id: 'circle-' + (circleCounter++),
                radius,
                x: boardCenter.x,
                y: boardCenter.y,
                color: nextCircleColour(),
                label,
            };
            guideCircles.push(newCircle);
            selectedCircleId = newCircle.id;
            selectedId = null;
            updateSelectionLabel();
            renderCircleList();
            draw();
            emitState();
        });
    });

    if (zoomSlider) {
        zoomSlider.addEventListener('input', event => {
            const target = parseFloat(event.target.value);
            if (Number.isFinite(target)) {
                setZoom(target, { x: canvas.width / 2, y: canvas.height / 2 });
            }
        });
    }

    if (resetViewButton) {
        resetViewButton.addEventListener('click', () => {
            resetView();
        });
    }

    if (rotateBoardLeftButton) {
        rotateBoardLeftButton.addEventListener('click', () => rotateBoard(-90));
    }
    if (rotateBoardRightButton) {
        rotateBoardRightButton.addEventListener('click', () => rotateBoard(90));
    }

    let dragging = false;
    let dragOffset = { x: 0, y: 0 };
    let viewPanning = false;
    let panPointerStart = { x: 0, y: 0 };
    let panStart = { x: 0, y: 0 };

    canvas.addEventListener('pointerdown', event => {
        const rect = canvas.getBoundingClientRect();
        const { x, y } = canvasToMm(event.clientX - rect.left, event.clientY - rect.top);
        for (let i = guideCircles.length - 1; i >= 0; i -= 1) {
            const circle = guideCircles[i];
            const distance = Math.hypot(x - circle.x, y - circle.y);
            if (distance <= circle.radius) {
                selectedCircleId = circle.id;
                selectedId = null;
                draggingCircleId = circle.id;
                circleDragOffset = { x: x - circle.x, y: y - circle.y };
                canvas.setPointerCapture(event.pointerId);
                updateSelectionLabel();
                renderCircleList();
                draw();
                return;
            }
        }
        let found = null;
        for (let i = placements.length - 1; i >= 0; i -= 1) {
            if (hitTest(placements[i], x, y)) {
                found = placements[i];
                break;
            }
        }
        if (found) {
            selectedId = found.id;
            selectedCircleId = null;
            dragOffset = { x: x - found.x, y: y - found.y };
            dragging = true;
            viewPanning = false;
            canvas.setPointerCapture(event.pointerId);
            const sectionIds = sectionMode ? connectedSectionIds(found.id) : [found.id];
            activeSectionIds = new Set(sectionIds);
            sectionInitialPositions.clear();
            sectionIds.forEach(id => {
                const piece = getPlacementById(id);
                if (piece) {
                    sectionInitialPositions.set(id, { x: piece.x, y: piece.y });
                }
            });
            updateSelectionLabel();
            draw();
        } else {
            selectedId = null;
            selectedCircleId = null;
            activeSectionIds = null;
            sectionInitialPositions.clear();
            viewPanning = false;
            updateSelectionLabel();
            if (event.button === 0) {
                viewPanning = true;
                panPointerStart = { x: event.clientX, y: event.clientY };
                panStart = { x: pan.x, y: pan.y };
                canvas.setPointerCapture(event.pointerId);
                event.preventDefault();
            }
            draw();
        }
    });

    canvas.addEventListener('pointermove', event => {
        if (draggingCircleId) {
            event.preventDefault();
            const rect = canvas.getBoundingClientRect();
            const { x, y } = canvasToMm(event.clientX - rect.left, event.clientY - rect.top);
            const circle = getCircleById(draggingCircleId);
            if (circle) {
                circle.x = x - circleDragOffset.x;
                circle.y = y - circleDragOffset.y;
                draw();
            }
            return;
        }
        if (viewPanning) {
            event.preventDefault();
            const dx = event.clientX - panPointerStart.x;
            const dy = event.clientY - panPointerStart.y;
            pan.x = panStart.x + dx;
            pan.y = panStart.y + dy;
            clampPan();
            draw();
            return;
        }
        if (!dragging || !selectedId) { return; }
        const placement = getPlacementById(selectedId);
        if (!placement) { return; }
        const rect = canvas.getBoundingClientRect();
        const { x, y } = canvasToMm(event.clientX - rect.left, event.clientY - rect.top);
        const initial = sectionInitialPositions.get(selectedId) || { x: placement.x, y: placement.y };
        const targetX = x - dragOffset.x;
        const targetY = y - dragOffset.y;
        const deltaX = targetX - initial.x;
        const deltaY = targetY - initial.y;
        const ids = activeSectionIds ? Array.from(activeSectionIds) : [selectedId];
        ids.forEach(id => {
            const piece = getPlacementById(id);
            const start = sectionInitialPositions.get(id);
            if (!piece || !start) { return; }
            piece.x = start.x + deltaX;
            piece.y = start.y + deltaY;
        });
        draw();
    });

    canvas.addEventListener('pointerup', event => {
        if (canvas.hasPointerCapture(event.pointerId)) {
            canvas.releasePointerCapture(event.pointerId);
        }
        let shouldEmit = false;
        if (dragging) {
            dragging = false;
            activeSectionIds = null;
            sectionInitialPositions.clear();
            shouldEmit = true;
        }
        if (viewPanning) {
            viewPanning = false;
            shouldEmit = true;
        }
        if (draggingCircleId) {
            draggingCircleId = null;
            renderCircleList();
            shouldEmit = true;
        }
        if (shouldEmit) {
            emitState();
        }
    });

    canvas.addEventListener('pointercancel', event => {
        if (canvas.hasPointerCapture(event.pointerId)) {
            canvas.releasePointerCapture(event.pointerId);
        }
        let shouldEmit = false;
        if (dragging) {
            dragging = false;
            activeSectionIds = null;
            sectionInitialPositions.clear();
            shouldEmit = true;
        }
        if (viewPanning) {
            viewPanning = false;
            shouldEmit = true;
        }
        if (draggingCircleId) {
            draggingCircleId = null;
            renderCircleList();
            shouldEmit = true;
        }
        if (shouldEmit) {
            emitState();
        }
    });

    canvas.addEventListener('wheel', event => {
        event.preventDefault();
        if (event.ctrlKey || event.metaKey) {
            const rect = canvas.getBoundingClientRect();
            const focus = {
                x: event.clientX - rect.left,
                y: event.clientY - rect.top,
            };
            const zoomFactor = Math.exp(-event.deltaY * 0.0015);
            setZoom(zoom * zoomFactor, focus);
        } else {
            pan.x -= event.deltaX;
            pan.y -= event.deltaY;
            clampPan();
            draw();
        }
    }, { passive: false });

    function hitTest(placement, x, y) {
        const piece = libraryByCode[placement.code];
        if (!piece) { return false; }
        const rotation = (placement.rotation || 0) * Math.PI / 180;
        const dx = x - placement.x;
        const dy = y - placement.y;
        const cos = Math.cos(rotation);
        const sin = Math.sin(rotation);
        const localX = cos * dx + sin * dy;
        const localY = -sin * dx + cos * dy;
        if (piece.kind === 'curve' && piece.radius) {
            const dist = Math.sqrt(dx * dx + dy * dy);
            return Math.abs(dist - piece.radius) < 60;
        }
        const length = piece.displayLength || piece.length || 0;
        return Math.abs(localX) <= length / 2 && Math.abs(localY) <= 50;
    }

    function adjustSelected(deltaRotation = 0, deltaX = 0, deltaY = 0) {
        const placement = getPlacementById(selectedId);
        if (!placement) { return; }
        const pivot = { x: placement.x, y: placement.y };
        const sectionIds = sectionMode ? connectedSectionIds(selectedId) : [selectedId];
        applySectionTransform(sectionIds, pivot, deltaRotation, deltaX, deltaY);
        draw();
        emitState();
    }

    document.getElementById('rotateLeft').addEventListener('click', () => adjustSelected(-15, 0, 0));
    document.getElementById('rotateRight').addEventListener('click', () => adjustSelected(15, 0, 0));
    document.getElementById('nudgeUp').addEventListener('click', () => adjustSelected(0, 0, 10));
    document.getElementById('nudgeDown').addEventListener('click', () => adjustSelected(0, 0, -10));
    document.getElementById('nudgeLeft').addEventListener('click', () => adjustSelected(0, -10, 0));
    document.getElementById('nudgeRight').addEventListener('click', () => adjustSelected(0, 10, 0));
    document.getElementById('flipPiece').addEventListener('click', () => {
        const placement = getPlacementById(selectedId);
        if (!placement) { return; }
        placement.flipped = !placement.flipped;
        draw();
        emitState();
    });

    document.getElementById('snapGrid').addEventListener('click', () => {
        const placement = getPlacementById(selectedId);
        if (!placement) { return; }
        const targetX = Math.round(placement.x / 10) * 10;
        const targetY = Math.round(placement.y / 10) * 10;
        const targetRotation = Math.round((placement.rotation || 0) / 15) * 15;
        const deltaX = targetX - placement.x;
        const deltaY = targetY - placement.y;
        const deltaRotation = normalizeDegrees(targetRotation - (placement.rotation || 0));
        const pivot = { x: placement.x, y: placement.y };
        const sectionIds = sectionMode ? connectedSectionIds(selectedId) : [selectedId];
        applySectionTransform(sectionIds, pivot, deltaRotation, deltaX, deltaY);
        const updatedPlacement = getPlacementById(selectedId);
        if (updatedPlacement) {
            updatedPlacement.rotation = ((targetRotation % 360) + 360) % 360;
        }
        draw();
        emitState();
    });

    document.getElementById('snapPiece').addEventListener('click', () => {
        const placement = getPlacementById(selectedId);
        if (!placement) { return; }
        const transform = findBestSnapTransform(placement);
        if (!transform) { return; }
        const pivot = { x: placement.x, y: placement.y };
        const sectionIds = sectionMode ? connectedSectionIds(selectedId) : [selectedId];
        applySectionTransform(sectionIds, pivot, transform.deltaRotationDeg, transform.deltaX, transform.deltaY);
        draw();
        emitState();
    });

    const sectionToggleButton = document.getElementById('toggleSectionMode');

    function updateSectionToggleButton() {
        if (!sectionToggleButton) { return; }
        sectionToggleButton.textContent = sectionMode ? 'Section move: On' : 'Section move: Off';
        sectionToggleButton.classList.toggle('primary', sectionMode);
    }

    if (sectionToggleButton) {
        sectionToggleButton.addEventListener('click', () => {
            sectionMode = !sectionMode;
            if (!sectionMode) {
                activeSectionIds = null;
                sectionInitialPositions.clear();
            }
            updateSectionToggleButton();
        });
    }
    document.getElementById('deletePiece').addEventListener('click', () => {
        if (selectedCircleId) {
            const circleIndex = guideCircles.findIndex(circle => circle.id === selectedCircleId);
            if (circleIndex !== -1) {
                guideCircles.splice(circleIndex, 1);
                selectedCircleId = guideCircles.length ? guideCircles[guideCircles.length - 1].id : null;
                renderCircleList();
                updateSelectionLabel();
                draw();
                emitState();
                return;
            }
        }
        const index = placements.findIndex(p => p.id === selectedId);
        if (index === -1) { return; }
        placements.splice(index, 1);
        selectedId = placements.length ? placements[placements.length - 1].id : null;
        activeSectionIds = null;
        sectionInitialPositions.clear();
        updateSelectionLabel();
        draw();
        emitState();
    });

    function renderCircleList() {
        const list = document.getElementById('circleList');
        if (!list) { return; }
        if (!guideCircles.length) {
            list.innerHTML = '<p class="hint">No planning circles added yet.</p>';
            requestFrameHeight();
            return;
        }
        const entries = guideCircles.map(circle => {
            const selected = circle.id === selectedCircleId ? ' selected' : '';
            const label = circle.label || `Radius $${circle.radius.toFixed(0)} mm`;
            const position = `Centre $${circle.x.toFixed(0)} mm · $${circle.y.toFixed(0)} mm`;
            const colour = circle.color || '#ff7f0e';
            return `
                <div class="circle-item$${selected}" data-id="$${circle.id}">
                    <span class="circle-swatch" style="background:$${colour}"></span>
                    <div class="circle-meta">
                        <div><strong>$${label}</strong></div>
                        <div>$${position}</div>
                    </div>
                    <div class="circle-actions">
                        <button type="button" data-action="remove" data-id="$${circle.id}">Remove</button>
                    </div>
                </div>
            `;
        });
        list.innerHTML = entries.join('');
        list.querySelectorAll('.circle-item').forEach(item => {
            item.addEventListener('click', () => {
                const id = item.getAttribute('data-id');
                if (!id) { return; }
                selectedCircleId = id;
                selectedId = null;
                updateSelectionLabel();
                renderCircleList();
                draw();
                emitState();
            });
        });
        list.querySelectorAll('button[data-action="remove"]').forEach(button => {
            button.addEventListener('click', event => {
                event.stopPropagation();
                const id = event.currentTarget.getAttribute('data-id');
                const index = guideCircles.findIndex(circle => circle.id === id);
                if (index !== -1) {
                    guideCircles.splice(index, 1);
                    if (selectedCircleId === id) {
                        selectedCircleId = guideCircles.length ? guideCircles[guideCircles.length - 1].id : null;
                    }
                    renderCircleList();
                    updateSelectionLabel();
                    draw();
                    emitState();
                }
            });
        });
        requestFrameHeight();
    }

    const saveLayoutButton = document.getElementById('saveLayout');
    if (saveLayoutButton) {
        saveLayoutButton.addEventListener('click', () => {
            const payload = emitState();
            const jsonText = JSON.stringify(payload, null, 2);
            const blob = new Blob([jsonText], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
            link.download = `layout-$${timestamp}.json`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            setTimeout(() => URL.revokeObjectURL(url), 1000);
        });
    }

    if (window.Streamlit && window.Streamlit.events && window.Streamlit.RENDER_EVENT) {
        window.Streamlit.events.addEventListener(window.Streamlit.RENDER_EVENT, event => {
            const detail = event && event.detail ? event.detail : {};
            applyRenderArgs(detail.args || {});
        });
    } else {
        window.addEventListener('message', event => {
            if (event && event.data && event.data.type === 'streamlit:render') {
                applyRenderArgs(event.data.args || {});
            }
        });
    }

    window.addEventListener('resize', () => {
        resizeCanvas();
        requestFrameHeight();
    });
    resizeCanvas();
    updateSelectionLabel();
    updateSectionToggleButton();
    renderCircleList();
    requestFrameHeight();
    announceReady();
    </script>
    """
    )

    html = html_template.substitute(
        library_cards="".join(library_cards),
        board_json=json.dumps(board_payload),
        track_json=json.dumps(track_payload),
        placements_json=json.dumps(placements),
        circles_json=json.dumps(circles),
        initial_zoom_json=json.dumps(clamped_initial_zoom),
    )

    _COMPONENT_INDEX.write_text(html, encoding="utf-8")
    component_value = _layout_designer_component(
        key="layout-designer",
        default=None,
        data_version=str(hash(html)),
        board=board_payload,
        library=track_payload,
        placements=placements,
        circles=circles,
        zoom=current_zoom,
    )
    if component_value is None:
        return placements, circles, current_zoom

    if not isinstance(component_value, str):
        return placements, circles, current_zoom

    try:
        parsed = json.loads(component_value)
    except json.JSONDecodeError:
        return placements, circles, current_zoom

    if not isinstance(parsed, dict):
        return placements, circles, current_zoom

    board_state = parsed.get("board")
    if isinstance(board_state, dict):
        orientation_value = board_state.get("orientation")
        if isinstance(orientation_value, (int, float)):
            st.session_state["board_orientation"] = float(orientation_value)

    payload = parsed.get("placements")
    zoom_value = parsed.get("zoom")
    circles_payload = parsed.get("circles")
    if isinstance(zoom_value, (int, float)):
        current_zoom = max(min(float(zoom_value), max_zoom), min_zoom)
    updated = placements
    if isinstance(payload, list):
        updated = [p for p in payload if isinstance(p, dict)]
    updated_circles = circles
    if isinstance(circles_payload, list):
        updated_circles = [c for c in circles_payload if isinstance(c, dict)]
    return updated, updated_circles, current_zoom


board = _board_controls()
st.sidebar.success(describe_board(board))

st.sidebar.header("Power planning")
supply_voltage = st.sidebar.number_input(
    "DCC supply voltage (V)",
    min_value=10.0,
    max_value=22.0,
    value=16.0,
    step=0.5,
)
expected_current = st.sidebar.number_input(
    "Expected simultaneous load (A)",
    min_value=0.1,
    max_value=5.0,
    value=1.5,
    step=0.1,
)

if "placements" not in st.session_state:
    st.session_state["placements"] = []

if "zoom" not in st.session_state:
    st.session_state["zoom"] = 1.0

if "circles" not in st.session_state:
    st.session_state["circles"] = []

if "board_orientation" not in st.session_state:
    st.session_state["board_orientation"] = 0.0

uploaded_layout = st.sidebar.file_uploader("Load layout JSON", type=["json"])
if uploaded_layout is not None:
    try:
        raw_text = uploaded_layout.getvalue().decode("utf-8")
        parsed_payload = json.loads(raw_text)
        loaded_placements, loaded_circles, loaded_zoom = _normalise_layout_payload(parsed_payload)
    except UnicodeDecodeError:
        st.sidebar.error("Could not decode the uploaded file. Please upload UTF-8 JSON.")
    except (json.JSONDecodeError, ValueError) as exc:
        st.sidebar.error(f"Unable to load layout: {exc}")
    else:
        st.session_state["placements"] = loaded_placements
        st.session_state["circles"] = loaded_circles
        if loaded_zoom is not None:
            st.session_state["zoom"] = loaded_zoom
        if isinstance(parsed_payload, dict):
            board_payload = parsed_payload.get("board")
            if isinstance(board_payload, dict):
                orientation_value = board_payload.get("orientation")
                if isinstance(orientation_value, (int, float)):
                    st.session_state["board_orientation"] = float(orientation_value)
        st.sidebar.success(f"Loaded {len(loaded_placements)} placement{'s' if len(loaded_placements) != 1 else ''} from layout.")

placements: List[Dict[str, object]] = st.session_state["placements"]
circles: List[Dict[str, object]] = st.session_state.get("circles", [])
current_zoom: float = float(st.session_state.get("zoom", 1.0))
placements, circles, current_zoom = _designer(board, placements, circles, current_zoom)
st.session_state["placements"] = placements
st.session_state["circles"] = circles
st.session_state["zoom"] = current_zoom

layout_payload = {
    "placements": placements,
    "circles": circles,
    "board": {
        "description": describe_board(board),
        "polygon": board.polygon_points(),
        "orientation": float(st.session_state.get("board_orientation", 0.0)),
    },
    "zoom": current_zoom,
}
st.sidebar.download_button(
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
