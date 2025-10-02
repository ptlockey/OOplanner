"""Layout planning utilities for the Streamlit Hornby OO gauge planner app."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

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
    "R600": TrackPiece("R600", "Standard Straight", "straight", 168.0),
    "R601": TrackPiece("R601", "Double Straight", "straight", 335.5),
    "R603": TrackPiece("R603", "Half Straight", "straight", 67.0),
    "R604": TrackPiece("R604", "Quarter Straight", "straight", 41.0),
    "R606": TrackPiece("R606", "1st Radius Curve (45°)", "curve", length=0.0, angle=45.0, radius=371.0),
    "R607": TrackPiece("R607", "2nd Radius Curve (45°)", "curve", length=0.0, angle=45.0, radius=438.0),
    "R608": TrackPiece("R608", "3rd Radius Curve (45°)", "curve", length=0.0, angle=45.0, radius=505.0),
    "R609": TrackPiece("R609", "4th Radius Curve (45°)", "curve", length=0.0, angle=45.0, radius=572.0),
    "R610": TrackPiece("R610", "1st Radius Curve (22.5°)", "curve", length=0.0, angle=22.5, radius=371.0),
    "R614": TrackPiece("R614", "90° Crossing", "special", 168.0),
    "R8072": TrackPiece("R8072", "Left-hand Point", "point", 168.0),
    "R8073": TrackPiece("R8073", "Right-hand Point", "point", 168.0),
}


@dataclass
class GeometryCommand:
    """Instruction used to draw the preview of a layout."""

    command: str
    parameters: Tuple[float, ...]


@dataclass
class LayoutPlan:
    """Full definition of a layout proposal."""

    name: str
    description: str
    pieces: Dict[str, int]
    footprint: Tuple[float, float]
    features: Set[str]
    radii_used: Set[float]
    notes: List[str] = field(default_factory=list)
    geometry_factory: Optional[Callable[["LayoutPlan"], List[GeometryCommand]]] = None

    def total_length_mm(self) -> float:
        total = 0.0
        for code, count in self.pieces.items():
            piece = TRACK_LIBRARY.get(code)
            if not piece:
                continue
            if piece.kind == "curve":
                total += piece.arc_length() * count
            else:
                total += piece.length * count
        return total

    def straight_length_mm(self) -> float:
        total = 0.0
        for code, count in self.pieces.items():
            piece = TRACK_LIBRARY.get(code)
            if not piece:
                continue
            if piece.kind in {"straight", "point", "special"}:
                total += piece.length * count
        return total

    def curve_length_mm(self) -> float:
        total = 0.0
        for code, count in self.pieces.items():
            piece = TRACK_LIBRARY.get(code)
            if not piece:
                continue
            if piece.kind == "curve":
                total += piece.arc_length() * count
        return total

    def piece_breakdown(self) -> List[Tuple[str, str, int]]:
        breakdown: List[Tuple[str, str, int]] = []
        for code, count in sorted(self.pieces.items()):
            piece = TRACK_LIBRARY.get(code)
            name = piece.name if piece else "Unknown"
            breakdown.append((code, name, count))
        return breakdown

    def build_geometry(self) -> List[GeometryCommand]:
        if self.geometry_factory is None:
            return []
        return self.geometry_factory(self)

    def fits_within(self, width: float, height: float) -> bool:
        footprint_width, footprint_height = self.footprint
        return footprint_width <= width and footprint_height <= height


@dataclass
class BoardSpecification:
    shape: str
    width: float
    height: float
    polygon: Optional[List[Tuple[float, float]]] = None

    def bounding_box(self) -> Tuple[float, float]:
        if self.shape == "custom" and self.polygon:
            xs = [p[0] for p in self.polygon]
            ys = [p[1] for p in self.polygon]
            return max(xs) - min(xs), max(ys) - min(ys)
        return self.width, self.height


def _linspace(start: float, end: float, steps: int) -> List[float]:
    if steps <= 1:
        return [start]
    delta = (end - start) / (steps - 1)
    return [start + i * delta for i in range(steps)]


def _oval_points(
    radius: float,
    straight_total: float,
    offset: Tuple[float, float] = (0.0, 0.0),
    samples: int = 120,
) -> List[Tuple[float, float]]:
    """Create a closed oval represented as (x, y) coordinate pairs."""

    quarter = max(2, samples // 4)
    half_straight = straight_total / 2.0
    ox, oy = offset

    points: List[Tuple[float, float]] = []

    # Top straight (right to left for continuity)
    for x in _linspace(half_straight, -half_straight, quarter):
        points.append((ox + x, oy + radius))

    # Left arc (90° to 270°)
    for theta in _linspace(math.pi / 2, 3 * math.pi / 2, quarter):
        x = -half_straight + radius * math.cos(theta)
        y = radius * math.sin(theta)
        points.append((ox + x, oy + y))

    # Bottom straight (left to right)
    for x in _linspace(-half_straight, half_straight, quarter):
        points.append((ox + x, oy - radius))

    # Right arc (-90° to 90°)
    for theta in _linspace(-math.pi / 2, math.pi / 2, quarter):
        x = half_straight + radius * math.cos(theta)
        y = radius * math.sin(theta)
        points.append((ox + x, oy + y))

    if points:
        points.append(points[0])
    return points


def render_geometry_svg(
    commands: Sequence[GeometryCommand],
    board_width: float,
    board_height: float,
) -> str:
    """Render layout geometry to an SVG snippet suitable for embedding in Streamlit."""

    if not commands:
        return (
            "<div style=\"border:1px solid #e6e6e6;padding:0.5rem;background-color:#fafafa;\">"
            "<p><em>No track preview available for this layout.</em></p>"
            "</div>"
        )

    track_shapes: List[Tuple[str, List[Tuple[float, float]]]] = []
    line_shapes: List[Tuple[str, Tuple[float, float, float, float]]] = []
    markers: List[Tuple[float, float]] = []

    min_x = float("inf")
    max_x = float("-inf")
    min_y = float("inf")
    max_y = float("-inf")

    def include_point(x: float, y: float) -> None:
        nonlocal min_x, max_x, min_y, max_y
        min_x = min(min_x, x)
        max_x = max(max_x, x)
        min_y = min(min_y, y)
        max_y = max(max_y, y)

    if board_width > 0 and board_height > 0:
        half_w = board_width / 2.0
        half_h = board_height / 2.0
        include_point(-half_w, -half_h)
        include_point(half_w, half_h)

    for command in commands:
        if command.command == "oval":
            radius, straight_total, ox, oy = command.parameters
            pts = _oval_points(radius, straight_total, (ox, oy))
            for x, y in pts:
                include_point(x, y)
            track_shapes.append(("oval", pts))
        elif command.command in {"line", "siding"}:
            x1, y1, x2, y2 = command.parameters
            include_point(x1, y1)
            include_point(x2, y2)
            line_shapes.append((command.command, (x1, y1, x2, y2)))
        elif command.command == "marker":
            x, y = command.parameters
            include_point(x, y)
            markers.append((x, y))

    if min_x == float("inf"):
        min_x, max_x = -500.0, 500.0
        min_y, max_y = -500.0, 500.0

    margin = 150.0
    min_x -= margin
    max_x += margin
    min_y -= margin
    max_y += margin

    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)

    def to_svg_point(x: float, y: float) -> Tuple[float, float]:
        return x - min_x, max_y - y

    parts: List[str] = []
    parts.append(
        "<div style=\"border:1px solid #e6e6e6;padding:0.5rem;background-color:#fafafa;\">"
    )
    parts.append(
        f'<svg viewBox="0 0 {span_x:.1f} {span_y:.1f}" '
        "preserveAspectRatio=\"xMidYMid meet\" style=\"width:100%;height:auto;\">"
    )

    if board_width > 0 and board_height > 0:
        half_w = board_width / 2.0
        half_h = board_height / 2.0
        top_left = to_svg_point(-half_w, half_h)
        parts.append(
            f'<rect x="{top_left[0]:.1f}" y="{top_left[1]:.1f}" '
            f'width="{board_width:.1f}" height="{board_height:.1f}" '
            'fill="none" stroke="#555555" stroke-dasharray="6 6" stroke-width="2" />'
        )

    for _, pts in track_shapes:
        svg_points = " ".join(
            f"{to_svg_point(x, y)[0]:.1f},{to_svg_point(x, y)[1]:.1f}" for x, y in pts
        )
        parts.append(
            f'<polyline points="{svg_points}" fill="none" stroke="#1f77b4" stroke-width="4" />'
        )

    for kind, (x1, y1, x2, y2) in line_shapes:
        sx1, sy1 = to_svg_point(x1, y1)
        sx2, sy2 = to_svg_point(x2, y2)
        dash = ' stroke-dasharray="10 6"' if kind == "siding" else ""
        colour = "#ff7f0e" if kind == "siding" else "#1f77b4"
        parts.append(
            f'<line x1="{sx1:.1f}" y1="{sy1:.1f}" x2="{sx2:.1f}" y2="{sy2:.1f}" '
            f'stroke="{colour}" stroke-width="4"{dash} />'
        )

    for x, y in markers:
        sx, sy = to_svg_point(x, y)
        parts.append(
            f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="6" fill="#2ca02c" />'
        )

    parts.append("</svg>")
    parts.append("</div>")
    return "".join(parts)


class LayoutGenerator:
    """Selects layout templates that meet the user's brief."""

    def __init__(self, templates: Iterable[LayoutPlan]):
        self.templates = list(templates)

    def generate(
        self,
        board: BoardSpecification,
        objectives: Set[str],
        allowed_radii: Set[float],
        max_layouts: int = 5,
    ) -> List[LayoutPlan]:
        width, height = board.bounding_box()
        required_features = set()
        if "Include loops" in objectives:
            required_features.add("loop")
        if "Include spurs/sidings" in objectives:
            required_features.add("spur")
        if "Include fiddle yard" in objectives:
            required_features.add("fiddle_yard")

        candidates: List[Tuple[float, LayoutPlan]] = []
        for template in self.templates:
            if not template.fits_within(width, height):
                continue
            if required_features and not required_features.issubset(template.features):
                continue
            if allowed_radii and not template.radii_used.issubset(allowed_radii):
                continue

            score = self._score(template, objectives)
            candidates.append((score, template))

        reverse = True
        if "Minimise total track" in objectives and "Maximise track coverage" not in objectives:
            reverse = False

        candidates.sort(key=lambda item: item[0], reverse=reverse)
        return [tpl for _, tpl in candidates[:max_layouts]]

    def _score(self, template: LayoutPlan, objectives: Set[str]) -> float:
        total = template.total_length_mm()
        straights = template.straight_length_mm()
        score = 0.0
        if not objectives:
            score = total
        if "Maximise track coverage" in objectives:
            score += total
        if "Maximise straight running" in objectives:
            score += straights * 1.25
        if "Minimise total track" in objectives:
            score -= total
        if "Encourage complex operations" in objectives and "fiddle_yard" in template.features:
            score += 500.0
        if "Encourage complex operations" in objectives and "spur" in template.features:
            score += 250.0
        if "Prefer multiple loops" in objectives and "multi_loop" in template.features:
            score += 500.0
        return score


