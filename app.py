from typing import List, Tuple

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from planner import (
    BoardSpecification,
    LayoutGenerator,
    LayoutPlan,
    describe_board,
    default_templates,
    draw_geometry,
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

    st.sidebar.markdown("Enter the corner points of your board outline in millimetres.")
    default_points: List[Tuple[float, float]] = [(0.0, 0.0), (2400.0, 0.0), (2400.0, 1200.0), (0.0, 1200.0)]
    data = st.sidebar.data_editor(
        pd.DataFrame(default_points, columns=["x", "y"]),
        num_rows="dynamic",
        key="custom_polygon",
    )
    polygon = list(data.itertuples(index=False, name=None))
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
    breakdown = pd.DataFrame(
        plan.piece_breakdown(), columns=["Catalogue", "Piece", "Quantity"]
    )

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
        st.dataframe(breakdown, hide_index=True, use_container_width=True)

    with col2:
        geometry = plan.build_geometry()
        width, height = board.bounding_box()
        fig, ax = plt.subplots(figsize=(6, 4))
        draw_geometry(geometry, ax)
        half_width = width / 2
        half_height = height / 2
        ax.add_patch(
            plt.Rectangle(
                (-half_width, -half_height),
                width,
                height,
                fill=False,
                edgecolor="#555555",
                linestyle=":",
                linewidth=1.5,
            )
        )
        ax.set_aspect("equal", adjustable="box")
        ax.set_title("Track geometry preview")
        ax.set_xlabel("mm")
        ax.set_ylabel("mm")
        ax.grid(True, linestyle=":", linewidth=0.5)
        ax.set_xlim(-half_width - 200, half_width + 200)
        ax.set_ylim(-half_height - 200, half_height + 200)
        st.pyplot(fig, clear_figure=True)


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
