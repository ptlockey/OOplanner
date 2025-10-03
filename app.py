from __future__ import annotations

import json
from string import Template
from typing import Dict, List, Tuple

import streamlit as st
import streamlit.components.v1 as components

from planner import (
    BoardSpecification,
    describe_board,
    hornby_track_library,
    inventory_from_placements,
    total_run_length_mm,
)


st.set_page_config(page_title="Hornby OO Layout Planner", layout="wide")
st.title("Hornby OO Gauge Layout Planner")
st.write(
    """Lay out your own Hornby OO gauge plan directly on the baseboard outline.\n"
    "Define the board you are building, drag track from the library, rotate or flip pieces,"
    " and snap them together while the planner keeps an eye on inventory and total run length."""
)


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


def _designer(board: BoardSpecification, placements: List[Dict[str, object]]) -> List[Dict[str, object]]:
    library = hornby_track_library()
    board_polygon = board.polygon_points()
    board_payload = {
        "polygon": board_polygon,
        "description": describe_board(board),
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
        card = (
            "<div class=\"library-item\">"
            f"<strong>{item['code']}</strong><br/>"
            f"<span>{item['name']}</span><br/>"
            f"<small>{item['kind'].title()} · {item['displayLength']:.0f} mm</small>"
            f"<button data-code=\"{item['code']}\" class=\"add-piece\">Add to board</button>"
            "</div>"
        )
        library_cards.append(card)

    html_template = Template(
        """
    <style>
    .designer-wrapper {
        display: flex;
        gap: 1rem;
        font-family: 'Source Sans Pro', sans-serif;
    }
    .track-library {
        width: 260px;
        max-height: 640px;
        overflow-y: auto;
        border: 1px solid #d0d0d0;
        border-radius: 0.5rem;
        padding: 0.75rem;
        background: #f8f9fb;
    }
    .track-library h3 {
        margin-top: 0;
        font-size: 1.1rem;
    }
    .library-item {
        border: 1px solid #d7d7d7;
        border-radius: 0.4rem;
        padding: 0.5rem;
        margin-bottom: 0.5rem;
        background: #ffffff;
    }
    .library-item button {
        margin-top: 0.4rem;
        width: 100%;
        padding: 0.35rem 0.5rem;
        border-radius: 0.3rem;
        border: 1px solid #1f77b4;
        background: #1f77b4;
        color: white;
        cursor: pointer;
    }
    .board-canvas {
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
    }
    #boardCanvas {
        width: 100%;
        height: 560px;
        border: 2px solid #d0d0d0;
        border-radius: 0.5rem;
        background: #ffffff;
        touch-action: none;
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
    </style>
    <div class="designer-wrapper">
        <div class="track-library">
            <h3>Hornby Set-Track</h3>
            <p class="hint">Click "Add" to drop a piece onto the board. Drag pieces on the canvas and use the controls to rotate, flip, nudge or snap.</p>
            $library_cards
        </div>
        <div class="board-canvas">
            <canvas id="boardCanvas"></canvas>
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
        </div>
    </div>
    <script>
    const boardData = $board_json;
    const trackLibrary = $track_json;
    const initialPlacements = $placements_json;
    const libraryByCode = Object.fromEntries(trackLibrary.map(item => [item.code, item]));
    const placements = initialPlacements.map((item, idx) => ({
        id: item.id || ('placement-' + idx),
        code: item.code,
        x: typeof item.x === 'number' ? item.x : 0,
        y: typeof item.y === 'number' ? item.y : 0,
        rotation: typeof item.rotation === 'number' ? item.rotation : 0,
        flipped: Boolean(item.flipped),
    }));
    let nextId = placements.length;
    let selectedId = placements.length ? placements[placements.length - 1].id : null;
    let sectionMode = false;
    let activeSectionIds = null;
    const sectionInitialPositions = new Map();

    const canvas = document.getElementById('boardCanvas');
    const ctx = canvas.getContext('2d');

    const polygon = boardData.polygon && boardData.polygon.length ? boardData.polygon : [
        [0, 0], [2400, 0], [2400, 1200], [0, 1200]
    ];
    const xs = polygon.map(pt => pt[0]);
    const ys = polygon.map(pt => pt[1]);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const widthMm = Math.max(maxX - minX, 1);
    const heightMm = Math.max(maxY - minY, 1);
    const padding = 60;
    const SNAP_DISTANCE_MM = 200;
    const CONNECTION_TOLERANCE_MM = 6;
    const ANGLE_TOLERANCE_RAD = Math.PI / 12;

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

    function resizeCanvas() {
        const rect = canvas.getBoundingClientRect();
        canvas.width = rect.width;
        canvas.height = rect.height;
        draw();
        requestFrameHeight();
    }

    function mmToCanvas(x, y) {
        const scale = Math.min((canvas.width - padding * 2) / widthMm, (canvas.height - padding * 2) / heightMm);
        const cx = (x - minX) * scale + padding;
        const cy = canvas.height - ((y - minY) * scale + padding);
        return { x: cx, y: cy, scale };
    }

    function canvasToMm(x, y) {
        const scale = Math.min((canvas.width - padding * 2) / widthMm, (canvas.height - padding * 2) / heightMm);
        const mmX = (x - padding) / scale + minX;
        const mmY = ((canvas.height - y) - padding) / scale + minY;
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

    function draw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        drawBoard();
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
                return {
                    x: placement.x + rotated.x,
                    y: placement.y + rotated.y,
                    tangent: normalizeRadians(tangentLocalAngle + rotation),
                    localPosition,
                    localTangent: tangentLocalAngle,
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
            return {
                x: placement.x + rotated.x,
                y: placement.y + rotated.y,
                tangent: normalizeRadians(endpoint.localTangent + rotation),
                localPosition: endpoint.localPosition,
                localTangent: endpoint.localTangent,
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
        const angleDiff = Math.abs(normalizeRadians(endpointA.tangent - endpointB.tangent));
        return Math.abs(angleDiff - Math.PI) < ANGLE_TOLERANCE_RAD;
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
                    const angleDiff = Math.abs(normalizeRadians(endpoint.tangent - target.tangent));
                    if (Math.abs(angleDiff - Math.PI) >= ANGLE_TOLERANCE_RAD) { return; }
                    if (best && distance >= best.distance) { return; }
                    const desiredTangent = normalizeRadians(target.tangent + Math.PI);
                    const deltaRotationRad = normalizeRadians(desiredTangent - endpoint.tangent);
                    const deltaRotationDeg = normalizeDegrees(toDegrees(deltaRotationRad));
                    const newRotationDeg = (placement.rotation + deltaRotationDeg + 360) % 360;
                    const newRotationRad = toRadians(newRotationDeg);
                    const rotatedLocal = rotatePoint(endpoint.localPosition.x, endpoint.localPosition.y, newRotationRad);
                    const newCenterX = target.x - rotatedLocal.x;
                    const newCenterY = target.y - rotatedLocal.y;
                    const deltaX = newCenterX - placement.x;
                    const deltaY = newCenterY - placement.y;
                    best = {
                        distance,
                        deltaRotationDeg,
                        deltaX,
                        deltaY,
                    };
                });
            });
        });
        return best;
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
            board: boardData,
        };
        window.parent.postMessage({
            isStreamlitMessage: true,
            type: "streamlit:setComponentValue",
            value: JSON.stringify(payload),
        }, "*");
    }

    function requestFrameHeight() {
        window.parent.postMessage({
            isStreamlitMessage: true,
            type: "streamlit:setFrameHeight",
            height: document.body.scrollHeight,
        }, "*");
    }

    function addPiece(code) {
        const piece = libraryByCode[code];
        if (!piece) { return; }
        const newPlacement = {
            id: 'placement-' + nextId++,
            code,
            x: (minX + maxX) / 2,
            y: (minY + maxY) / 2,
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

    function updateSelectionLabel() {
        const label = document.getElementById('selectionLabel');
        const placement = placements.find(p => p.id === selectedId);
        if (!placement) {
            label.textContent = 'No piece selected';
        } else {
            const piece = libraryByCode[placement.code];
            label.textContent = placement.code + ' · ' + (piece ? piece.name : '');
        }
    }

    document.querySelectorAll('.add-piece').forEach(button => {
        button.addEventListener('click', event => {
            const code = event.currentTarget.getAttribute('data-code');
            addPiece(code);
        });
    });

    let dragging = false;
    let dragOffset = { x: 0, y: 0 };

    canvas.addEventListener('pointerdown', event => {
        const rect = canvas.getBoundingClientRect();
        const { x, y } = canvasToMm(event.clientX - rect.left, event.clientY - rect.top);
        let found = null;
        for (let i = placements.length - 1; i >= 0; i -= 1) {
            if (hitTest(placements[i], x, y)) {
                found = placements[i];
                break;
            }
        }
        if (found) {
            selectedId = found.id;
            dragOffset = { x: x - found.x, y: y - found.y };
            dragging = true;
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
            activeSectionIds = null;
            sectionInitialPositions.clear();
            updateSelectionLabel();
            draw();
        }
    });

    canvas.addEventListener('pointermove', event => {
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
        dragging = false;
        activeSectionIds = null;
        sectionInitialPositions.clear();
        if (canvas.hasPointerCapture(event.pointerId)) {
            canvas.releasePointerCapture(event.pointerId);
        }
        emitState();
    });

    canvas.addEventListener('pointercancel', event => {
        dragging = false;
        activeSectionIds = null;
        sectionInitialPositions.clear();
        if (canvas.hasPointerCapture(event.pointerId)) {
            canvas.releasePointerCapture(event.pointerId);
        }
        emitState();
    });

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

    window.addEventListener('resize', resizeCanvas);
    resizeCanvas();
    updateSelectionLabel();
    updateSectionToggleButton();
    requestFrameHeight();
    </script>
    """
    )

    html = html_template.substitute(
        library_cards="".join(library_cards),
        board_json=json.dumps(board_payload),
        track_json=json.dumps(track_payload),
        placements_json=json.dumps(placements),
    )

    component_value = components.html(html, height=720, scrolling=True)
    if component_value is None:
        return placements
    parsed: Dict[str, object]
    if isinstance(component_value, str):
        try:
            parsed = json.loads(component_value)
        except json.JSONDecodeError:
            return placements
    elif isinstance(component_value, dict):
        parsed = component_value
    else:
        return placements
    payload = parsed.get("placements") if isinstance(parsed, dict) else None
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    return placements


board = _board_controls()
st.sidebar.success(describe_board(board))

if "placements" not in st.session_state:
    st.session_state["placements"] = []

placements: List[Dict[str, object]] = st.session_state["placements"]
placements = _designer(board, placements)
st.session_state["placements"] = placements


library = hornby_track_library()
inventory = inventory_from_placements(placements)
total_length_mm = total_run_length_mm(placements)

st.subheader("Inventory summary")
cols = st.columns(3)
cols[0].metric("Pieces placed", sum(inventory.values()))
cols[1].metric("Unique catalogue items", len(inventory))
cols[2].metric("Run length", f"{total_length_mm/1000:.2f} m")

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