CLEARANCE = 120.0  # mm of margin around templates to give realistic space


def _oval_geometry_factory(radius: float, straight_count: int, straight_code: str) -> Callable[[LayoutPlan], List[GeometryCommand]]:
    piece = TRACK_LIBRARY[straight_code]
    straight_total = piece.length * (straight_count / 2)

    def factory(_: LayoutPlan) -> List[GeometryCommand]:
        return [GeometryCommand("oval", (radius, straight_total, 0.0, 0.0))]

    return factory


def _oval_with_siding_geometry_factory(radius: float, straight_code: str, siding_length: float) -> Callable[[LayoutPlan], List[GeometryCommand]]:
    piece = TRACK_LIBRARY[straight_code]
    straight_total = piece.length * 2

    def factory(_: LayoutPlan) -> List[GeometryCommand]:
        commands = [GeometryCommand("oval", (radius, straight_total, 0.0, 0.0))]
        commands.append(
            GeometryCommand(
                "siding",
                (-straight_total / 2, radius + 60.0, -straight_total / 2 - siding_length, radius + 60.0),
            )
        )
        commands.append(
            GeometryCommand(
                "siding",
                (-straight_total / 2 + 30.0, radius + 60.0, -straight_total / 2 + 30.0, radius + 120.0),
            )
        )
        return commands

    return factory


