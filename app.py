from typing import List, Tuple

import streamlit as st

from planner import (
    BoardSpecification,
    LayoutGenerator,
    LayoutPlan,
    describe_board,
    default_templates,
    render_geometry_svg,
)


st.set_page_config(page_title="Hornby OO Layout Planner", layout="wide")
st.title("Hornby OO Gauge Layout Planner")
st.write(
    """Design OO gauge train set plans by choosing a baseboard size and the features you would like in your layout.\n"
    "The planner uses real-world Hornby set-track dimensions to recommend track plans that fit within your available space."""
)


@st.cache_resource
def get_generator() -> LayoutGenerator:
    return LayoutGenerator(default_templates())


def _board_controls() -> BoardSpecification:
    st.sidebar.header("Board")
    shape = st.sidebar.selectbox("Board shape", ["Rectangle", "L-Shape", "Custom polygon"], index=0)

    if shape == "Rectangle":
        width = st.sidebar.number_input("Width (mm)", min_value=600.0, value=1800.0, step=50.0)
        height = st.sidebar.number_input("Depth (mm)", min_value=450.0, value=1200.0, step=50.0)
        return BoardSpecification(shape="rectangle", width=width, height=height)

    if shape == "L-Shape":
        long_leg = st.sidebar.number_input("Long leg length (mm)", min_value=1000.0, value=2400.0, step=50.0)
        short_leg = st.sidebar.number_input("Short leg length (mm)", min_value=800.0, value=1500.0, step=50.0)
        width = st.sidebar.number_input("Overall width (mm)", min_value=600.0, value=900.0, step=25.0)
        polygon = [(0.0, 0.0), (long_leg, 0.0), (long_leg, width), (width, width), (width, short_leg), (0.0, short_leg)]
        return BoardSpecification(shape="l-shape", width=long_leg, height=short_leg, polygon=polygon)

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
        height=120,
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
    return BoardSpecification(
        shape="custom",
        width=max(p[0] for p in polygon) if polygon else 0.0,
        height=max(p[1] for p in polygon) if polygon else 0.0,
        polygon=polygon,
    )


def _objective_controls() -> Tuple[List[str], List[float]]:
    st.sidebar.header("Layout priorities")
    objectives = st.sidebar.multiselect(
        "Choose the goals that matter to you",
        [
            "Maximise track coverage",
            "Maximise straight running",
            "Include loops",
            "Include spurs/sidings",
            "Include fiddle yard",
            "Minimise total track",
            "Encourage complex operations",
            "Prefer multiple loops",
        ],
        default=["Include loops"],
    )

    allowed_radii = st.sidebar.multiselect(
        "Allowed curve radii",
        options=[371.0, 438.0, 505.0, 572.0],
        format_func=lambda v: f"{v:.0f} mm",
        default=[371.0, 438.0, 505.0, 572.0],
    )
    return objectives, allowed_radii


def _render_plan(plan: LayoutPlan, board: BoardSpecification) -> None:
    total_length = plan.total_length_mm() / 1000
    straight_length = plan.straight_length_mm() / 1000
    curve_length = plan.curve_length_mm() / 1000
    breakdown_rows = [
        {"Catalogue": code, "Piece": name, "Quantity": count}
        for code, name, count in plan.piece_breakdown()
    ]

    col1, col2 = st.columns([1, 1])
    with col1:
        st.subheader(plan.name)
        st.write(plan.description)
        st.metric("Total track length", f"{total_length:.2f} m")
        st.metric("Straight sections", f"{straight_length:.2f} m")
        st.metric("Curved sections", f"{curve_length:.2f} m")
        st.write("**Features:** " + ", ".join(sorted(plan.features)))
        if plan.notes:
            st.markdown("**Notes:**")
            for note in plan.notes:
                st.markdown(f"- {note}")
        st.dataframe(breakdown_rows, hide_index=True, use_container_width=True)

    with col2:
        geometry = plan.build_geometry()
        width, height = board.bounding_box()
        svg = render_geometry_svg(geometry, width, height)
        st.markdown(svg, unsafe_allow_html=True)


board = _board_controls()
objectives, allowed_radii = _objective_controls()
st.sidebar.header("Results")
max_layouts = st.sidebar.slider("Number of layout options", min_value=1, max_value=6, value=3)

st.info(describe_board(board))

if allowed_radii:
    allowed_radii_set = set(allowed_radii)
else:
    allowed_radii_set = set()

generator = get_generator()
layouts = generator.generate(board, set(objectives), allowed_radii_set, max_layouts=max_layouts)

if not layouts:
    st.warning("No layouts match the chosen board size and goals. Try expanding the allowed radii or relaxing priorities.")
else:
    for plan in layouts:
        st.divider()
        _render_plan(plan, board)
