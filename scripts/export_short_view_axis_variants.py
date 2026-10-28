"""
Exploratory export: the Predictivo > General > Short View Analysis scatter
("Posición en la flota") with alternative axis pairings, as standalone HTML files.

Not a dashboard feature: nothing here is wired into the app. Each variant reuses the
dashboard's own loader (`load_status_frame`), quadrant thresholds
(`Settings.get_fleet_scatter_threshold`) and figure builder (`create_fleet_scatter`),
passing its own `axes`; the dashboard's configured axes (`Settings.fleet_scatter_axes`)
are not read here.

    python scripts/export_short_view_axis_variants.py [--out outputs]
"""
import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import get_settings  # noqa: E402
from dashboard.components.predictive_charts import create_fleet_scatter  # noqa: E402
from dashboard.components.predictive_state import STATE_COLORS, normalize_state  # noqa: E402
from dashboard.tabs import tab_predictive_overview as ov  # noqa: E402
from src.i18n import t  # noqa: E402

# Column of the per-unit frame (see `_load_component_data_cached`) and its axis label.
# 7d / 30d / today are the columns the live chart reads; 60d / 90d are the loader's
# existing rolling means (`avg_ranking_60d`, `ranking_acum_90d`).
FIELDS = {
    "ranking_today": ("ranking", "Ranking hoy"),
    "ranking_7d": ("avg_ranking_7d", t("predictive_charts.ranking_7_dias")),
    "ranking_30d": ("avg_ranking_30d", t("predictive_charts.ranking_30_dias")),
    "ranking_60d": ("avg_ranking_60d", "Ranking 60 días"),
    "ranking_90d": ("ranking_acum_90d", "Ranking 90 días"),
}

VARIANTS = [
    ("short_view_7d_vs_30d.html", "ranking_7d", "ranking_30d"),
    ("short_view_7d_vs_60d.html", "ranking_7d", "ranking_60d"),
    ("short_view_7d_vs_90d.html", "ranking_7d", "ranking_90d"),
    ("short_view_today_vs_30d.html", "ranking_today", "ranking_30d"),
]

CLIENTS = ("cda", "capstone")

PAGE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500&display=swap" rel="stylesheet">
<style>
  body {{ margin: 0; padding: 24px 16px; background: #f4f5f7; font-family: "DM Sans", sans-serif; color: #1f2937; }}
  .card {{ max-width: 1100px; margin: 0 auto 24px; background: #fff; border-radius: 8px;
           box-shadow: 0 1px 3px rgba(0,0,0,.12); padding: 16px; }}
  .title {{ font-weight: 500; font-size: 14px; }}
  .subtitle {{ font-size: 11px; color: #6c7280; margin-left: 8px; }}
  .chart {{ width: 100%; aspect-ratio: 5 / 2; margin-top: 8px; }}
  .note {{ font-size: 11px; color: #6c7280; margin-top: 4px; }}
</style>
</head>
<body>
{cards}
</body>
</html>
"""

CARD = """<div class="card">
  <div><span class="title">{title}</span><span class="subtitle">{subtitle}</span></div>
  <div class="chart">{chart}</div>
  <div class="note">{note}</div>
</div>"""


def build_figure(latest, client, component, x_key, y_key):
    """(figure, plotted units, units dropped for a missing value) of one pairing."""
    x_col, y_col = FIELDS[x_key][0], FIELDS[y_key][0]
    ok = (
        latest["status"].map(normalize_state).notna()  # units the live chart can draw
        & np.isfinite(latest[x_col].astype(float)) & np.isfinite(latest[y_col].astype(float))
    )
    frame = latest[ok].sort_values("Unit")
    fig = create_fleet_scatter(
        frame, None, STATE_COLORS, axes=(x_key, y_key),
        thresholds=get_settings().get_fleet_scatter_threshold(client, component),
        meter_by_unit=ov.load_latest_component_meter(client, component, frame["Unit"]), height=None,
    )
    return fig, len(frame), int((~ok).sum())


def main(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    frames = []  # (client, component, latest)
    for client in CLIENTS:
        for component in ov._discover_components(client):
            latest = ov.load_status_frame(client, component)
            if latest is None:
                print(f"skip {client}/{component}: no data")
                continue
            missing = [FIELDS[k][0] for k in FIELDS if FIELDS[k][0] not in latest.columns]
            if missing:
                raise SystemExit(f"{client}/{component}: ranking fields missing from the data: {missing}")
            frames.append((client, component, latest))

    for filename, x_key, y_key in VARIANTS:
        cards = []
        for i, (client, component, latest) in enumerate(frames):
            fig, n, dropped = build_figure(latest, client, component, x_key, y_key)
            print(f"{filename}: {client}/{component} - {n} units plotted, {dropped} dropped (missing value)")
            thr = get_settings().get_fleet_scatter_threshold(client, component)
            chart = fig.to_html(
                full_html=False, include_plotlyjs=True if i == 0 else False,
                default_width="100%", default_height="100%",
                config={"displayModeBar": False, "responsive": True},
            )
            cards.append(CARD.format(
                title=f"{t('tab_predictive_overview.posicion_en_la_flota')} · {client.upper()} {component}",
                subtitle=f"{FIELDS[x_key][1]} vs {FIELDS[y_key][1].lower()}"
                         + (f" · umbrales x={thr[0]:g}, y={thr[1]:g}" if thr else " · sin umbrales"),
                chart=chart,
                note=t("tab_predictive_overview.short_view_color_note"),
            ))
        title = f"{t('tab_predictive_overview.posicion_en_la_flota')} - {FIELDS[x_key][1]} vs {FIELDS[y_key][1]}"
        (out_dir / filename).write_text(PAGE.format(title=title, cards="\n".join(cards)), encoding="utf-8")
        print(f"wrote {out_dir / filename}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--out", default=str(ROOT / "outputs"), help="output folder (default: outputs/)")
    main(Path(ap.parse_args().out))