def _double_oval_geometry_factory(inner_radius: float, outer_radius: float, straight_length: float) -> Callable[[LayoutPlan], List[GeometryCommand]]:
    half = straight_length

    def factory(_: LayoutPlan) -> List[GeometryCommand]:
        commands = [
            GeometryCommand("oval", (outer_radius, half * 2, 0.0, 0.0)),
            GeometryCommand("oval", (inner_radius, (half - 60.0) * 2, 0.0, 0.0)),
            GeometryCommand("line", (-half - inner_radius, 0.0, -half - inner_radius, -200.0)),
            GeometryCommand("line", (-half - inner_radius, -200.0, -half + inner_radius, -200.0)),
        ]
        return commands

    return factory


def _figure_eight_geometry_factory(radius: float, straight_length: float) -> Callable[[LayoutPlan], List[GeometryCommand]]:
    half = straight_length / 2

    def factory(_: LayoutPlan) -> List[GeometryCommand]:
        left_center = (-half, 0.0)
        right_center = (half, 0.0)
        commands = [GeometryCommand("line", (left_center[0], radius, right_center[0], -radius))]
        commands.append(GeometryCommand("oval", (radius, straight_length, *left_center)))
        commands.append(GeometryCommand("oval", (radius, straight_length, *right_center)))
        return commands

    return factory


