/* Registro de Usuarios: keep date labels on the x-axis of the daily charts from overlapping.
   The figures ship every label plus the interval used at desktop width (layout.meta.urTicks).
   Here the interval grows with the narrowness of the plot, so labels never touch; at desktop width
   nothing changes. When the interval had to grow, the last day stays labelled. Data, bucketing and
   tooltips are untouched. */
(function () {
    var CHAR_PX = 7, PAD_PX = 16;

    function sameArray(a, b) {
        return Array.isArray(a) && a.length === b.length && a.every(function (v, i) { return v === b[i]; });
    }

    function thin(gd) {
        try {
            var cfg = gd && gd.layout && gd.layout.meta && gd.layout.meta.urTicks;
            if (!cfg || !gd._fullLayout || !gd._fullLayout._size) { return; }
            var n = cfg.vals.length, width = gd._fullLayout._size.w;
            if (!n || !(width > 0)) { return; }
            var longest = cfg.text.reduce(function (m, s) { return Math.max(m, String(s).length); }, 0);
            var slot = longest * CHAR_PX + PAD_PX;
            var step = Math.max(cfg.step, Math.ceil(slot * n / width));
            var idx = [];
            for (var i = 0; i < n; i += step) { idx.push(i); }
            if (step > cfg.step && idx[idx.length - 1] !== n - 1) {
                var gapPx = (n - 1 - idx[idx.length - 1]) * width / n;
                if (gapPx >= slot) { idx.push(n - 1); } else { idx[idx.length - 1] = n - 1; }
            }
            var vals = idx.map(function (k) { return cfg.vals[k]; });
            var text = idx.map(function (k) { return cfg.text[k]; });
            if (sameArray(gd.layout.xaxis.tickvals, vals)) { return; }
            window.Plotly.relayout(gd, { "xaxis.tickvals": vals, "xaxis.ticktext": text });
        } catch (e) { /* cosmetic only */ }
    }

    function hook(gd) {
        if (gd.__urAxisHooked || !gd.on) { return; }
        gd.__urAxisHooked = true;
        gd.on("plotly_afterplot", function () { thin(gd); });
        thin(gd);
    }

    function scan() {
        document.querySelectorAll(".js-plotly-plot").forEach(hook);
    }

    new MutationObserver(scan).observe(document.documentElement, { childList: true, subtree: true });
    var timer = null;
    window.addEventListener("resize", function () {
        clearTimeout(timer);
        timer = setTimeout(function () {
            document.querySelectorAll(".js-plotly-plot").forEach(thin);
        }, 150);
    });
    scan();
})();
