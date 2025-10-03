"""Utility primitives for the interactive Hornby OO layout planner."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import math


@dataclass(frozen=True)
class TrackPiece:
    """Represents a single catalogue item from the Hornby track range."""

    code: str
    name: str
    kind: str
    length: float  # straight length or equivalent primary dimension in mm
    angle: Optional[float] = None  # degrees for curves
    radius: Optional[float] = None  # mm for curves

    def arc_length(self) -> float:
        """Return the length along the centreline for curved pieces."""
        if self.kind != "curve" or self.angle is None or self.radius is None:
            return 0.0
        return 2 * math.pi * self.radius * (self.angle / 360.0)


TRACK_LIBRARY: Dict[str, TrackPiece] = {
    # Core straights
    "R600": TrackPiece("R600", "Standard Straight", "straight", 168.0),
    "R601": TrackPiece("R601", "Double Straight", "straight", 335.5),
    "R602": TrackPiece("R602", "Short Straight", "straight", 111.0),
    "R603": TrackPiece("R603", "Half Straight", "straight", 67.0),
    "R604": TrackPiece("R604", "Quarter Straight", "straight", 41.0),
    "R618": TrackPiece("R618", "Buffer Stop Track", "special", 76.0),
    "R627": TrackPiece("R627", "Level Crossing Straight", "special", 168.0),
    # Flexible and specialist straights
    "R6102": TrackPiece("R6102", "Flexi Track (914mm)", "flex", 914.0),
    "R6143": TrackPiece("R6143", "Platform Straight", "special", 168.0),
    # Curves by radius and angle
    "R605": TrackPiece("R605", "1st Radius Curve (90°)", "curve", 0.0, angle=90.0, radius=371.0),
    "R606": TrackPiece("R606", "1st Radius Curve (45°)", "curve", 0.0, angle=45.0, radius=371.0),
    "R607": TrackPiece("R607", "2nd Radius Curve (45°)", "curve", 0.0, angle=45.0, radius=438.0),
    "R608": TrackPiece("R608", "3rd Radius Curve (45°)", "curve", 0.0, angle=45.0, radius=505.0),
    "R609": TrackPiece("R609", "4th Radius Curve (45°)", "curve", 0.0, angle=45.0, radius=572.0),
    "R610": TrackPiece("R610", "1st Radius Curve (22.5°)", "curve", 0.0, angle=22.5, radius=371.0),
    "R611": TrackPiece("R611", "2nd Radius Curve (22.5°)", "curve", 0.0, angle=22.5, radius=438.0),
    "R612": TrackPiece("R612", "3rd Radius Curve (22.5°)", "curve", 0.0, angle=22.5, radius=505.0),
    "R613": TrackPiece("R613", "4th Radius Curve (22.5°)", "curve", 0.0, angle=22.5, radius=572.0),
    # Points, crossings and specialist pieces
    "R8072": TrackPiece("R8072", "Left-hand Point", "point", 168.0),
    "R8073": TrackPiece("R8073", "Right-hand Point", "point", 168.0),
    "R8074": TrackPiece("R8074", "Y Point", "point", 168.0),
    "R8075": TrackPiece("R8075", "Curved Point LH", "point", 168.0, angle=22.5, radius=371.0),
    "R8076": TrackPiece("R8076", "Curved Point RH", "point", 168.0, angle=22.5, radius=371.0),
    "R8099": TrackPiece("R8099", "Double Slip", "special", 168.0),
    "R614": TrackPiece("R614", "90° Crossing", "special", 168.0),
    "R615": TrackPiece("R615", "30° Crossing", "special", 168.0),
    "R628": TrackPiece("R628", "Diamond Crossing", "special", 168.0),
}


@dataclass
class BoardSpecification:
    """Representation of the work surface for the layout designer."""

    shape: str
    width: float
    height: float
    polygon: Optional[List[Tuple[float, float]]] = None

    def bounding_box(self) -> Tuple[float, float]:
        """Return width/height of the board envelope."""
        points = self.polygon_points()
        if not points:
            return self.width, self.height
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return max(xs) - min(xs), max(ys) - min(ys)

    def polygon_points(self) -> List[Tuple[float, float]]:
        """Return the polygon describing the working area."""
        if self.polygon:
            return list(self.polygon)
        if self.shape == "rectangle":
            return [
                (0.0, 0.0),
                (self.width, 0.0),
                (self.width, self.height),
                (0.0, self.height),
            ]
        if self.shape == "l-shape":
            return [
                (0.0, 0.0),
                (self.width, 0.0),
                (self.width, self.height / 2.0),
                (self.height / 2.0, self.height / 2.0),
                (self.height / 2.0, self.height),
                (0.0, self.height),
            ]
        return []


def hornby_track_library() -> Dict[str, TrackPiece]:
    """Return the Hornby set-track items available to the designer."""

    return TRACK_LIBRARY


def piece_display_length(piece: TrackPiece) -> float:
    """Return the running length of a track piece in millimetres."""

    if piece.kind == "curve":
        return piece.arc_length()
    return piece.length


def inventory_from_placements(placements: Sequence[Dict[str, object]]) -> Dict[str, int]:
    """Calculate how many of each catalogue code have been placed."""

    counts: Dict[str, int] = {}
    for placement in placements:
        code = placement.get("code")
        if not isinstance(code, str):
            continue
        counts[code] = counts.get(code, 0) + 1
    return counts


def total_run_length_mm(placements: Sequence[Dict[str, object]]) -> float:
    """Return the cumulative running length of the placed track pieces."""

    total = 0.0
    for placement in placements:
        code = placement.get("code")
        if not isinstance(code, str):
            continue
        piece = TRACK_LIBRARY.get(code)
        if not piece:
            continue
        total += piece_display_length(piece)
    return total


def describe_board(board: BoardSpecification) -> str:
    """Provide a human readable description of the board."""

    width, height = board.bounding_box()
    dims = f"{width/1000:.2f} m x {height/1000:.2f} m"
    if board.shape == "rectangle":
        return f"Rectangular board {dims}"
    if board.shape == "l-shape":
        return f"L-shaped board envelope {dims}"
    if board.shape == "custom":
        return f"Custom board bounding box {dims}"
    return dims