def _fiddle_yard_geometry_factory(main_length: float, sidings: int, spacing: float = 70.0) -> Callable[[LayoutPlan], List[GeometryCommand]]:
    def factory(_: LayoutPlan) -> List[GeometryCommand]:
        commands = [GeometryCommand("line", (-main_length / 2, 0.0, main_length / 2, 0.0))]
        for i in range(1, sidings + 1):
            offset = i * spacing
            commands.append(GeometryCommand("siding", (-main_length / 2 + 200.0, offset, main_length / 2, offset)))
        return commands

    return factory


def default_templates() -> List[LayoutPlan]:
    templates: List[LayoutPlan] = []

    # Compact oval (1st radius)
    radius = TRACK_LIBRARY["R606"].radius or 0.0
    straight_piece = TRACK_LIBRARY["R600"].length
    straight_total = straight_piece * 2
    footprint = (2 * radius + straight_total + CLEARANCE, 2 * radius + CLEARANCE)
    templates.append(
        LayoutPlan(
            name="Compact Continuous Oval",
            description="A simple 1st radius oval ideal for very small boards and continuous running.",
            pieces={"R606": 8, "R600": 4},
            footprint=footprint,
            features={"loop", "compact"},
            radii_used={radius},
            notes=["Add power clips to any straight for track power."],
            geometry_factory=_oval_geometry_factory(radius, 4, "R600"),
        )
    )

    # Standard oval with passing loop
    radius = TRACK_LIBRARY["R607"].radius or 0.0
    straight_length = TRACK_LIBRARY["R600"].length
    straight_total = straight_length * 2
    footprint = (2 * radius + straight_total + CLEARANCE + 180.0, 2 * radius + CLEARANCE + 140.0)
    templates.append(
        LayoutPlan(
            name="Passing Loop Oval",
            description="2nd radius oval with a passing loop for two-train operation or station stops.",
            pieces={
                "R607": 8,
                "R600": 6,
                "R603": 2,
                "R8072": 1,
                "R8073": 1,
            },
            footprint=footprint,
            features={"loop", "spur"},
            radii_used={radius},
            notes=["Points form a loop on the top straight allowing trains to pass."],
            geometry_factory=_oval_with_siding_geometry_factory(radius, "R600", 400.0),
        )
    )

    # Double track oval
    inner_radius = TRACK_LIBRARY["R607"].radius or 0.0
    outer_radius = TRACK_LIBRARY["R608"].radius or 0.0
    straight_length = TRACK_LIBRARY["R600"].length * 2
    footprint = (2 * outer_radius + straight_length + CLEARANCE + 160.0, 2 * outer_radius + CLEARANCE + 120.0)
    templates.append(
        LayoutPlan(
            name="Twin Track Mainline",
            description="Paired 2nd and 3rd radius loops for continuous two-train running with a crossover.",
            pieces={
                "R608": 8,
                "R607": 8,
                "R600": 8,
                "R8072": 2,
                "R8073": 2,
            },
            footprint=footprint,
            features={"loop", "multi_loop", "max_track"},
            radii_used={inner_radius, outer_radius},
            notes=["Use opposing points as a scissors crossover between the loops."],
            geometry_factory=_double_oval_geometry_factory(inner_radius, outer_radius, straight_length / 2),
        )
    )

    # Large oval with fiddle yard
    radius = TRACK_LIBRARY["R609"].radius or 0.0
    straight_length = TRACK_LIBRARY["R601"].length * 2
    footprint = (2 * radius + straight_length + CLEARANCE + 420.0, 2 * radius + CLEARANCE + 200.0)
    templates.append(
        LayoutPlan(
            name="Mainline with Fiddle Yard",
            description="4th radius oval with extended straights feeding a three-road fiddle yard.",
            pieces={
                "R609": 8,
                "R601": 4,
                "R8072": 3,
                "R8073": 3,
                "R600": 6,
            },
            footprint=footprint,
            features={"loop", "fiddle_yard", "spur", "max_track"},
            radii_used={radius},
            notes=["Three sidings can store full-length trains ready to enter the mainline."],
            geometry_factory=_fiddle_yard_geometry_factory(straight_length + 2 * radius, sidings=3),
        )
    )

    # End-to-end with fiddle yard
    main_length = 2400.0
    footprint = (main_length + CLEARANCE, 600.0 + CLEARANCE)
    templates.append(
        LayoutPlan(
            name="End-to-End Terminus",
            description="End-to-end layout with a three road fiddle yard and long platform straight.",
            pieces={
                "R601": 8,
                "R600": 6,
                "R603": 4,
                "R8072": 3,
                "R8073": 3,
            },
            footprint=footprint,
            features={"fiddle_yard", "spur", "terminus"},
            radii_used=set(),
            notes=["Ideal for shunting and timetable operations without requiring continuous running."],
            geometry_factory=_fiddle_yard_geometry_factory(main_length, sidings=3),
        )
    )

    # Compact shunting puzzle
    footprint = (1600.0 + CLEARANCE, 600.0 + CLEARANCE)
    templates.append(
        LayoutPlan(
            name="Shunting Puzzle Yard",
            description="A Inglenook-inspired yard using set-track pieces for switching challenges.",
            pieces={
                "R600": 10,
                "R603": 6,
                "R604": 4,
                "R8072": 2,
                "R8073": 1,
            },
            footprint=footprint,
            features={"spur", "operations"},
            radii_used=set(),
            notes=["Lengths suit three wagon trains in the longest siding and two wagons elsewhere."],
            geometry_factory=_fiddle_yard_geometry_factory(1200.0, sidings=2),
        )
    )

    # Figure eight continuous run
    radius = TRACK_LIBRARY["R607"].radius or 0.0
    straight_length = TRACK_LIBRARY["R600"].length * 2
    footprint = (straight_length * 2 + 2 * radius + CLEARANCE, 2 * radius + straight_length + CLEARANCE)
    templates.append(
        LayoutPlan(
            name="Figure Eight with Crossing",
            description="Continuous run with grade-level crossover for visual interest and reversing loops.",
            pieces={
                "R607": 16,
                "R600": 4,
                "R614": 1,
            },
            footprint=footprint,
            features={"loop", "crossover", "max_track"},
            radii_used={radius},
            notes=["Consider using power districts to avoid shorts through the crossing."],
            geometry_factory=_figure_eight_geometry_factory(radius, straight_length),
        )
    )

    return templates


def describe_board(board: BoardSpecification) -> str:
    width, height = board.bounding_box()
    dims = f"{width/1000:.2f} m x {height/1000:.2f} m"
    if board.shape == "rectangle":
        return f"Rectangular board {dims}"
    if board.shape == "l-shape":
        return f"L-shaped board envelope {dims}"
    if board.shape == "custom":
        return f"Custom board bounding box {dims}"
    return dims
