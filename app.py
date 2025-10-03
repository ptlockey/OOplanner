import json
from dataclasses import asdict
from typing import Dict, List, Optional, Sequence, Tuple

import streamlit as st
import streamlit.components.v1 as components

from planner import (
    TRACK_LIBRARY,
    TrackPiece,
    board_polygon_for_l_shape,
    board_polygon_for_rectangle,
    compute_piece_counts,
    normalise_polygon,
    polygon_bounds,
    total_run_length_mm,
)


st.set_page_config(page_title="Hornby OO Gauge Board Planner", layout="wide")


def _board_controls() -> Tuple[Dict[str, float], List[Tuple[float, float]]]:
    st.sidebar.header("Board configuration")
    shape = st.sidebar.selectbox("Board shape", ["Rectangle", "L-Shape", "Custom polygon"], index=0)

    if shape == "Rectangle":
        width = st.sidebar.number_input("Width (mm)", min_value=600.0, value=2400.0, step=50.0)
        depth = st.sidebar.number_input("Depth (mm)", min_value=450.0, value=1200.0, step=50.0)
        polygon = board_polygon_for_rectangle(width, depth)
        return {"shape": "rectangle", "width": width, "height": depth}, polygon

    if shape == "L-Shape":
        long_leg = st.sidebar.number_input("Long leg (mm)", min_value=1200.0, value=2400.0, step=50.0)
        short_leg = st.sidebar.number_input("Short leg (mm)", min_value=900.0, value=1500.0, step=50.0)
        depth = st.sidebar.number_input("Depth (mm)", min_value=450.0, value=900.0, step=25.0)
        polygon = board_polygon_for_l_shape(long_leg, short_leg, depth)
        return {"shape": "l-shape", "width": long_leg, "height": short_leg}, polygon

    st.sidebar.markdown(
        "Enter corner points in millimetres, one per line as `x,y`. Points are connected in the order provided."
    )
    default_points = "\n".join(["0,0", "2400,0", "2400,1200", "0,1200"])
    raw_points = st.sidebar.text_area("Polygon points", value=default_points, height=150, key="custom_polygon_input")
    polygon: List[Tuple[float, float]] = []
    invalid = 0
    for line in raw_points.splitlines():
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) != 2:
            invalid += 1
            continue
        try:
            x_val = float(parts[0].strip())
            y_val = float(parts[1].strip())
        except ValueError:
            invalid += 1
            continue
        polygon.append((x_val, y_val))

    if invalid:
        st.sidebar.warning(f"Skipped {invalid} invalid coordinate line{'s' if invalid != 1 else ''}.")

    polygon = normalise_polygon(polygon)
    width, height = polygon_bounds(polygon)
    return {"shape": "polygon", "width": width, "height": height}, polygon


def _grid_controls() -> Dict[str, float]:
    st.sidebar.header("Layout helpers")
    snap = st.sidebar.number_input("Grid snap (mm)", min_value=1.0, value=25.0, step=1.0)
    fine_snap = st.sidebar.number_input("Fine snap (mm)", min_value=0.5, value=5.0, step=0.5)
    return {"snap": snap, "fineSnap": fine_snap}


