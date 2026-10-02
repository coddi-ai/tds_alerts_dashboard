"""
Predictive callbacks - handles internal tab switching and evidence interactivity.
"""

from src.i18n import t
from dashboard.components.labels import status_label
from dash import html, dcc, Input, Output, State, no_update, ALL, ctx
import pandas as pd
from src.utils.logger import get_logger
from config.settings import get_settings
from src.data.loaders import get_latest_component_hours
from dashboard.components.predictive_config import (
    resolve_failure_modes,
    resolve_failure_mode_options,
    load_real_oil_samples,
)
from dashboard.tabs.tab_predictive_overview import (
    _discover_components,
    _load_component_data as _load_overview_component,
    _render_component_overview,
    _failure_table,
    attach_status,
    WINDOW_SUFFIX,
)
from dashboard.tabs.tab_predictive_evidence import (
    _load_component_data as _load_evidence_component,
    render_initial_content,
    render_detailed_evidence,
)

logger = get_logger(__name__)

# _load_real_oil_samples was moved to
# dashboard.components.predictive_config.load_real_oil_samples so
# tab_predictive_evidence.py's oil selector/table (which needs the same real,
# non-forward-filled oil samples for components on the new parquet Data
# Contract v2.0 format) can share it without a circular import.


def register_callbacks(app):
    """Register predictive callbacks."""

    # ══════════════════════════════════════════════════════════════════════════
    # INTERNAL TAB SWITCHING: Resumen / Evidencia
    # ══════════════════════════════════════════════════════════════════════════

    @app.callback(
        Output("predictive-component-tab-content", "children"),
        Input("predictive-component-internal-tabs", "value"),
        State("predictive-ev-client-store", "data"),
        State("predictive-ev-component-store", "data"),
        State("predictive-selected-unit-store", "data"),
    )
    def switch_internal_tab(tab_value, client, component, selected_unit):
        if not client or not component:
            return no_update

        if tab_value == 'resumen':
            # Render overview
            components = _discover_components(client)
            filepath = components.get(component)
            if not filepath:
                return html.P(t("predictive_callbacks.no_hay_datos_para", component=component), className="text-muted text-center")

            df, df_latest, prev_ranking = _load_overview_component(filepath, component, client)
            if df_latest is None or df_latest.empty:
                return html.P(t("tab_predictive_overview.no_hay_datos_disponibles_para", component=component), className="text-muted text-center")

            return _render_component_overview(df_latest, prev_ranking, component, client, df=df)

        else:
            # Render evidence shell (interactive parts handled by other callbacks)
            components = _discover_components(client)
            filepath = components.get(component)
            if not filepath:
                return html.P(t("predictive_callbacks.no_hay_datos_para", component=component), className="text-muted text-center")

            df, df_latest = _load_evidence_component(filepath, component, client)
            units = sorted(df["Unit"].unique()) if df is not None else []
            failure_mode_options = resolve_failure_mode_options(component, client)

            # A unit picked in Resumen (scatter/table click) or earlier in this
            # tab wins over the first-unit default. It is offered as an option
            # even if this component has no data for it, so the selector always
            # shows the clicked unit and Evidence renders its standard no-data state.
            unit_options = list(units)
            if selected_unit and selected_unit not in unit_options:
                unit_options.append(selected_unit)
            default_unit = selected_unit or (units[0] if units else None)

            return html.Div([
                # Unit selector
                html.Div([
                    html.Div([
                        dcc.Dropdown(
                            id="predictive-ev-unit",
                            options=[{"label": u, "value": u} for u in unit_options],
                            value=default_unit,
                            clearable=False,
                            className="ev-unit-dropdown",
                        ),
                    ], className="ev-unit-selector"),
                ], className="ev-page-header"),

                # Unit banner
                html.Div(id="predictive-ev-unit-banner", style={"marginTop": "1rem"}),

                # KPIs and fleet (updated by callback)
                html.Div(id="predictive-ev-initial-content", className="mt-4"),

                # Failure mode selector
                html.Div([
                    html.Div([
                        html.H5([html.I(className="fas fa-cogs me-2"), t("tab_predictive_component.seleccionar_modo_de_falla")], className="mb-2"),
                        html.P(t("tab_predictive_component.elige_un_modo_de_falla_para"),
                               className="text-muted mb-2", style={"fontSize": "12px"}),
                    ]),
                    dcc.Dropdown(
                        id="predictive-ev-failure-mode",
                        options=failure_mode_options,
                        value=None,
                        clearable=False,
                        className="ev-unit-dropdown",
                        style={"marginTop": "8px"}
                    ),
                ], className="card shadow-sm", style={"marginBottom": "1.5rem", "padding": "16px"}),

                # Detailed evidence (updated by callback)
                html.Div(id="predictive-ev-detailed-content"),
            ])

    # ══════════════════════════════════════════════════════════════════════════
    # OVERVIEW -> EVIDENCE: click a scatter point / table row to open that unit
    # ══════════════════════════════════════════════════════════════════════════

    @app.callback(
        Output("predictive-component-internal-tabs", "value"),
        Output("predictive-selected-unit-store", "data", allow_duplicate=True),
        Input("predictive-fleet-scatter", "clickData"),
        Input({"type": "predictive-fm-row", "unit": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def navigate_to_evidence_from_overview(click_data, _row_clicks):
        """Open Evidence with the clicked unit selected. Only the unit travels:
        the failure mode keeps Evidence's own default."""
        triggered = ctx.triggered_id
        unit = None
        if triggered == "predictive-fleet-scatter":
            points = (click_data or {}).get("points") or []
            if points:
                unit = points[0].get("customdata", points[0].get("text"))
                if isinstance(unit, (list, tuple)):
                    unit = unit[0] if unit else None
        elif isinstance(triggered, dict) and triggered.get("type") == "predictive-fm-row":
            # A re-rendered (re-sorted) table creates fresh rows with n_clicks 0;
            # only a real click, i.e. a positive count, navigates.
            if ctx.triggered and ctx.triggered[0].get("value"):
                unit = triggered.get("unit")
        if not unit:
            return no_update, no_update
        return "evidencia", unit

    @app.callback(
        Output("predictive-selected-unit-store", "data", allow_duplicate=True),
        Input("predictive-ev-unit", "value"),
        prevent_initial_call=True,
    )
    def remember_evidence_unit(selected_unit):
        """Mirror Evidence's selector so leaving and re-entering the tab keeps
        the unit instead of snapping back to an earlier click or the first unit."""
        return selected_unit or no_update

    # ══════════════════════════════════════════════════════════════════════════
    # OVERVIEW: Sort failure mode table by selected period
    # ══════════════════════════════════════════════════════════════════════════

    @app.callback(
        Output("predictive-fm-table-container", "children"),
        Output("predictive-fm-table-state", "data"),
        Input("predictive-fm-sort-selector", "value"),
        Input({"type": "predictive-fm-col-header", "key": ALL}, "n_clicks"),
        State("predictive-fm-table-state", "data"),
        State("predictive-ev-client-store", "data"),
        State("predictive-ev-component-store", "data"),
        prevent_initial_call=True,
    )
    def update_failure_mode_table(window, _header_clicks, state, client, component):
        """Re-sort/re-render the failure mode table (REQ-PR-09/10).

        The window dropdown ("Hoy"/"30 días"/"60 días"/"90 días") picks which
        single ranking column is shown; changing it also re-sorts by that
        column. Clicking a failure-mode column header instead sorts by that
        mode's value at the current window, toggling ascending/descending on
        repeated clicks of the same header.
        """
        if not window or not client or not component:
            return no_update, no_update

        components = _discover_components(client)
        filepath = components.get(component)
        if not filepath:
            return no_update, no_update

        df, df_latest, _ = _load_overview_component(filepath, component, client)
        if df_latest is None or df_latest.empty:
            return no_update, no_update

        failure_modes = resolve_failure_modes(component, client)
        latest = attach_status(df_latest, client, component)
        fm_keys = list(failure_modes.keys())

        state = dict(state or {})
        triggered = ctx.triggered_id
        if isinstance(triggered, dict) and triggered.get("type") == "predictive-fm-col-header":
            key = triggered["key"]
            if state.get("sort_by") == key:
                state["ascending"] = not state.get("ascending", False)
            else:
                state["sort_by"] = key
                state["ascending"] = False
        else:
            state["sort_by"] = window
            state["ascending"] = False

        sort_by = state.get("sort_by", window)
        ascending = state.get("ascending", False)

        if sort_by in fm_keys:
            suffix = WINDOW_SUFFIX.get(window, "_30d")
            actual_sort_col = f"{sort_by}{suffix}"
        else:
            actual_sort_col = sort_by

        if actual_sort_col in latest.columns:
            # "Unit" as a secondary key makes tie order deterministic across
            # renders (W34-10) instead of an unstable-quicksort fallback,
            # while still respecting the column-header ascending/descending
            # toggle above.
            sorted_df = latest.sort_values([actual_sort_col, "Unit"], ascending=[ascending, True])
        else:
            sorted_df = latest.sort_values(["avg_ranking_30d", "Unit"], ascending=[False, True])

        return _failure_table(sorted_df, window, sort_by, ascending, failure_modes), state

    # ══════════════════════════════════════════════════════════════════════════
    # EVIDENCE: Unit banner
    # ══════════════════════════════════════════════════════════════════════════

    @app.callback(
        Output("predictive-ev-unit-banner", "children"),
        Input("predictive-ev-unit", "value"),
        State("predictive-ev-client-store", "data"),
        State("predictive-ev-component-store", "data"),
    )
    def update_unit_banner(selected_unit, client, component):
        if not selected_unit:
            return None

        # Load data to get status context
        ranking_text = ""
        status_text = ""
        status_color = "#667eea"
        if client and component:
            components = _discover_components(client)
            filepath = components.get(component)
            if filepath:
                _, df_latest = _load_evidence_component(filepath, component, client)
                if df_latest is not None and not df_latest.empty:
                    # Status via attach_status() (same source as Estado de
                    # Flota, REQ-PR-04) so the banner never disagrees with the
                    # priority cards for the same unit.
                    latest_with_status = attach_status(df_latest, client, component)
                    row = latest_with_status[latest_with_status["Unit"] == selected_unit]
                    if not row.empty:
                        row = row.iloc[0]
                        ranking_val = float(row.get("ranking", 0))
                        ranking_text = f"{ranking_val:.0f}/100"
                        status_text = row["status"]
                        status_color = {
                            "Anormal": "#e24b4a",
                            "Alerta": "#ef9f27",
                            "Normal": "#1d9e75",
                        }.get(status_text, "#667eea")

        component_label = (component or "").title()

        # ── Load component horómetro (at last evidence date) ──
        horometro_text = "—"
        horometro_date = ""
        if client and component:
            settings = get_settings()
            allowed = [c.upper() for c in settings.component_hours_allowed_clients]
            if client.upper() in allowed:
                comp_hours_file = settings.get_component_hours_path(client.lower())
                if comp_hours_file.exists():
                    try:
                        from src.data.loaders import load_component_hours
                        import re as _re
                        all_hours = load_component_hours(comp_hours_file)
                        if not all_hours.empty:
                            # Normalize unit IDs (T_09 vs T_9)
                            def _norm_uid(uid):
                                m = _re.match(r'^([A-Za-z]+_)0*(\d+)$', str(uid))
                                return f"{m.group(1)}{m.group(2)}" if m else str(uid)

                            unit_norm = _norm_uid(selected_unit)
                            all_hours['_uid_norm'] = all_hours['unitId'].apply(_norm_uid)

                            # Get last evidence date
                            components_map = _discover_components(client)
                            filepath = components_map.get(component)
                            last_ev_date = None
                            if filepath:
                                df_ev, _ = _load_evidence_component(filepath, component, client)
                                if df_ev is not None:
                                    df_ev_unit = df_ev[df_ev["Unit"] == selected_unit]
                                    if not df_ev_unit.empty:
                                        last_ev_date = df_ev_unit["Fecha"].max()

                            hours_component_name = settings.get_component_hours_name(client, component)
                            unit_hours = all_hours[
                                (all_hours['_uid_norm'] == unit_norm) &
                                (all_hours['componentName'] == hours_component_name)
                            ].copy()

                            if not unit_hours.empty and last_ev_date is not None:
                                unit_hours['date_diff'] = abs(unit_hours['sampleDate'] - last_ev_date)
                                closest = unit_hours.sort_values('date_diff').iloc[0]
                                hrs = closest['componentHours_cleaned']
                                date_val = closest['sampleDate']
                                if pd.notna(hrs):
                                    horometro_text = f"{hrs:,.0f} hrs"
                                if pd.notna(date_val):
                                    horometro_date = pd.to_datetime(date_val).strftime('%d %b %Y')
                            elif not unit_hours.empty:
                                latest_row = unit_hours.sort_values('sampleDate').iloc[-1]
                                hrs = latest_row['componentHours_cleaned']
                                if pd.notna(hrs):
                                    horometro_text = f"{hrs:,.0f} hrs"
                    except Exception as e:
                        logger.warning(f"Could not load component hours for banner: {e}")

        return html.Div([
            html.Div([
                html.Div([
                    # Unit icon and name
                    html.Div([
                        html.I(className="fas fa-truck", style={"fontSize": "28px"}),
                    ], style={"marginRight": "16px"}),
                    html.Div([
                        html.Div(t("predictive_callbacks.unidad_en_analisis"), style={
                            "fontSize": "11px", "fontWeight": "500",
                            "textTransform": "uppercase", "letterSpacing": "0.5px",
                            "opacity": "0.8", "marginBottom": "2px"
                        }),
                        html.Div(selected_unit, style={
                            "fontSize": "32px", "fontWeight": "700", "letterSpacing": "-0.5px",
                            "lineHeight": "1.1"
                        }),
                        html.Div(t("predictive_callbacks.componente", component_label=component_label), style={
                            "fontSize": "12px", "opacity": "0.8", "marginTop": "2px"
                        }),
                    ]),
                ], style={"display": "flex", "alignItems": "center"}),
                # Status badges on the right (ranking + horómetro + estado)
                html.Div([
                    # Horómetro badge
                    html.Div([
                        html.Div(t("tables.horometro"), style={
                            "fontSize": "10px", "textTransform": "uppercase",
                            "letterSpacing": "0.5px", "opacity": "0.8", "marginBottom": "4px"
                        }),
                        html.Div(horometro_text, style={
                            "fontSize": "20px", "fontWeight": "700"
                        }),
                        html.Div(horometro_date, style={
                            "fontSize": "9px", "opacity": "0.7", "marginTop": "2px"
                        }) if horometro_date else None,
                    ], style={"textAlign": "center", "marginRight": "20px"}),
                    # Ranking badge
                    html.Div([
                        html.Div(t("predictive_callbacks.ranking_actual"), style={
                            "fontSize": "10px", "textTransform": "uppercase",
                            "letterSpacing": "0.5px", "opacity": "0.8", "marginBottom": "4px"
                        }),
                        html.Div(ranking_text, style={
                            "fontSize": "24px", "fontWeight": "700"
                        }),
                    ], style={"textAlign": "center", "marginRight": "20px"}),
                    html.Div([
                        html.Div(t("fleet_overview.col_status"), style={
                            "fontSize": "10px", "textTransform": "uppercase",
                            "letterSpacing": "0.5px", "opacity": "0.8", "marginBottom": "4px"
                        }),
                        html.Span(status_label(status_text), style={
                            "background": "rgba(255,255,255,0.2)",
                            "padding": "4px 12px", "borderRadius": "12px",
                            "fontSize": "13px", "fontWeight": "600",
                            "border": "1px solid rgba(255,255,255,0.4)"
                        }),
                    ], style={"textAlign": "center"}),
                ], style={"display": "flex", "alignItems": "center"}),
            ], style={
                "display": "flex", "justifyContent": "space-between", "alignItems": "center"
            })
        ], style={
            "background": f"linear-gradient(135deg, {status_color} 0%, {status_color}dd 100%)",
            "color": "white", "padding": "20px 28px", "borderRadius": "12px",
            "boxShadow": f"0 4px 12px {status_color}44", "marginBottom": "1.5rem"
        })

    # ══════════════════════════════════════════════════════════════════════════
    # EVIDENCE: KPIs and fleet comparison (when unit changes)
    # ══════════════════════════════════════════════════════════════════════════

    @app.callback(
        Output("predictive-ev-initial-content", "children"),
        Input("predictive-ev-unit", "value"),
        State("predictive-ev-client-store", "data"),
        State("predictive-ev-component-store", "data"),
    )
    def update_initial_content(selected_unit, client, component):
        if not selected_unit or not client or not component:
            return html.Div(html.P(t("predictive_callbacks.seleccione_una_unidad"), className="text-muted text-center", style={"padding": "40px"}))

        components = _discover_components(client)
        filepath = components.get(component)
        if not filepath:
            return html.Div(html.P(t("tab_predictive_evidence.no_hay_datos_disponibles"), className="text-muted text-center", style={"padding": "40px"}))

        df, df_latest = _load_evidence_component(filepath, component, client)
        if df is None:
            return html.Div(html.P(t("tab_predictive_evidence.no_hay_datos_disponibles"), className="text-muted text-center", style={"padding": "40px"}))

        return render_initial_content(selected_unit, df, df_latest, component, client)

    # ══════════════════════════════════════════════════════════════════════════
    # EVIDENCE: Set default failure mode when unit changes
    # ══════════════════════════════════════════════════════════════════════════

    @app.callback(
        Output("predictive-ev-failure-mode", "value"),
        Input("predictive-ev-unit", "value"),
        State("predictive-ev-client-store", "data"),
        State("predictive-ev-component-store", "data"),
    )
    def set_default_failure_mode(selected_unit, client, component):
        if not selected_unit or not client or not component:
            return no_update

        components = _discover_components(client)
        filepath = components.get(component)
        if not filepath:
            return no_update

        df, df_latest = _load_evidence_component(filepath, component, client)
        if df is None or df_latest is None:
            return no_update

        failure_modes = resolve_failure_modes(component, client)
        row = df_latest[df_latest["Unit"] == selected_unit]
        if row.empty:
            return list(failure_modes.keys())[0] if failure_modes else None

        row = row.iloc[0]
        fm_keys = list(failure_modes.keys())
        fm_scores = {k: float(row[f"{k}_30d"]) if f"{k}_30d" in row.index and pd.notna(row[f"{k}_30d"]) else 0.0 for k in fm_keys}
        return max(fm_scores, key=fm_scores.get) if fm_scores else (fm_keys[0] if fm_keys else None)

    # ══════════════════════════════════════════════════════════════════════════
    # EVIDENCE: Detailed evidence (oil + telemetry)
    # ══════════════════════════════════════════════════════════════════════════

    @app.callback(
        Output("predictive-ev-detailed-content", "children"),
        Input("predictive-ev-unit", "value"),
        Input("predictive-ev-failure-mode", "value"),
        State("predictive-ev-client-store", "data"),
        State("predictive-ev-component-store", "data"),
    )
    def update_detailed_evidence(selected_unit, selected_failure_mode, client, component):
        if not selected_unit or not selected_failure_mode or not client or not component:
            return html.Div(html.P(t("predictive_callbacks.seleccione_una_unidad_y_modo_de"),
                                   className="text-muted text-center", style={"padding": "40px"}))

        components = _discover_components(client)
        filepath = components.get(component)
        if not filepath:
            return html.Div(html.P(t("tab_predictive_evidence.no_hay_datos_disponibles"), className="text-muted text-center", style={"padding": "40px"}))

        df, df_latest = _load_evidence_component(filepath, component, client)
        if df is None:
            return html.Div(html.P(t("tab_predictive_evidence.no_hay_datos_disponibles"), className="text-muted text-center", style={"padding": "40px"}))

        return render_detailed_evidence(selected_unit, df, df_latest, selected_failure_mode, component, client)

    # ══════════════════════════════════════════════════════════════════════════
    # EVIDENCE: Oil chart update (when user changes variable selection)
    # ══════════════════════════════════════════════════════════════════════════

    @app.callback(
        Output("predictive-oil-chart-container", "children"),
        Input("predictive-oil-var-selector", "value"),
        State("predictive-oil-range-store", "data"),
        State("predictive-ev-unit", "value"),
        State("predictive-ev-client-store", "data"),
        State("predictive-ev-component-store", "data"),
        prevent_initial_call=False,
    )
    def update_oil_chart(selected_vars, oil_range, selected_unit, client, component):
        """Update oil timeseries chart based on user-selected variables."""
        from dashboard.components.predictive_charts import create_oil_timeseries_90d
        from dashboard.components.predictive_config import OIL_LABELS, load_predictive_oil_limits_four

        if not selected_vars or not selected_unit or not client or not component:
            return html.P(t("predictive_callbacks.seleccione_al_menos_una_variable_de"),
                         className="text-muted", style={"fontSize": "13px", "padding": "20px", "textAlign": "center"})

        # Resolve per-client labels (fallback to cda if missing) and the
        # four-limit Stewart dict (LIC/LIM/LSM/LSC, v2.8) for this component -
        # never the legacy three-limit OIL_THRESHOLDS table.
        _ckey = (client or "cda").lower()
        oil_labels = OIL_LABELS.get(_ckey, OIL_LABELS["cda"])
        oil_limits_four = load_predictive_oil_limits_four(_ckey, component)

        # Real (non-forward-filled) samples from the oil technique's golden
        # layer - component.csv forward-fills oil values across every daily
        # row between samples, which is what produced the staircase. This is
        # now the sole source for this chart; if there are no matching real
        # samples we show an empty state instead of falling back to it.
        df_oil_real = load_real_oil_samples(client, component, selected_unit)
        if df_oil_real is None or not any(v in df_oil_real.columns for v in selected_vars):
            return html.P(t("predictive_callbacks.no_hay_muestras_de_aceite_reales"),
                         className="text-muted", style={"fontSize": "13px", "padding": "20px", "textAlign": "center"})

        # Always pass limits — the chart function shows limit lines when len(vars)==1
        fig = create_oil_timeseries_90d(
            df_oil_real, selected_vars, oil_labels,
            oil_limits_four=oil_limits_four,
            oil_range=oil_range,
        )

        if fig:
            return dcc.Graph(figure=fig, config={"displayModeBar": False})
        return html.P(t("predictive_callbacks.no_hay_suficientes_datos_historicos"), className="text-muted", style={"fontSize": "13px"})