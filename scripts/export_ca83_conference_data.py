"""Export the CA-83 (engine) data pack for the Minexcellence 2026 talk.

Reads the local data mirror (read-only) and writes CSV/Markdown files to
documentation/conference/new_request/. Re-runnable. Privacy: no client name and no
person names are written to the output files; unit IDs are kept.

    python scripts/export_ca83_conference_data.py
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from datetime import date, datetime

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.environ.get("DASHBOARD_DATA_ROOT", os.path.join(ROOT, "data"))
OUT = os.path.join(ROOT, "documentation", "conference", "new_request")
CLIENT = "capstone"           # used only to build input paths; never written to outputs
UNIT = "CA-83"
START = pd.Timestamp("2026-08-05")
END = pd.Timestamp("2026-11-02")
TZ = "America/Santiago"
EXPORTED = date.today().isoformat()

os.makedirs(OUT, exist_ok=True)
PRED = os.path.join(DATA, "predictive", "golden", CLIENT, "motor")
TELE = os.path.join(DATA, "telemetry", "golden", CLIENT)

MODE_EN = {
    "lubrication_failure_risk": "Lubrication Failure",
    "turbocharger_risk": "Turbocharger Failure",
    "thermal_imbalance_risk": "Thermal Imbalance Between Banks",
    "combustion_risk": "Combustion / Injectors",
    "abrasive_wear_risk": "Abrasive Wear",
    "bearing_wear_risk": "Bearing Wear",
    "coolant_contamination_risk": "Coolant Contamination",
    "blowby_risk": "Blow-by / Ring Wear",
    "oil_degradation_risk": "Oil Degradation",
    "accumulated_wear_risk": "Accumulated Wear",
}
STATE_EN = {"Saludable": "Healthy", "Monitoreo": "Monitoring", "Prioridad alta": "High priority", "Critico": "Critical"}

SIGNALS = {  # signal_id: (English name, unit)
    "imp_lb_psi": ("Left bank intake pressure", "psi"),
    "imp_rb_psi": ("Right bank intake pressure", "psi"),
    "egt_03_c": ("Cylinder 03 exhaust temperature", "degC"),
    "egt_lb_c": ("Left bank exhaust temperature", "degC"),
    "egt_rb_c": ("Right bank exhaust temperature", "degC"),
    "DeltaExh": ("Exhaust temperature difference (right-left)", "degC"),
    "imt_lbf_c": ("Left bank front intake temperature", "degC"),
    "imt_rbf_c": ("Right bank front intake temperature", "degC"),
    "rifle_oil_pressure_psi": ("Rifle oil pressure", "psi"),
    "oil_diff_pressure_psi": ("Engine oil differential pressure", "psi"),
    "oil_temp_c": ("Oil temperature", "degC"),
    "turbo_speed_rpm": ("Turbo speed", "rpm"),
}
# catalogue of the platform (dashboard/components/predictive_config.py, client "motor")
MODE_SIGNALS = {
    "thermal_imbalance_risk": ["DeltaExh", "egt_lb_c", "egt_rb_c", "imp_lb_psi", "imp_rb_psi", "imt_lbf_c", "imt_rbf_c"],
    "lubrication_failure_risk": ["Hierro", "Plomo", "Cobre", "rifle_oil_pressure_psi", "oil_diff_pressure_psi", "oil_temp_c"],
    "turbocharger_risk": ["Aluminio", "Hierro", "Cromo", "turbo_speed_rpm", "imp_lb_psi", "imp_rb_psi", "imt_lbf_c",
                          "imt_rbf_c", "egt_lb_c", "egt_rb_c"],
    "combustion_risk": ["Hollín", "Combustible", "egt_avg_c", "fuel_pump_intake_pressure_psi"],
}
OIL_EN = {"Hierro": ("Iron", "ppm"), "Plomo": ("Lead", "ppm"), "Cobre": ("Copper", "ppm"), "Aluminio": ("Aluminum", "ppm"),
          "Cromo": ("Chromium", "ppm"), "Hollín": ("Soot", "%"), "Combustible": ("Fuel dilution", "%"),
          "Silicio": ("Silicon", "ppm"), "Sodio": ("Sodium", "ppm"), "Potasio": ("Potassium", "ppm"),
          "Estaño": ("Tin", "ppm"), "Níquel": ("Nickel", "ppm"), "Plata": ("Silver", "ppm"),
          "Titanio": ("Titanium", "ppm"), "Vanadio": ("Vanadium", "ppm"), "Manganeso": ("Manganese", "ppm"),
          "Agua": ("Water", "%"), "Oxidación": ("Oxidation", "Abs/cm"), "Viscocidad": ("Viscosity", "cSt"),
          "Numero Total Basico": ("Total base number", "mg KOH/g")}
EGT_AVG = ("egt_avg_c", "Average exhaust temperature", "degC")

OUTLOG = []


def log(*a):
    msg = " ".join(str(x) for x in a)
    OUTLOG.append(msg)
    print(msg)


def wk(f):
    return int(re.search(r"year=(\d+)", f).group(1)), int(re.search(r"week=(\d+)", f).group(1))


def read_weeks(table_dir, y_w_min, y_w_max, extra_filter=None):
    fs = [f for f in glob.glob(os.path.join(table_dir, "year=*", "week=*", "*.parquet"))
          if y_w_min <= wk(f) <= y_w_max]
    parts = []
    for f in sorted(fs, key=wk):
        d = pd.read_parquet(f)
        if extra_filter is not None:
            d = extra_filter(d)
        parts.append(d)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def write_csv(df, name):
    p = os.path.join(OUT, name)
    df.to_csv(p, index=False, encoding="utf-8", lineterminator="\n")
    log(f"wrote {name}: {len(df)} rows")


dates = pd.date_range(START, END, freq="D")
assert len(dates) == 90

# ---------------------------------------------------------------- risk scores
rs = read_weeks(os.path.join(PRED, "risk_scores"), (2026, 25), (2026, 46))
rs["Fecha"] = pd.to_datetime(rs["Fecha"])
rs = rs[(rs.Fecha >= START - pd.Timedelta(days=14)) & (rs.Fecha <= END)]
modes_df = rs[rs.failure_mode != "ranking"].copy()
win = modes_df[(modes_df.Fecha >= START) & (modes_df.Fecha <= END)]
fleet_units = sorted(win.Unit.unique())
log("fleet units in window:", len(fleet_units), "| modes:", sorted(win.failure_mode.unique()))
assert len(fleet_units) == 50, len(fleet_units)

# --------------------------------------------------- B1 calendar (state per mode)
edges_path = os.path.join(ROOT, "config", "umbrales_criticidad", f"{CLIENT}.json")
edges = json.load(open(edges_path, encoding="utf-8"))["umbrales_criticidad"]["modos"]
unit = modes_df[modes_df.Unit == UNIT].set_index(["failure_mode", "Fecha"]).sort_index()
rows = []
for m in MODE_EN:
    daily = unit.loc[m] if m in unit.index.get_level_values(0) else pd.DataFrame()
    rv = daily["risk_value"].reindex(pd.date_range(START - pd.Timedelta(days=6), END)) if len(daily) else None
    mean7 = rv.rolling(7, min_periods=1).mean() if rv is not None else None
    e = (edges[m]["p75"], edges[m]["p90"], edges[m]["p98"]) if m in edges else (35.0, 55.0, 75.0)
    for d in dates:
        if len(daily) and d in daily.index:
            r = daily.loc[d]
            state = STATE_EN.get(r["risk_level"], "No data") if pd.notna(r["risk_level"]) else "No data"
            score = r["risk_level_value"]
            dws = r["risk_value"]
            v_old = mean7[d] if m in edges else rv[d]
            old = ["Healthy", "Monitoring", "High priority", "Critical"][sum(v_old >= x for x in e)]
        else:
            state, score, dws, old = "No data", np.nan, np.nan, "No data"
        rows.append((d.date().isoformat(), MODE_EN[m], state, score, dws, old))
cal = pd.DataFrame(rows, columns=["date", "failure_mode", "state", "score", "daily_weighted_score", "state_5nov_logic"])
cal["score"] = cal["score"].round(4)
cal["daily_weighted_score"] = cal["daily_weighted_score"].round(4)
write_csv(cal, "calendar_ca83.csv")
log("calendar: no-data cells", int((cal.state == "No data").sum()), "of", len(cal),
    "| agreement platform-now vs 5-Nov logic (cells with data):",
    round(float((cal[cal.state != "No data"].state == cal[cal.state != "No data"].state_5nov_logic).mean()), 3))
log("state counts (current):", cal.state.value_counts().to_dict())
log("state counts 2 Nov:", cal[cal.date == "2026-11-02"][["failure_mode", "state", "score"]].to_dict("records"))

# --------------------------------------------------------- B2 mode scores + fleet
g = win.groupby(["Fecha", "failure_mode"])
fleet = g.agg(fleet_mean=("risk_level_value", "mean"), fleet_p80=("risk_level_value", lambda s: s.quantile(0.8)),
              fleet_mean_daily=("risk_value", "mean"), fleet_p80_daily=("risk_value", lambda s: s.quantile(0.8)),
              n_units=("Unit", "nunique")).reset_index()
u = win[win.Unit == UNIT][["Fecha", "failure_mode", "risk_level_value", "risk_value"]]
ms = u.merge(fleet, on=["Fecha", "failure_mode"], how="left")
ms["failure_mode"] = ms.failure_mode.map(MODE_EN)
ms["date"] = ms.Fecha.dt.date.astype(str)
ms = ms.rename(columns={"risk_level_value": "score", "risk_value": "daily_weighted_score"})
ms = ms[["date", "failure_mode", "score", "fleet_mean", "fleet_p80", "daily_weighted_score", "fleet_mean_daily",
         "fleet_p80_daily", "n_units"]].sort_values(["failure_mode", "date"]).round(4)
write_csv(ms, "mode_scores_ca83.csv")
log("mode windows on 2 Nov (CA-83):")
lat = modes_df[(modes_df.Unit == UNIT) & (modes_df.Fecha <= END)]
for m in ["lubrication_failure_risk", "thermal_imbalance_risk", "turbocharger_risk", "combustion_risk"]:
    s = lat[lat.failure_mode == m].set_index("Fecha").sort_index()
    log(f"  {m}: day rlv {s.risk_level_value.iloc[-1]:.2f} | day rv {s.risk_value.iloc[-1]:.2f} | "
        f"7d rlv {s.risk_level_value.tail(7).mean():.2f} | 30d rv {s.risk_value.tail(30).mean():.2f} "
        f"rlv {s.risk_level_value.tail(30).mean():.2f} | 90d rv {s.risk_value.tail(90).mean():.2f} "
        f"rlv {s.risk_level_value.tail(90).mean():.2f} | window-mean rlv "
        f"{s[(s.index >= START)].risk_level_value.mean():.2f} | days>=Monitoring "
        f"{int((s[s.index>=START].risk_level.isin(['Monitoreo','Prioridad alta','Critico'])).sum())}")

# ------------------------------------------------------- telemetry: published daily status
sds = read_weeks(os.path.join(TELE, "motor", "signal_daily_status"), (2026, 31), (2026, 46),
                 lambda d: d[d.Unit == UNIT])
sds["Fecha"] = pd.to_datetime(sds["Fecha"])
sds = sds[(sds.Fecha >= START) & (sds.Fecha <= END)]
log("signal_daily_status rows for unit in window:", len(sds), "days:", sds.Fecha.nunique(),
    "| rows where critical > alert:", int((sds.pct_time_critical > sds.pct_time_alert + 1e-9).sum()),
    "| max alert+critical:", round(float((sds.pct_time_alert + sds.pct_time_critical).max()), 1),
    "| rows alert+critical > 100:", int(((sds.pct_time_alert + sds.pct_time_critical) > 100).sum()))
oh = read_weeks(os.path.join(TELE, "motor", "operating_hours"), (2026, 31), (2026, 46), lambda d: d[d.Unit == UNIT])
oh["dia"] = pd.to_datetime(oh["dia"])
oh = oh[(oh.dia >= START) & (oh.dia <= END)]
log("operating_hours: days with data", len(oh), "of 90; total h_op", round(oh.h_op.sum(), 1))

# ------------------------------------------------------- minute telemetry -> daily stats
silver_dir = os.path.join(DATA, "telemetry", "silver", CLIENT, "Telemetry_Wide_With_States")
cols = ["Fecha", "Unit", "EstadoMaquina", "engine_speed_rpm"] + [s for s in SIGNALS if s != "DeltaExh"] + ["egt_avg_c"]
minute = []
for w in range(31, 47):
    f = os.path.join(silver_dir, f"Week{w:02d}Year2026.parquet")
    if os.path.exists(f):
        minute.append(pd.read_parquet(f, columns=cols, filters=[("Unit", "==", UNIT)]))
mn = pd.concat(minute, ignore_index=True)
mn["ts"] = pd.to_datetime(mn.Fecha, utc=True)
mn["day"] = mn.ts.dt.tz_convert(TZ).dt.tz_localize(None).dt.normalize()
mn["DeltaExh"] = mn.egt_rb_c - mn.egt_lb_c
mn_w = mn[(mn.day >= START) & (mn.day <= END)]
pw = mn_w[mn_w.EstadoMaquina == "Potencia"]
log("minute rows (all states) in window:", len(mn_w), "| Potencia minutes:", len(pw),
    "| days with Potencia minutes:", pw.day.nunique())

lim = pd.read_parquet(os.path.join(TELE, "limits", "limits_version=20261101", "limits.parquet"))
sdsi = sds.set_index(["signal_name", "Fecha"])
rows = []
for sig, (name, unit_) in SIGNALS.items():
    L = lim[lim.signal_id == sig]
    hi = L[L.direction == "HIGH"]
    lo = L[L.direction == "LOW"]
    a_hi = float(hi.warn_limit.iloc[0]) if len(hi) else np.nan
    c_hi = float(hi.crit_limit.iloc[0]) if len(hi) else np.nan
    a_lo = float(lo.warn_limit.iloc[0]) if len(lo) else np.nan
    c_lo = float(lo.crit_limit.iloc[0]) if len(lo) else np.nan
    for d in dates:
        x = pw[(pw.day == d)][sig].dropna()
        pub = sdsi.loc[(sig, d)] if (sig, d) in sdsi.index else None
        ohd = oh[oh.dia == d]
        rows.append((d.date().isoformat(), name, unit_,
                     x.mean() if len(x) else np.nan, x.quantile(0.95) if len(x) else np.nan,
                     a_hi, c_hi, a_lo, c_lo,
                     pub.pct_time_alert if pub is not None else np.nan,
                     pub.pct_time_critical if pub is not None else np.nan,
                     float(ohd.h_op.iloc[0]) if len(ohd) else np.nan, len(x)))
fd = pd.DataFrame(rows, columns=["date", "feature", "unit", "daily_mean", "daily_p95", "alert_threshold",
                                 "critical_threshold", "alert_threshold_low", "critical_threshold_low",
                                 "pct_time_alert", "pct_time_critical", "operating_hours", "power_state_minutes"])
fd = fd.round(4)
write_csv(fd, "features_daily_ca83.csv")
log("features with published pct rows:", sorted(sds.signal_name.unique()))
log("days with any Potencia minutes:", int(fd[fd.feature == "Left bank intake pressure"].power_state_minutes.gt(0).sum()))

# ------------------------------------------------------------------- alerts list
adir = os.path.join(DATA, "alerts", "golden", CLIENT)
alert_files = [f for f in glob.glob(os.path.join(adir, "*", "file.parquet")) if os.path.basename(os.path.dirname(f)) >= "2026-07-20"]
al = pd.concat([pd.read_parquet(f) for f in alert_files], ignore_index=True)
al = al[al.UnitId == UNIT].copy()
al["ts"] = pd.to_datetime(al.Timestamp, utc=True)
al["local_day"] = al.ts.dt.tz_convert(TZ).dt.tz_localize(None).dt.normalize()
for lbl, s0 in (("04 Aug start (platform capture)", pd.Timestamp("2026-08-04")), ("05 Aug start (this pack)", START)):
    w_ = al[(al.local_day >= s0) & (al.local_day <= END)]
    log(f"alerts {lbl}: total {len(w_)} | by signal", w_.Trigger_Var.value_counts().to_dict())
alw = al[(al.local_day >= START) & (al.local_day <= END)].copy()
# operating state at alert time: from the alert's telemetry evidence
tidx = pd.read_parquet(os.path.join(adir, "_telemetry_index.parquet"))
state_map = {}
tele_cache = {}
for _, r in alw.iterrows():
    wkdir = r["Timestamp"]
for wdir in sorted({os.path.basename(os.path.dirname(f)) for f in alert_files}):
    pass
tfiles = {os.path.basename(os.path.dirname(f)): f for f in glob.glob(os.path.join(adir, "*", "telemetry.parquet"))}
need_ids = set(alw.FusionID) | set(alw.TelemetryID)
for wdir, f in tfiles.items():
    if wdir < "2026-07-20":
        continue
    t = pd.read_parquet(f, columns=["AlertID", "Unit", "State", "Alert_TimeStart", "TimeStart"],
                        filters=[("Unit", "==", UNIT)])
    t = t[t.AlertID.isin(need_ids)].copy()
    # State of the evidence minute closest to the alert time (the evidence window spans the alert hour).
    t["gap"] = (pd.to_datetime(t.TimeStart, utc=True) - pd.to_datetime(t.Alert_TimeStart, utc=True)).abs()
    for aid, s in t.sort_values("gap").groupby("AlertID"):
        state_map[aid] = s.State.iloc[0]
alw["operating_state"] = alw.FusionID.map(state_map).fillna(alw.TelemetryID.map(state_map))
SIG_EN = {k: v[0] for k, v in SIGNALS.items()}
SIG_EN["egt_14_c"] = "Cylinder 14 exhaust temperature"
out = pd.DataFrame({
    "timestamp": alw.ts.dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "signal": alw.Trigger_Var.map(SIG_EN).fillna(alw.Trigger_Var),
    "system": "engine / " + alw.subsistema.fillna("").astype(str),
    "severity": "",
    "operating_state": alw.operating_state.fillna("").astype(str),
    "diagnosis_text": alw.mensaje_ia_eng.where(alw.mensaje_ia_eng.notna() & (alw.mensaje_ia_eng.astype(str).str.strip() != ""), alw.mensaje_ia),
    "diagnosis_text_es": alw.mensaje_ia,
    "trigger_type": alw.Trigger_type.map({"Telemetria": "telemetry", "Mixto": "mixed"}).fillna(alw.Trigger_type),
}).sort_values("timestamp")
write_csv(out, "alerts_ca83.csv")
log("alerts operating_state:", out.operating_state.value_counts(dropna=False).to_dict())
log("alerts by week:", alw.groupby(alw.local_day.dt.to_period("W-SUN").dt.start_time.dt.date.astype(str)).size().to_dict())
log("alerts hour-of-day (Chile):", alw.ts.dt.tz_convert(TZ).dt.hour.value_counts().sort_index().to_dict())
log("last alert per signal:", alw.groupby("Trigger_Var").ts.max().astype(str).to_dict())
post = al[al.local_day > END]
log("alerts after window:", post[["Timestamp", "Trigger_Var"]].astype(str).values.tolist())
miss_text = int((out.diagnosis_text.isna()).sum())
log("alerts without diagnosis text:", miss_text, "| with English:", int(alw.mensaje_ia_eng.notna().sum()))

# ---------------------------------------------------------------------- oil
oil = pd.read_parquet(os.path.join(DATA, "oil", "golden", CLIENT, "classified.parquet"))
oil = oil[oil.unitId == UNIT].copy()
oil["sampleDate"] = pd.to_datetime(oil.sampleDate)
lim3 = pd.read_parquet(os.path.join(DATA, "oil", "golden", CLIENT, "stewart_limits.parquet")).set_index("essay")
lim4 = pd.read_parquet(os.path.join(DATA, "oil", "golden", CLIENT, "stewart_limits_four.parquet")).set_index("essay")
ow = oil[(oil.sampleDate >= START) & (oil.sampleDate <= END)].sort_values("sampleDate")
rows = []
for _, s in ow.iterrows():
    for ess in lim3.index:
        if ess not in s.index or pd.isna(s[ess]):
            continue
        en, un = OIL_EN.get(ess, (ess, ""))
        n_, a_, c_ = lim3.loc[ess, ["threshold_normal", "threshold_alert", "threshold_critic"]]
        lic, lim_ = lim4.loc[ess, "LIC"], lim4.loc[ess, "LIM"]
        v = float(s[ess])
        st = "Critical" if v > c_ else ("Alert" if v > n_ else "Normal")
        if pd.notna(lic) and v < lic:
            st = "Critical (low)"
        elif pd.notna(lim_) and v < lim_ and st == "Normal":
            st = "Alert (low)"
        rows.append((s.sampleDate.date().isoformat(), en, v, un, n_, a_, c_, lim_, lic, st, s.report_status))
oil_out = pd.DataFrame(rows, columns=["sample_date", "element_or_property", "value", "unit", "normal_limit",
                                      "alert_limit", "critical_limit", "low_alert_limit", "low_critical_limit",
                                      "value_vs_limits", "sample_report_status"])
write_csv(oil_out, "oil_samples_ca83.csv")
log("oil samples in window:", ow.sampleDate.dt.date.astype(str).tolist())
log("oil exceedances:", oil_out[oil_out.value_vs_limits != "Normal"][["sample_date", "element_or_property", "value", "normal_limit", "critical_limit", "value_vs_limits"]].values.tolist())
log("oil sample status:", ow[["sampleDate", "report_status", "anomalyType"]].astype(str).values.tolist())
log("latest sample in dataset:", oil.sampleDate.max().date())

# ---------------------------------------------- B3 feature evidence by mode (no weights upstream)
ow_all = oil.sort_values("sampleDate")
rows = []
wk_ends = [END - pd.Timedelta(days=7 * k) for k in range(0, 12)][::-1]
for end in wk_ends:
    start7 = end - pd.Timedelta(days=6)
    for m, sigs in MODE_SIGNALS.items():
        for sg in sigs:
            if sg in SIGNALS:
                name, un = SIGNALS[sg]
                p = sds[(sds.signal_name == sg) & (sds.Fecha >= start7) & (sds.Fecha <= end)]
                ohw = oh[(oh.dia >= start7) & (oh.dia <= end)].h_op.sum()
                Lh = lim[(lim.signal_id == sg)]
                ref = "; ".join(f"{r.direction.lower()} warn {r.warn_limit:.2f} / crit {r.crit_limit:.2f} ({un})" for r in Lh.itertuples()) or "no fixed limit in limits table"
                rows.append((end.date().isoformat(), MODE_EN[m], name, "telemetry",
                             round(float(p.pct_time_alert.mean()), 3) if len(p) else np.nan,
                             "% of time in alert band (includes critical)",
                             ref, np.nan, np.nan, np.nan,
                             round(float(p.pct_time_critical.mean()), 3) if len(p) else np.nan,
                             len(p), round(float(ohw), 2), ""))
            elif sg == "egt_avg_c":
                p = sds[(sds.signal_name == sg) & (sds.Fecha >= start7) & (sds.Fecha <= end)]
                rows.append((end.date().isoformat(), MODE_EN[m], "Average exhaust temperature", "telemetry",
                             round(float(p.pct_time_alert.mean()), 3) if len(p) else np.nan,
                             "% of time in alert band (includes critical)",
                             "no fixed limit in limits table", np.nan, np.nan, np.nan,
                             round(float(p.pct_time_critical.mean()), 3) if len(p) else np.nan, len(p),
                             round(float(oh[(oh.dia >= start7) & (oh.dia <= end)].h_op.sum()), 2), ""))
            elif sg in OIL_EN:
                en, un = OIL_EN[sg]
                prev = ow_all[ow_all.sampleDate <= end]
                if prev.empty or pd.isna(prev.iloc[-1].get(sg)):
                    continue
                s = prev.iloc[-1]
                n_, a_, c_ = lim3.loc[sg, ["threshold_normal", "threshold_alert", "threshold_critic"]] if sg in lim3.index else (np.nan,) * 3
                rows.append((end.date().isoformat(), MODE_EN[m], en, "oil", float(s[sg]), un,
                             f"normal<={n_}; critical>{c_} ({un})", np.nan, np.nan, np.nan, np.nan, 1, np.nan,
                             s.sampleDate.date().isoformat()))
fe = pd.DataFrame(rows, columns=["date", "failure_mode", "feature", "source", "value", "unit", "reference",
                                 "severity_0_100", "weight", "contribution_to_mode_score",
                                 "pct_time_critical_7d", "n_days_with_data", "operating_hours_7d", "oil_sample_date"])
write_csv(fe, "feature_evidence_by_mode_ca83.csv")

# --------------------------------------------------------------------- AI text
ai_dir = os.path.join(PRED, "unit_failure_analisis")
cands = []
for f in glob.glob(os.path.join(ai_dir, "**", "*.parquet"), recursive=True):
    rel = os.path.relpath(f, ai_dir).replace("\\", "/")
    if rel.startswith("_runs"):
        continue
    d = pd.read_parquet(f)
    d = d[d.Unit == UNIT]
    if d.empty:
        continue
    r = d.iloc[0]
    cands.append((rel, datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M"), r))
cands.sort(key=lambda x: (x[2]["Fecha"], x[1]))
ai_md = []
for rel, mt, r in cands:
    if pd.Timestamp(r["Fecha"]) < pd.Timestamp("2026-10-25"):
        continue
    ai_md.append(dict(file=rel, mirror_mtime=mt, run_date=str(pd.Timestamp(r["Fecha"]).date()), year_week=r.get("year_week"),
                      estado=r["estado"], worst_mode=r["peor_modo"], worst_value=float(r["peor_valor"]),
                      source=r["analisis_fuente"], tokens=str(r["analisis_tokens"]),
                      diagnostico=r["diagnostico"], causa_probable=r["causa_probable"], acciones=r["acciones"]))
json.dump(ai_md, open(os.path.join(os.environ.get("EXPORT_SCRATCH", OUT), "_ai_versions.json") if os.environ.get("EXPORT_SCRATCH") else os.devnull, "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
for a in ai_md:
    log("AI version:", a["file"], a["mirror_mtime"], a["run_date"], a["worst_mode"], a["worst_value"], a["source"])

# ------------------------------------------- post-window context for the outcome file
post_rs = modes_df  # up to END only; reload full for post-window
full = read_weeks(os.path.join(PRED, "risk_scores"), (2026, 45), (2026, 46))
full["Fecha"] = pd.to_datetime(full.Fecha)
pw_ = full[(full.Unit == UNIT) & (full.Fecha > END)]
for m in ["thermal_imbalance_risk", "lubrication_failure_risk"]:
    s = pw_[pw_.failure_mode == m].set_index("Fecha")
    log(f"post-window {m}: days {len(s)}, levels", s.risk_level.value_counts().to_dict(), "| mean rlv", round(s.risk_level_value.mean(), 2))
post_sds = read_weeks(os.path.join(TELE, "motor", "signal_daily_status"), (2026, 45), (2026, 46), lambda d: d[d.Unit == UNIT])
post_sds["Fecha"] = pd.to_datetime(post_sds.Fecha)
ps = post_sds[(post_sds.Fecha > END) & (post_sds.signal_name == "imp_lb_psi")]
log("post-window imp_lb_psi published pct (alert/critical):", ps[["Fecha", "pct_time_alert", "pct_time_critical"]].astype(str).values.tolist())
pre = sds[(sds.signal_name == "imp_lb_psi")]
log("in-window imp_lb_psi mean pct alert/critical:", round(pre.pct_time_alert.mean(), 2), round(pre.pct_time_critical.mean(), 2), "days", len(pre))
poh = read_weeks(os.path.join(TELE, "motor", "operating_hours"), (2026, 45), (2026, 46), lambda d: d[d.Unit == UNIT])
poh["dia"] = pd.to_datetime(poh.dia)
log("post-window operating hours:", poh[poh.dia > END][["dia", "h_op"]].astype(str).values.tolist())

# CA-83 hours operated: window, and fleet comparison
ohf = read_weeks(os.path.join(TELE, "motor", "operating_hours"), (2026, 32), (2026, 45))
ohf["dia"] = pd.to_datetime(ohf.dia)
ohf = ohf[(ohf.dia >= START) & (ohf.dia <= END)]
tot = ohf.groupby("Unit").h_op.sum()
log("operating hours in window: CA-83", round(tot.get(UNIT, 0), 1), "| fleet median", round(tot.median(), 1), "| fleet p10", round(tot.quantile(.1), 1), "| rank", int((tot > tot.get(UNIT, 0)).sum()) + 1, "of", len(tot))

with open(os.path.join(os.environ.get("EXPORT_SCRATCH", OUT), "_export_log.txt") if os.environ.get("EXPORT_SCRATCH") else os.devnull, "w", encoding="utf-8") as fh:
    fh.write("\n".join(OUTLOG))
