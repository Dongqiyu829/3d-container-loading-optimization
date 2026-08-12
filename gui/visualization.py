"""Matplotlib canvas for canonical container-loading solutions."""

from __future__ import annotations

from typing import Any, Mapping

from matplotlib import colormaps
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.patches import Patch
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from gui.models import box_type_by_id


def _cuboid_faces(
    x: float,
    y: float,
    z: float,
    length: float,
    width: float,
    height: float,
) -> list[list[tuple[float, float, float]]]:
    vertices = [
        (x, y, z),
        (x + length, y, z),
        (x + length, y + width, z),
        (x, y + width, z),
        (x, y, z + height),
        (x + length, y, z + height),
        (x + length, y + width, z + height),
        (x, y + width, z + height),
    ]
    return [
        [vertices[index] for index in (0, 1, 2, 3)],
        [vertices[index] for index in (4, 5, 6, 7)],
        [vertices[index] for index in (0, 1, 5, 4)],
        [vertices[index] for index in (1, 2, 6, 5)],
        [vertices[index] for index in (2, 3, 7, 6)],
        [vertices[index] for index in (3, 0, 4, 7)],
    ]


class PackingCanvas(FigureCanvasQTAgg):
    def __init__(self) -> None:
        self.figure = Figure(figsize=(7, 6), constrained_layout=True)
        super().__init__(self.figure)
        self.axes = self.figure.add_subplot(111, projection="3d")
        self.clear_message("Run a solver to display a packing.")

    def clear_message(self, message: str) -> None:
        self.axes.clear()
        self.axes.text2D(0.5, 0.5, message, transform=self.axes.transAxes, ha="center")
        self.axes.set_axis_off()
        self.draw_idle()

    def plot_solution(
        self,
        instance_data: Mapping[str, Any],
        solution: Mapping[str, Any],
        *,
        title: str,
    ) -> None:
        self.axes.clear()
        self.axes.set_axis_on()
        container = instance_data["container"]
        length = container["length"]
        width = container["width"]
        height = container["height"]
        type_by_box = box_type_by_id(instance_data)
        type_ids = [box_type["type_id"] for box_type in instance_data["box_types"]]
        color_map = colormaps["tab20"]
        colors = {
            type_id: color_map(index % color_map.N)
            for index, type_id in enumerate(type_ids)
        }

        boundary = Poly3DCollection(
            _cuboid_faces(0, 0, 0, length, width, height),
            facecolors=(0, 0, 0, 0),
            edgecolors="black",
            linewidths=1.0,
        )
        self.axes.add_collection3d(boundary)

        used_types: set[str] = set()
        for placement in solution["placements"]:
            position = placement["position"]
            dimensions = placement["dimensions"]
            type_id = type_by_box[placement["box_id"]]
            used_types.add(type_id)
            cuboid = Poly3DCollection(
                _cuboid_faces(
                    position["x"],
                    position["y"],
                    position["z"],
                    dimensions["length"],
                    dimensions["width"],
                    dimensions["height"],
                ),
                facecolors=colors[type_id],
                edgecolors="black",
                linewidths=0.65,
                alpha=0.62,
            )
            self.axes.add_collection3d(cuboid)

        self.axes.set_xlim(0, length)
        self.axes.set_ylim(0, width)
        self.axes.set_zlim(0, height)
        self.axes.set_xlabel("Length (x)")
        self.axes.set_ylabel("Width (y)")
        self.axes.set_zlabel("Height (z)")
        self.axes.set_title(title)
        try:
            self.axes.set_box_aspect((length, width, height))
        except AttributeError:
            pass
        if used_types:
            handles = [
                Patch(facecolor=colors[type_id], edgecolor="black", label=type_id, alpha=0.62)
                for type_id in type_ids
                if type_id in used_types
            ]
            self.axes.legend(handles=handles, loc="upper left", title="Box type")
        self.draw_idle()
