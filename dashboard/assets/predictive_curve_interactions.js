/**
 * Curva Acumulada de Riesgo - resaltado por hover.
 *
 * Al pasar el mouse sobre una curva del grafico (Plotly) o sobre uno de los
 * chips de color del selector de unidades, la curva correspondiente se
 * resalta (opacidad 1) y el resto de las curvas de unidad se atenuan. Las
 * zonas de fondo y las lineas de referencia (media/umbral) nunca se tocan.
 *
 * Se implementa fuera del ciclo de callbacks de Dash (sin round-trip al
 * servidor) via los eventos nativos de Plotly.js (plotly_hover/unhover) y
 * delegacion de eventos DOM para los chips, que sobreviven a que Dash
 * vuelva a renderizar el contenedor de chips en cada interaccion.
 */

(function () {
    var GRAPH_ID = "predictive-curve-graph";
    var DIMMED_OPACITY = 0.1;

    function isUnitGroup(legendgroup) {
        return !!legendgroup && legendgroup !== "zonas" && legendgroup !== "referencia";
    }

    function baseOpacityOf(trace) {
        if (trace.meta && typeof trace.meta.baseOpacity === "number") {
            return trace.meta.baseOpacity;
        }
        return trace.opacity === undefined ? 1 : trace.opacity;
    }

    function restyleForGroup(gd, hoveredGroup) {
        if (!gd || !gd.data || !window.Plotly) return;
        var opacities = gd.data.map(function (trace) {
            if (!isUnitGroup(trace.legendgroup)) {
                return baseOpacityOf(trace);
            }
            if (hoveredGroup === null) {
                return baseOpacityOf(trace);
            }
            return trace.legendgroup === hoveredGroup ? 1 : DIMMED_OPACITY;
        });
        window.Plotly.restyle(gd, { opacity: opacities });
    }

    function getGraphDiv() {
        return document.getElementById(GRAPH_ID);
    }

    function attachPlotlyHoverHandlers(gd) {
        if (!gd || gd._predictiveCurveHoverAttached || !gd.on) return;
        gd._predictiveCurveHoverAttached = true;

        gd.on("plotly_hover", function (evt) {
            if (!evt || !evt.points || !evt.points.length) return;
            var trace = gd.data[evt.points[0].curveNumber];
            var group = trace && isUnitGroup(trace.legendgroup) ? trace.legendgroup : null;
            restyleForGroup(gd, group);
        });

        gd.on("plotly_unhover", function () {
            restyleForGroup(gd, null);
        });
    }

    // El div del grafico se crea/recrea de forma asincrona (Plotly.newPlot
    // corre despues del render de React de Dash); se sondea en vez de
    // depender de un unico evento de montaje.
    setInterval(function () {
        var gd = getGraphDiv();
        if (gd) attachPlotlyHoverHandlers(gd);
    }, 500);

    // Hover sobre los chips de color del selector de unidades - delegado en
    // `document` para no perder el listener cuando Dash vuelve a renderizar
    // el contenedor de chips tras cada interaccion.
    document.addEventListener("mouseover", function (evt) {
        var chip = evt.target.closest && evt.target.closest(".predictive-curve-chip");
        if (!chip) return;
        var unit = chip.getAttribute("data-unit");
        if (unit) restyleForGroup(getGraphDiv(), unit);
    });

    document.addEventListener("mouseout", function (evt) {
        var chip = evt.target.closest && evt.target.closest(".predictive-curve-chip");
        if (!chip) return;
        restyleForGroup(getGraphDiv(), null);
    });
})();
