"""Zoomable native record graph; layout never invents scientific components."""

from collections import defaultdict
from functools import partial

from PySide6.QtCore import Qt, QPointF, Signal, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene
from rime_core.record_inspection import node_title, format_result
from .components import button


def layered_positions(nodes, edges):
    """Deterministic DAG ranks with barycentric ordering; no external layout runtime."""
    children, parents = defaultdict(set), defaultdict(set)
    for edge in edges:
        children[edge["source"]].add(edge["target"])
        parents[edge["target"]].add(edge["source"])
    degree = {key: len(parents[key]) for key in nodes}
    ready = sorted(key for key in nodes if not degree[key])
    ranks = dict.fromkeys(nodes, 0)
    visited = []
    while ready:
        key = ready.pop(0)
        visited.append(key)
        for target in sorted(children[key]):
            ranks[target] = max(ranks[target], ranks[key] + 1)
            degree[target] -= 1
            if not degree[target]:
                ready.append(target)
    if len(visited) != len(nodes):
        raise ValueError("Cannot lay out a cyclic record graph.")
    layers = defaultdict(list)
    for key in nodes:
        layers[ranks[key]].append(key)

    def initial(key):
        n = nodes[key]
        raw = next(iter(n["originals"].values()))
        order = {"ObservationPeriod": 0, "AnnotationSet": 1, "CalculationDefinition": 2}
        kind = next((t[5:] for t in raw["@type"] if t.startswith("rime:")), "Agent")
        return order.get(kind, 1), n["sides"], node_title(raw), key

    for layer in layers.values():
        layer.sort(key=initial)
    for _ in range(3):
        positions = {k: i for layer in layers.values() for i, k in enumerate(layer)}
        for rank in sorted(layers):
            layers[rank].sort(
                key=lambda k: (
                    sum(positions[p] for p in parents[k]) / len(parents[k])
                    if parents[k]
                    else positions[k],
                    initial(k),
                )
            )
            positions.update({k: i for i, k in enumerate(layers[rank])})
    return {
        key: ((i - (len(layer) - 1) / 2) * 240, rank * 110)
        for rank, layer in layers.items()
        for i, key in enumerate(layer)
    }


class RecordGraph(QGraphicsView):
    node_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMinimumSize(280, 220)
        self.nodes, self.branch_buttons = {}, {}
        self.collapsed = set()
        self.selected = None
        self.model = None

    def set_model(self, model):
        self.model = model
        self.selected = next(iter(model["roots"].values()))
        self.collapsed.clear()
        self.draw()
        QTimer.singleShot(0, self.fit)

    def draw(self):
        self.scene().clear()
        self.nodes, self.branch_buttons = {}, {}
        if self.model is None:
            return
        all_nodes = {n["id"]: n for n in self.model["nodes"]}
        outgoing = defaultdict(list)
        for edge in self.model["edges"]:
            if not edge.get("display_omitted"):
                outgoing[edge["source"]].append(edge)
        # Traverse each record separately: merged display nodes never switch A/B lineage.
        reached, visible_edges = set(), set()
        for side, root in self.model["roots"].items():
            pending, seen = [root], set()
            while pending:
                key = pending.pop()
                if key in seen:
                    continue
                seen.add(key)
                reached.add(key)
                if key not in self.collapsed:
                    for edge in outgoing[key]:
                        if side in edge["sides"]:
                            visible_edges.add(id(edge))
                            pending.append(edge["target"])
        nodes = {key: all_nodes[key] for key in reached}
        edges = [e for e in self.model["edges"] if id(e) in visible_edges]
        positions = layered_positions(nodes, edges)
        width, height = 210, 66
        for key, n in nodes.items():
            raw = next(iter(n["originals"].values()))
            title = node_title(raw)
            if "rime:MeasurementResult" in raw["@type"]:
                title += "\n" + format_result(raw["rime:data"])
            if self.model["comparison"] and len(n["sides"]) == 1:
                title += "\n" + n["sides"][0].upper()
            widget = button(title, partial(self.choose, key), name="record_node_" + key)
            widget.setFixedSize(width, height)
            widget.setCheckable(True)
            widget.setChecked(key == self.selected)
            widget.setAccessibleName(title.replace("\n", ", "))
            color, fill = "#666666", "#ffffff"
            if self.model["comparison"]:
                if n["status"] in ("equal", "shared"):
                    color, fill = "#276541", "#e5f1e8"
                elif n["status"] == "unavailable":
                    color, fill = "#666666", "#eeeeee"
                else:
                    color, fill = "#a8352c", "#fae8e5"
            radius = (
                25 if "prov:Agent" in raw["@type"] else 10 if "prov:Activity" in raw["@type"] else 0
            )
            widget.setStyleSheet(
                f"QPushButton {{ border: 1.5px solid {color}; background: {fill}; color: #111; border-radius: {radius}px; }} QPushButton:checked {{ border: 3px solid #222; }}"
            )
            proxy = self.scene().addWidget(widget)
            x, y = positions[key]
            proxy.setPos(x, y)
            proxy.setZValue(1)
            self.nodes[key] = widget
            if outgoing[key]:
                action = "Expand" if key in self.collapsed else "Collapse"
                toggle = button("+" if key in self.collapsed else "−", name="branch_" + key)
                toggle.setFixedSize(24, 24)
                toggle.setToolTip(action + " branch")
                toggle.setAccessibleName(action + " " + title.replace("\n", " "))
                toggle.clicked.connect(
                    lambda checked=False, key=key: QTimer.singleShot(
                        0, partial(self.toggle_branch, key)
                    )
                )
                control = self.scene().addWidget(toggle)
                control.setPos(x + width - 12, y + height - 12)
                control.setZValue(2)
                self.branch_buttons[key] = toggle
        for edge in edges:
            ax, ay = positions[edge["source"]]
            bx, by = positions[edge["target"]]
            start, end = QPointF(ax + width / 2, ay + height), QPointF(bx + width / 2, by)
            color = (
                "#555555"
                if not self.model["comparison"]
                else "#276541"
                if len(edge["sides"]) == 2
                else "#a8352c"
            )
            pen = QPen(QColor(color), 1.5)
            line = self.scene().addLine(start.x(), start.y(), end.x(), end.y() - 5, pen)
            line.setToolTip(
                edge["relation"].removeprefix("prov:")
                + (" · " + edge["role"].removeprefix("rime:") if edge["role"] else "")
            )
            vector = end - start
            unit = vector / (vector.x() ** 2 + vector.y() ** 2) ** 0.5
            back, perp = end - unit * 9, QPointF(-unit.y(), unit.x()) * 4
            self.scene().addPolygon(QPolygonF([end, back + perp, back - perp]), pen, QColor(color))
        self.setSceneRect(self.scene().itemsBoundingRect().adjusted(-25, -25, 25, 25))

    def choose(self, key):
        self.selected = key
        for name, node in self.nodes.items():
            node.setChecked(name == key)
        self.node_selected.emit(key)

    def toggle_branch(self, key):
        self.choose(key)
        self.collapsed.symmetric_difference_update({key})
        self.draw()
        self.fit()

    def expand_all(self):
        self.collapsed.clear()
        self.draw()
        self.fit()

    def fit(self):
        if self.scene().items():
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def zoom(self, factor):
        if 0.03 <= self.transform().m11() * factor <= 3:
            self.scale(factor, factor)

    def wheelEvent(self, event):
        self.zoom(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
        event.accept()