def _prepare_library_for_js(pieces: Sequence[TrackPiece]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for piece in pieces:
        row = asdict(piece)
        rows.append(row)
    return rows


def _build_designer_html(
    board: Dict[str, float],
    polygon: Sequence[Tuple[float, float]],
    grid: Dict[str, float],
    pieces: Sequence[TrackPiece],
    existing_state: Optional[Dict[str, object]],
) -> str:
    polygon_json = json.dumps(polygon)
    board_json = json.dumps(board)
    grid_json = json.dumps(grid)
    library_json = json.dumps(_prepare_library_for_js(pieces))
    state_json = json.dumps(existing_state or {"placements": []})

    template = """
<style>
    .planner-wrapper {
        display: grid;
        grid-template-columns: 260px minmax(420px, 1fr) 240px;
        gap: 1.25rem;
        font-family: 'Inter', sans-serif;
    }
    .planner-pane {
        background: #ffffff;
        border: 1px solid #d9d9d9;
        border-radius: 8px;
        padding: 0.75rem 0.9rem;
        box-shadow: 0 1px 2px rgba(0,0,0,0.04);
        display: flex;
        flex-direction: column;
    }
    .planner-pane h3 {
        margin: 0 0 0.5rem;
        font-size: 1.05rem;
        font-weight: 600;
    }
    .library-list {
        overflow-y: auto;
        flex: 1;
        border-top: 1px solid #e6e6e6;
        padding-top: 0.5rem;
    }
    .library-item {
        border: 1px solid #e0e0e0;
        border-radius: 6px;
        padding: 0.45rem 0.5rem;
        margin-bottom: 0.45rem;
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
        background: #fafafa;
    }
    .library-item button {
        align-self: flex-start;
        background: #ff4b4b;
        border: none;
        color: white;
        border-radius: 4px;
        padding: 0.25rem 0.6rem;
        cursor: pointer;
        font-size: 0.82rem;
    }
    .library-item button:hover {
        background: #ff2d2d;
    }
    .board-pane {
        position: relative;
        min-height: 520px;
    }
    .board-svg {
        width: 100%;
        height: 100%;
        background: #f9fafb;
        border-radius: 8px;
    }
    .board-instructions {
        font-size: 0.82rem;
        color: #555555;
        margin-top: 0.5rem;
        line-height: 1.4;
    }
    .board-instructions code {
        background: #f0f0f0;
        padding: 0.05rem 0.25rem;
        border-radius: 3px;
        font-size: 0.78rem;
    }
    .piece {
        cursor: grab;
    }
    .piece.dragging {
        cursor: grabbing;
    }
    .piece path {
        fill: #d1d5db;
        stroke: #374151;
        stroke-width: 1.6;
    }
    .piece.selected path {
        stroke: #fb923c;
        stroke-width: 2.2;
    }
    .endpoint {
        fill: #9ca3af;
        stroke: #1f2937;
        stroke-width: 0.6;
    }
    .endpoint.connected {
        fill: #10b981;
    }
    .inventory-list {
        flex: 1;
        overflow-y: auto;
        border-top: 1px solid #e6e6e6;
        padding-top: 0.5rem;
        font-size: 0.85rem;
    }
    .inventory-list table {
        width: 100%;
        border-collapse: collapse;
    }
    .inventory-list th,
    .inventory-list td {
        text-align: left;
        padding: 0.2rem 0.1rem;
        border-bottom: 1px solid #ececec;
    }
    .inventory-empty {
        color: #6b7280;
        font-style: italic;
    }
</style>
<div class="planner-wrapper">
  <div class="planner-pane">
    <h3>Track library</h3>
    <div class="library-list" id="library-list"></div>
  </div>
  <div class="planner-pane board-pane">
    <svg class="board-svg" id="board-canvas" viewBox="0 0 10 10"></svg>
    <div class="board-instructions">
        Drag pieces onto the board. Use <code>R</code>/<code>Shift+R</code> to rotate, <code>F</code> to flip, arrow keys to nudge, and <code>Delete</code> to remove the selected piece. Hold <code>Alt</code> while dragging to temporarily disable grid snapping.
    </div>
  </div>
  <div class="planner-pane">
    <h3>Placed pieces</h3>
    <div class="inventory-list" id="inventory"></div>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/streamlit-component-lib@1.2.0/dist/index.min.js"></script>
<script>
const BOARD = __BOARD__;
const POLYGON = __POLYGON__;
const GRID = __GRID__;
const LIBRARY = __LIBRARY__;
let state = __STATE__;
let placements = Array.isArray(state.placements) ? state.placements.slice() : [];
let selectedId = null;
let dragInfo = null;
let syncTimer = null;

const SNAP = GRID.snap || 1.0;
const FINE_SNAP = GRID.fineSnap || Math.max(SNAP / 5, 1.0);

const libraryList = document.getElementById('library-list');
const inventoryList = document.getElementById('inventory');
const svg = document.getElementById('board-canvas');

const mmBounds = (() => {
    if (!Array.isArray(POLYGON) || !POLYGON.length) {
        return { minX: 0, minY: 0, width: BOARD.width || 0, height: BOARD.height || 0 };
    }
    let minX = POLYGON[0][0];
    let minY = POLYGON[0][1];
    let maxX = POLYGON[0][0];
    let maxY = POLYGON[0][1];
    POLYGON.forEach(([x, y]) => {
        if (x < minX) minX = x;
        if (y < minY) minY = y;
        if (x > maxX) maxX = x;
        if (y > maxY) maxY = y;
    });
    return { minX, minY, width: maxX - minX, height: maxY - minY };
})();

const toSvgPoint = (clientX, clientY) => {
    const point = svg.createSVGPoint();
    point.x = clientX;
    point.y = clientY;
    const inverted = point.matrixTransform(svg.getScreenCTM().inverse());
    return { x: inverted.x, y: inverted.y };
};

const snapValue = (value, increment) => {
    if (!increment || increment <= 0) return value;
    return Math.round(value / increment) * increment;
};

const createPiecePath = (piece) => {
    const halfWidth = 16; // Hornby track is ~32mm wide
    if (piece.kind === 'straight' || piece.kind === 'point' || piece.kind === 'accessory' || piece.kind === 'crossover') {
        const len = piece.length || 0;
        return `M 0 ${-halfWidth} L ${len} ${-halfWidth} L ${len} ${halfWidth} L 0 ${halfWidth} Z`;
    }
    if (piece.kind === 'curve') {
        const radius = piece.radius || 0;
        const angle = (piece.angle || 0) * Math.PI / 180;
        const largeArc = (piece.angle || 0) > 180 ? 1 : 0;
        const outer = radius + halfWidth;
        const inner = Math.max(radius - halfWidth, 1);
        const thetaEnd = angle - Math.PI / 2;
        const outerEndX = outer * Math.cos(thetaEnd);
        const outerEndY = radius + outer * Math.sin(thetaEnd);
        const innerEndX = inner * Math.cos(thetaEnd);
        const innerEndY = radius + inner * Math.sin(thetaEnd);
        return [
            `M 0 ${-halfWidth}`,
            `A ${outer} ${outer} 0 ${largeArc} 1 ${outerEndX} ${outerEndY}`,
            `L ${innerEndX} ${innerEndY}`,
            `A ${inner} ${inner} 0 ${largeArc} 0 0 ${halfWidth}`,
            'Z',
        ].join(' ');
    }
    return '';
};

const pieceLocalEnd = (piece) => {
    if (piece.kind === 'curve') {
        const radius = piece.radius || 0;
        const angleRad = (piece.angle || 0) * Math.PI / 180;
        const x = radius * Math.cos(angleRad - Math.PI / 2);
        const y = radius + radius * Math.sin(angleRad - Math.PI / 2);
        return { x, y };
    }
    const len = piece.length || 0;
    return { x: len, y: 0 };
};

const transformPoint = (placement, point) => {
    const scaleX = placement.flipped ? -1 : 1;
    const angle = (placement.rotation || 0) * Math.PI / 180;
    const xScaled = scaleX * point.x;
    const yScaled = point.y;
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    const xRot = xScaled * cos - yScaled * sin;
    const yRot = xScaled * sin + yScaled * cos;
    return { x: xRot + placement.x, y: yRot + placement.y };
};

const transformVector = (placement, vector) => {
    const scaleX = placement.flipped ? -1 : 1;
    const angle = (placement.rotation || 0) * Math.PI / 180;
    const xScaled = scaleX * vector.x;
    const yScaled = vector.y;
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    return { x: xScaled * cos - yScaled * sin, y: xScaled * sin + yScaled * cos };
};

const endpointsFor = (placement, piece) => {
    const start = transformPoint(placement, { x: 0, y: 0 });
    const endLocal = pieceLocalEnd(piece);
    const end = transformPoint(placement, endLocal);
    const dir = transformVector(placement, { x: 1, y: 0 });
    const endDir = transformVector(placement, { x: Math.cos((piece.angle || 0) * Math.PI / 180), y: Math.sin((piece.angle || 0) * Math.PI / 180) });
    return [
        { x: start.x, y: start.y, dir },
        { x: end.x, y: end.y, dir: endDir },
    ];
};

const placementPath = (placement, piece) => {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', createPiecePath(piece));
    return path;
};

const placementGroup = (placement, piece) => {
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.classList.add('piece');
    g.dataset.id = placement.id;
    if (placement.id === selectedId) {
        g.classList.add('selected');
    }
    const path = placementPath(placement, piece);
    g.appendChild(path);

    const endpoints = endpointsFor(placement, piece);
    endpoints.forEach((pt, index) => {
        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.classList.add('endpoint');
        circle.dataset.endpoint = `${placement.id}:${index}`;
        circle.setAttribute('cx', pt.x);
        circle.setAttribute('cy', pt.y);
        circle.setAttribute('r', 6);
        svgEndpoints.push({ element: circle, x: pt.x, y: pt.y });
        g.appendChild(circle);
    });

    const transform = placementTransform(placement);
    g.setAttribute('transform', transform);
    return g;
};

const placementTransform = (placement) => {
    const scaleX = placement.flipped ? -1 : 1;
    const angle = placement.rotation || 0;
    const cos = Math.cos(angle * Math.PI / 180);
    const sin = Math.sin(angle * Math.PI / 180);
    const a = cos * scaleX;
    const b = sin * scaleX;
    const c = -sin;
    const d = cos;
    const e = placement.x;
    const f = placement.y;
    return `matrix(${a} ${b} ${c} ${d} ${e} ${f})`;
};

const renderBoard = () => {
    while (svg.firstChild) {
        svg.removeChild(svg.firstChild);
    }

    const viewWidth = mmBounds.width || 10;
    const viewHeight = mmBounds.height || 10;
    svg.setAttribute('viewBox', `${mmBounds.minX} ${mmBounds.minY} ${viewWidth} ${viewHeight}`);

    const gridGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    gridGroup.setAttribute('stroke', '#e5e7eb');
    gridGroup.setAttribute('stroke-width', 0.6);
    const spacing = Math.max(SNAP, 10);
    for (let x = 0; x <= viewWidth; x += spacing) {
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', mmBounds.minX + x);
        line.setAttribute('y1', mmBounds.minY);
        line.setAttribute('x2', mmBounds.minX + x);
        line.setAttribute('y2', mmBounds.minY + viewHeight);
        line.setAttribute('opacity', x % (spacing * 2) === 0 ? 0.6 : 0.3);
        gridGroup.appendChild(line);
    }
    for (let y = 0; y <= viewHeight; y += spacing) {
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', mmBounds.minX);
        line.setAttribute('y1', mmBounds.minY + y);
        line.setAttribute('x2', mmBounds.minX + viewWidth);
        line.setAttribute('y2', mmBounds.minY + y);
        line.setAttribute('opacity', y % (spacing * 2) === 0 ? 0.6 : 0.3);
        gridGroup.appendChild(line);
    }
    svg.appendChild(gridGroup);

    const outline = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    const poly = POLYGON.length ? POLYGON : [
        [0, 0],
        [BOARD.width || 0, 0],
        [BOARD.width || 0, BOARD.height || 0],
        [0, BOARD.height || 0],
    ];
    const d = poly.map((pt, index) => `${index ? 'L' : 'M'} ${pt[0]} ${pt[1]}`).join(' ') + ' Z';
    outline.setAttribute('d', d);
    outline.setAttribute('fill', '#fefefe');
    outline.setAttribute('stroke', '#111827');
    outline.setAttribute('stroke-width', 4);
    svg.appendChild(outline);

    svgPieces = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    svgPieces.setAttribute('id', 'svg-pieces');
    svg.appendChild(svgPieces);

    redrawPieces();
};

const redrawPieces = () => {
    if (!svgPieces) return;
    while (svgPieces.firstChild) {
        svgPieces.removeChild(svgPieces.firstChild);
    }
    svgEndpoints = [];
    placements.forEach((placement) => {
        const piece = LIBRARY.find((item) => item.code === placement.code);
        if (!piece) return;
        const group = placementGroup(placement, piece);
        svgPieces.appendChild(group);
    });
    highlightConnections();
};

const highlightConnections = () => {
    const tolerance = 6;
    svgEndpoints.forEach((endpoint) => {
        endpoint.element.classList.remove('connected');
    });
    for (let i = 0; i < svgEndpoints.length; i += 1) {
        for (let j = i + 1; j < svgEndpoints.length; j += 1) {
            const a = svgEndpoints[i];
            const b = svgEndpoints[j];
            const dx = a.x - b.x;
            const dy = a.y - b.y;
            if (Math.hypot(dx, dy) <= tolerance) {
                a.element.classList.add('connected');
                b.element.classList.add('connected');
            }
        }
    }
};

const updateInventory = () => {
    const counts = {};
    placements.forEach((placement) => {
        counts[placement.code] = (counts[placement.code] || 0) + 1;
    });
    const codes = Object.keys(counts).sort();
    if (!codes.length) {
        inventoryList.innerHTML = '<p class="inventory-empty">No track has been placed yet.</p>';
        return;
    }
    const rows = codes.map((code) => {
        const piece = LIBRARY.find((item) => item.code === code);
        const name = piece ? piece.name : 'Unknown piece';
        return `<tr><td>${code}</td><td>${name}</td><td style="text-align:right;">${counts[code]}</td></tr>`;
    }).join('');
    inventoryList.innerHTML = `<table><thead><tr><th>Code</th><th>Piece</th><th style="text-align:right;">Qty</th></tr></thead><tbody>${rows}</tbody></table>`;
};

const scheduleSync = () => {
    if (syncTimer) {
        clearTimeout(syncTimer);
    }
    syncTimer = setTimeout(() => {
        const payload = { placements: placements.map((p) => ({ ...p })) };
        Streamlit.setComponentValue(JSON.stringify(payload));
    }, 120);
};

const ensureIds = () => {
    placements.forEach((placement, index) => {
        if (!placement.id) {
            placement.id = `piece-${Date.now()}-${index}-${Math.random().toString(36).slice(2, 7)}`;
        }
        if (typeof placement.rotation !== 'number') {
            placement.rotation = 0;
        }
        if (typeof placement.x !== 'number') {
            placement.x = (mmBounds.minX + mmBounds.width / 2) || 0;
        }
        if (typeof placement.y !== 'number') {
            placement.y = (mmBounds.minY + mmBounds.height / 2) || 0;
        }
        if (typeof placement.flipped !== 'boolean') {
            placement.flipped = false;
        }
    });
};

const addPiece = (code) => {
    const piece = LIBRARY.find((item) => item.code === code);
    if (!piece) return;
    const placement = {
        id: `piece-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        code,
        x: (mmBounds.minX + mmBounds.width / 2) || 0,
        y: (mmBounds.minY + mmBounds.height / 2) || 0,
        rotation: 0,
        flipped: false,
    };
    placements.push(placement);
    selectedId = placement.id;
    redrawPieces();
    updateInventory();
    scheduleSync();
};

const removeSelected = () => {
    if (!selectedId) return;
    placements = placements.filter((placement) => placement.id !== selectedId);
    selectedId = null;
    redrawPieces();
    updateInventory();
    scheduleSync();
};

const rotateSelected = (increment) => {
    const placement = placements.find((item) => item.id === selectedId);
    if (!placement) return;
    placement.rotation = (placement.rotation + increment + 360) % 360;
    redrawPieces();
    updateInventory();
    scheduleSync();
};

const flipSelected = () => {
    const placement = placements.find((item) => item.id === selectedId);
    if (!placement) return;
    placement.flipped = !placement.flipped;
    redrawPieces();
    updateInventory();
    scheduleSync();
};

const nudgeSelected = (dx, dy, fine) => {
    const placement = placements.find((item) => item.id === selectedId);
    if (!placement) return;
    const snap = fine ? FINE_SNAP : SNAP;
    placement.x = snapValue(placement.x + dx, snap);
    placement.y = snapValue(placement.y + dy, snap);
    redrawPieces();
    updateInventory();
    scheduleSync();
};

const handlePointerDown = (event) => {
    const group = event.target.closest('.piece');
    if (!group) return;
    const id = group.dataset.id;
    selectedId = id;
    redrawPieces();
    updateInventory();
    const placement = placements.find((item) => item.id === id);
    if (!placement) return;
    group.classList.add('dragging');
    const svgPoint = toSvgPoint(event.clientX, event.clientY);
    dragInfo = {
        id,
        offsetX: svgPoint.x - placement.x,
        offsetY: svgPoint.y - placement.y,
        snapping: !event.altKey,
    };
    svg.setPointerCapture(event.pointerId);
    event.preventDefault();
};

const handlePointerMove = (event) => {
    if (!dragInfo) return;
    const placement = placements.find((item) => item.id === dragInfo.id);
    if (!placement) return;
    const svgPoint = toSvgPoint(event.clientX, event.clientY);
    const snap = event.shiftKey ? FINE_SNAP : SNAP;
    let x = svgPoint.x - dragInfo.offsetX;
    let y = svgPoint.y - dragInfo.offsetY;
    if (dragInfo.snapping && !event.altKey) {
        x = snapValue(x, snap);
        y = snapValue(y, snap);
    }
    placement.x = x;
    placement.y = y;
    redrawPieces();
    updateInventory();
    scheduleSync();
};

const handlePointerUp = (event) => {
    if (dragInfo) {
        const group = svg.querySelector(`.piece[data-id="${dragInfo.id}"]`);
        if (group) {
            group.classList.remove('dragging');
        }
    }
    dragInfo = null;
    svg.releasePointerCapture(event.pointerId);
};

const handleClick = (event) => {
    const group = event.target.closest('.piece');
    if (!group) {
        selectedId = null;
        redrawPieces();
        updateInventory();
        return;
    }
    selectedId = group.dataset.id;
    redrawPieces();
    updateInventory();
};

svg.addEventListener('pointerdown', handlePointerDown);
svg.addEventListener('pointermove', handlePointerMove);
svg.addEventListener('pointerup', handlePointerUp);
svg.addEventListener('pointerleave', handlePointerUp);
svg.addEventListener('click', handleClick);

window.addEventListener('keydown', (event) => {
    if (!selectedId) return;
    if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault();
        removeSelected();
    } else if (event.key.toLowerCase() === 'r') {
        event.preventDefault();
        rotateSelected(event.shiftKey ? 11.25 : 22.5);
    } else if (event.key.toLowerCase() === 'f') {
        event.preventDefault();
        flipSelected();
    } else if (event.key === 'ArrowLeft') {
        event.preventDefault();
        nudgeSelected(-SNAP, 0, event.shiftKey);
    } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        nudgeSelected(SNAP, 0, event.shiftKey);
    } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        nudgeSelected(0, -SNAP, event.shiftKey);
    } else if (event.key === 'ArrowDown') {
        event.preventDefault();
        nudgeSelected(0, SNAP, event.shiftKey);
    }
});

const renderLibrary = () => {
    const groups = {};
    LIBRARY.forEach((piece) => {
        const kind = piece.kind || 'other';
        if (!groups[kind]) {
            groups[kind] = [];
        }
        groups[kind].push(piece);
    });
    const order = ['straight', 'curve', 'point', 'crossover', 'accessory', 'other'];
    libraryList.innerHTML = '';
    order.forEach((kind) => {
        if (!groups[kind] || !groups[kind].length) return;
        const header = document.createElement('div');
        header.style.fontWeight = '600';
        header.style.margin = '0.35rem 0 0.2rem';
        header.textContent = kind.charAt(0).toUpperCase() + kind.slice(1);
        libraryList.appendChild(header);
        groups[kind]
            .sort((a, b) => a.code.localeCompare(b.code))
            .forEach((piece) => {
                const item = document.createElement('div');
                item.className = 'library-item';
                const title = document.createElement('div');
                title.style.fontWeight = '600';
                title.textContent = `${piece.code}`;
                const subtitle = document.createElement('div');
                subtitle.textContent = piece.name;
                subtitle.style.fontSize = '0.82rem';
                const details = document.createElement('div');
                details.style.fontSize = '0.75rem';
                details.style.color = '#4b5563';
                const info = [];
                if (piece.length) info.push(`${piece.length} mm`);
                if (piece.radius) info.push(`Radius ${piece.radius} mm`);
                if (piece.angle) info.push(`${piece.angle}°`);
                details.textContent = info.join(' · ');
                const button = document.createElement('button');
                button.textContent = 'Add to board';
                button.addEventListener('click', () => addPiece(piece.code));
                item.appendChild(title);
                item.appendChild(subtitle);
                if (info.length) {
                    item.appendChild(details);
                }
                if (piece.notes) {
                    const notes = document.createElement('div');
                    notes.textContent = piece.notes;
                    notes.style.fontSize = '0.72rem';
                    notes.style.color = '#6b7280';
                    item.appendChild(notes);
                }
                item.appendChild(button);
                libraryList.appendChild(item);
            });
    });
};

let svgPieces = null;
let svgEndpoints = [];

ensureIds();
renderLibrary();
renderBoard();
updateInventory();
Streamlit.setFrameHeight(document.querySelector('.planner-wrapper').offsetHeight + 24);
</script>
"""

    return (
        template
        .replace("__BOARD__", board_json)
        .replace("__POLYGON__", polygon_json)
        .replace("__GRID__", grid_json)
        .replace("__LIBRARY__", library_json)
        .replace("__STATE__", state_json)
    )


st.title("Interactive Hornby OO Gauge Layout Planner")
st.write(
    "Design your layout directly on a board that matches your real-world space. Drag set-track sections from the library, align them on the board, and build spurs or loops with precise Hornby dimensions."
)

board_config, polygon = _board_controls()
grid_config = _grid_controls()

if "layout_state" not in st.session_state:
    st.session_state["layout_state"] = {"placements": []}

def _describe_piece(piece: Optional[TrackPiece]) -> str:
    if not piece:
        return ""
    bits: List[str] = []
    if piece.length:
        bits.append(f"{piece.length:.0f} mm")
    if piece.radius:
        bits.append(f"Radius {piece.radius:.0f} mm")
    if piece.angle:
        bits.append(f"{piece.angle:.1f}°")
    return " · ".join(bits)


designer_html = _build_designer_html(
    board_config,
    polygon,
    grid_config,
    list(TRACK_LIBRARY.values()),
    st.session_state.get("layout_state"),
)

component_value = components.html(designer_html, height=640, scrolling=True, key="designer")

if component_value:
    try:
        new_state = json.loads(component_value)
    except json.JSONDecodeError:
        new_state = st.session_state.get("layout_state", {"placements": []})
    else:
        st.session_state["layout_state"] = new_state

layout_state = st.session_state.get("layout_state", {"placements": []})
placements = layout_state.get("placements", [])

st.subheader("Layout summary")

if placements:
    total_length = total_run_length_mm(placements)
    st.metric("Total run length", f"{total_length/1000:.2f} m")
    counts = compute_piece_counts(placements)
    summary_rows = []
    for code, quantity in sorted(counts.items()):
        piece = TRACK_LIBRARY.get(code)
        summary_rows.append(
            {
                "Catalogue": code,
                "Piece": piece.name if piece else "Unknown",
                "Quantity": quantity,
                "Details": _describe_piece(piece),
            }
        )
    st.dataframe(summary_rows, hide_index=True, use_container_width=True)
else:
    st.info("Add track pieces to the board to see an inventory summary here.")


st.caption(
    "Tip: use the grid snap controls in the sidebar to match the spacing of your actual baseboard markings."
)

