"""Data and helpers for the manual Hornby OO gauge planning interface."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import math


@dataclass(frozen=True)
class TrackPiece:
    """Represents a catalogue item from the Hornby OO gauge set-track range."""

    code: str
    name: str
    kind: str  # straight, curve, point, crossover, accessory
    length: float  # for straights and nominal size for specials (mm)
    angle: Optional[float] = None  # degrees for curves and turnouts
    radius: Optional[float] = None  # mm for curves and curved turnouts
    notes: Optional[str] = None

    def run_length(self) -> float:
        """Return the travel distance along the centre-line for the piece."""

        if self.kind == "curve" and self.radius and self.angle:
            return 2 * math.pi * self.radius * (self.angle / 360.0)
        return self.length


# A curated library of the most common Hornby set-track sections with real-world dimensions.
# The list purposely includes straight, curved, turnout and accessory pieces so the designer
# can build loops, sidings, crossovers and branch lines without switching context.
TRACK_LIBRARY: Dict[str, TrackPiece] = {
    "R600": TrackPiece("R600", "Standard Straight", "straight", 168.0),
    "R601": TrackPiece("R601", "Double Straight", "straight", 335.5),
    "R602": TrackPiece("R602", "Short Straight", "straight", 112.0),
    "R603": TrackPiece("R603", "Half Straight", "straight", 83.5),
    "R604": TrackPiece("R604", "Quarter Straight", "straight", 41.75),
    "R605": TrackPiece("R605", "Power Track", "straight", 168.0, notes="Insulated, power feed"),
    "R606": TrackPiece("R606", "1st Radius Curve (45°)", "curve", 0.0, angle=45.0, radius=371.0),
    "R607": TrackPiece("R607", "2nd Radius Curve (45°)", "curve", 0.0, angle=45.0, radius=438.0),
    "R608": TrackPiece("R608", "3rd Radius Curve (45°)", "curve", 0.0, angle=45.0, radius=505.0),
    "R609": TrackPiece("R609", "4th Radius Curve (45°)", "curve", 0.0, angle=45.0, radius=572.0),
    "R610": TrackPiece("R610", "1st Radius Curve (22.5°)", "curve", 0.0, angle=22.5, radius=371.0),
    "R611": TrackPiece("R611", "2nd Radius Curve (22.5°)", "curve", 0.0, angle=22.5, radius=438.0),
    "R612": TrackPiece("R612", "3rd Radius Curve (22.5°)", "curve", 0.0, angle=22.5, radius=505.0),
    "R613": TrackPiece("R613", "4th Radius Curve (22.5°)", "curve", 0.0, angle=22.5, radius=572.0),
    "R614": TrackPiece("R614", "90° Crossing", "crossover", 168.0, angle=90.0),
    "R615": TrackPiece("R615", "Double Curve (22.5°)", "curve", 0.0, angle=22.5, radius=438.0, notes="Superelevated"),
    "R617": TrackPiece("R617", "Level Crossing", "accessory", 168.0),
    "R618": TrackPiece("R618", "Buffer Stop", "accessory", 30.0),
    "R620": TrackPiece("R620", "Half Curve (22.5°)", "curve", 0.0, angle=22.5, radius=371.0),
    "R622": TrackPiece("R622", "Isolating Track", "straight", 168.0),
    "R8072": TrackPiece("R8072", "Left-hand Point", "point", 168.0, angle=12.0, radius=438.0),
    "R8073": TrackPiece("R8073", "Right-hand Point", "point", 168.0, angle=12.0, radius=438.0),
    "R8074": TrackPiece("R8074", "Y Point", "point", 168.0, angle=12.0, radius=505.0),
    "R8075": TrackPiece("R8075", "Curved Point Left", "point", 0.0, angle=22.5, radius=505.0),
    "R8076": TrackPiece("R8076", "Curved Point Right", "point", 0.0, angle=22.5, radius=505.0),
    "R8077": TrackPiece("R8077", "Diamond Crossing (12°)", "crossover", 185.0, angle=12.0),
    "R8078": TrackPiece("R8078", "Double Slip", "crossover", 185.0, angle=12.0),
    "R8079": TrackPiece("R8079", "Single Slip", "crossover", 185.0, angle=12.0),
    "R8201": TrackPiece("R8201", "Power Track (DCC)", "straight", 168.0),
    "R8202": TrackPiece("R8202", "Link Wire Track", "straight", 168.0),
    "R8232": TrackPiece("R8232", "Diamond Crossing (R2)", "crossover", 168.0, angle=22.5),
    "R8233": TrackPiece("R8233", "Double Track Level Crossing", "accessory", 168.0),
}


def library_by_kind(kind: str) -> Sequence[TrackPiece]:
    """Return all pieces matching the requested category."""

    return [piece for piece in TRACK_LIBRARY.values() if piece.kind == kind]


def track_library_as_rows() -> List[Tuple[str, str, str]]:
    """Return the library as simple tuples for display tables."""

    rows: List[Tuple[str, str, str]] = []
    for code, piece in sorted(TRACK_LIBRARY.items()):
        rows.append((code, piece.name, piece.kind.title()))
    return rows


def compute_piece_counts(placements: Iterable[Dict[str, object]]) -> Dict[str, int]:
    """Count how many instances of each catalogue item are placed."""

    totals: Dict[str, int] = {}
    for placement in placements:
        code = placement.get("code")
        if not isinstance(code, str):
            continue
        totals[code] = totals.get(code, 0) + 1
    return totals


def total_run_length_mm(placements: Iterable[Dict[str, object]]) -> float:
    """Total run length of the layout assembled so far."""

    total = 0.0
    for placement in placements:
        code = placement.get("code")
        if not isinstance(code, str):
            continue
        piece = TRACK_LIBRARY.get(code)
        if not piece:
            continue
        total += piece.run_length()
    return total


def board_polygon_for_rectangle(width: float, height: float) -> List[Tuple[float, float]]:
    """Create a polygon that outlines a rectangular board."""

    return [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)]


def board_polygon_for_l_shape(
    long_leg: float,
    short_leg: float,
    depth: float,
) -> List[Tuple[float, float]]:
    """Return the polygon for an L-shaped board."""

    return [
        (0.0, 0.0),
        (long_leg, 0.0),
        (long_leg, depth),
        (depth, depth),
        (depth, short_leg),
        (0.0, short_leg),
    ]


def normalise_polygon(points: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Translate a polygon so the minimum coordinate starts at the origin."""

    if not points:
        return []
    min_x = min(p[0] for p in points)
    min_y = min(p[1] for p in points)
    return [(x - min_x, y - min_y) for x, y in points]


def polygon_bounds(points: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    """Return the width and height of a polygon's bounding box."""

    if not points:
        return 0.0, 0.0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return max(xs) - min(xs), max(ys) - min(ys)

