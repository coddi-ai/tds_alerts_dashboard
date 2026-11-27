/* Label the original fleet points inside the scatterplot, including dense clusters. */
(() => {
    "use strict";

    const svgNS = "http://www.w3.org/2000/svg";
    const measure = document.createElement("canvas").getContext("2d");
    const rowHeight = 16;
    let active;

    function svgNode(tag, attributes, text) {
        const node = document.createElementNS(svgNS, tag);
        Object.entries(attributes).forEach(([name, value]) => node.setAttribute(name, value));
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function clamp(value, low, high) {
        return Math.max(low, Math.min(high, value));
    }

    function labelSlots(points, width, height, zoneBoxes) {
        measure.font = "700 11px Arial, sans-serif";
        const cellWidth = Math.ceil(Math.max(...points.map(point => measure.measureText(point.unit).width))) + 12;
        const cols = Math.max(1, Math.floor((width - 4) / cellWidth));
        const rows = Math.max(1, Math.floor((height - 4) / rowHeight));
        const stride = (width - 4) / cols;
        const rowStride = (height - 4) / rows;
        const slots = [];
        for (let row = 0; row < rows; row++) {
            for (let col = 0; col < cols; col++) {
                slots.push({left: 2 + col * stride, right: 2 + (col + 1) * stride, y: 2 + (row + .5) * rowStride});
            }
        }
        return points.map(point => {
            const half = Math.min(stride / 2 - 2, Math.ceil(measure.measureText(point.unit).width) / 2 + 3);
            let bestIndex = -1;
            let bestCost = Infinity;
            let best;
            slots.forEach((slot, index) => {
                if (slot.used) return;
                const minX = slot.left + half + 1;
                const maxX = slot.right - half - 1;
                const right = clamp(point.px + half + 7, minX, maxX);
                const left = clamp(point.px - half - 7, minX, maxX);
                const options = [right, left, (slot.left + slot.right) / 2];
                for (const x of options) {
                    const occluded = points.some(other =>
                        Math.abs(other.px - x) < half + 5 && Math.abs(other.py - slot.y) < 10);
                    const coversZone = zoneBoxes.some(zone =>
                        Math.abs(zone.x - x) < half + zone.half + 2 && Math.abs(zone.y - slot.y) < 16);
                    const dx = Math.max(0, Math.abs(x - point.px) - half);
                    const dy = slot.y - point.py;
                    const cost = (coversZone ? 10000000 : 0) + (occluded ? 50000 : 0) + dx * dx + dy * dy;
                    if (cost < bestCost) {
                        bestCost = cost;
                        bestIndex = index;
                        best = {x, y: slot.y, half};
                    }
                }
            });
            if (bestIndex < 0) return null;
            slots[bestIndex].used = true;
            return {...point, ...best};
        });
    }

    function draw(state) {
        const {graph, host, overlay} = state;
        const meta = graph.layout?.meta;
        const plot = graph.querySelector(".draglayer .xy .nsewdrag");
        if (!plot || !meta?.fleetLabels?.length || !meta.xLimit || !meta.yLimit) return;
        const bounds = plot.getBoundingClientRect();
        if (bounds.width < 45 || bounds.height < 30) return;
        const panel = host.getBoundingClientRect();
        const left = bounds.left - panel.left;
        const top = bounds.top - panel.top;
        const toggle = host.parentElement.querySelector(".emin-beta-label-toggle input");
        const showAll = !meta.priorityLabelsOnly || Boolean(toggle?.checked);
        const geometry = [bounds.width, bounds.height, left, top, showAll];
        if (meta === state.meta && geometry.every((value, index) => value === state.geometry?.[index])) return;
        state.meta = meta;
        state.geometry = geometry;
        Object.assign(overlay.style, {left: left + "px", top: top + "px",
                                      width: bounds.width + "px", height: bounds.height + "px"});
        overlay.setAttribute("viewBox", `0 0 ${bounds.width} ${bounds.height}`);
        overlay.setAttribute("aria-label", meta.labelTitle);
        const positions = meta.fleetLabels.filter(point => showAll || point.priority).map(point => ({...point,
            px: point.x / meta.xLimit * bounds.width,
            py: (1 - point.y / meta.yLimit) * bounds.height,
        }));
        const guides = svgNode("g", {"aria-hidden": "true"});
        const labels = svgNode("g", {});
        const zones = svgNode("g", {});
        measure.font = "700 11px Arial, sans-serif";
        const zoneBoxes = (meta.zones || []).map(zone => {
            const zoneWidth = (zone.x1 - zone.x0) / meta.xLimit * bounds.width;
            const full = zone.index + " · " + zone.label;
            const title = meta.priorityLabelsOnly ? zone.label
                : measure.measureText(full).width + 10 < zoneWidth ? full : String(zone.index);
            return {...zone, title, half: (measure.measureText(title).width + 4) / 2,
                x: (zone.x0 + zone.x1) / (2 * meta.xLimit) * bounds.width,
                y: (1 - (zone.y0 + zone.y1) / (2 * meta.yLimit)) * bounds.height};
        });
        for (const zone of zoneBoxes) {
            zones.append(svgNode("text", {x: zone.x, y: zone.y, fill: zone.color, "font-weight": 700,
                "text-anchor": "middle", "dominant-baseline": "central", class: "emin-beta-zone-name"}, zone.title));
        }
        for (const label of labelSlots(positions, bounds.width, bounds.height, zoneBoxes)) {
            if (!label) continue;
            const x2 = clamp(label.px, label.x - label.half, label.x + label.half);
            const y2 = clamp(label.py, label.y - 7, label.y + 7);
            if (Math.hypot(x2 - label.px, y2 - label.py) > 5) {
                guides.append(svgNode("line", {x1: label.px, y1: label.py, x2, y2,
                    stroke: label.color, "stroke-width": .8, opacity: label.priority ? .7 : .52}));
            }
            labels.append(
                svgNode("rect", {x: label.x - label.half, y: label.y - 7, width: label.half * 2, height: 14,
                    rx: 2, fill: "white", opacity: .9, "aria-hidden": "true"}),
                svgNode("text", {x: label.x, y: label.y, "text-anchor": "middle", "dominant-baseline": "central",
                    fill: label.color, "font-weight": label.priority ? 700 : 400, class: "emin-beta-unit-name"}, label.unit)
            );
        }
        overlay.replaceChildren(zones, guides, labels);
    }

    function schedule(state) {
        if (state.frame) return;
        state.frame = requestAnimationFrame(() => {
            state.frame = 0;
            if (active === state) draw(state);
        });
    }

    function connect() {
        const host = document.querySelector(".emin-beta-fleet-plot");
        const graph = host?.querySelector(".js-plotly-plot");
        if (graph && active?.graph === graph) {
            if (!active.hasListener && typeof graph.on === "function") {
                graph.on("plotly_afterplot", active.afterPlot);
                graph.on("plotly_click", active.onClick);
                active.hasListener = true;
                schedule(active);
            }
            return;
        }
        if (active) {
            active.resize.disconnect();
            active.graph.removeListener?.("plotly_afterplot", active.afterPlot);
            active.graph.removeListener?.("plotly_click", active.onClick);
            active.overlay.remove();
            active = null;
        }
        if (!graph) return;
        const overlay = svgNode("svg", {class: "emin-beta-scatter-labels", role: "group"});
        host.append(overlay);
        const state = {graph, host, overlay};
        active = state;
        state.afterPlot = () => schedule(state);
        state.onClick = (event) => {
            const unit = event?.points?.[0]?.customdata?.[0];
            if (!unit) return;
            const page = host.closest(".emin-beta-page");
            const row = page?.querySelector(`[data-emin-fleet-unit="${CSS.escape(unit)}"]`);
            const status = page?.querySelector(".emin-beta-plot-status");
            if (status) status.textContent = row ? "" : `${unit} · ${status.dataset.missingText}`;
            if (!row) return;
            page.querySelector(".emin-beta-fleet-selected")?.classList.remove("emin-beta-fleet-selected");
            row.classList.add("emin-beta-fleet-selected");
            row.querySelector("a")?.focus({preventScroll: true});
            row.scrollIntoView({block: "center", inline: "nearest"});
        };
        state.resize = new ResizeObserver(state.afterPlot);
        state.resize.observe(graph);
        if (typeof graph.on === "function") {
            graph.on("plotly_afterplot", state.afterPlot);
            graph.on("plotly_click", state.onClick);
            state.hasListener = true;
        }
        schedule(state);
    }

    document.addEventListener("change", event => {
        if (active && event.target.matches(".emin-beta-label-toggle input")) schedule(active);
    });
    new MutationObserver(connect).observe(document.documentElement, {subtree: true, childList: true});
    connect();
})();
