"""
Language selector (Español / English) shown in the top bar and on the login page.

The control itself only displays the active language; switching is done in the
browser by dashboard/assets/i18n_language.js (see `register_language_callbacks`),
which stores the choice in the `app_language` cookie and reloads the page so the
server renders every layout and callback output in the new language.
"""

from dash import Dash, Input, Output, dcc, html

from src.i18n import LANGUAGES, current_language, t

LANGUAGE_SELECTOR_ID = "language-selector"
# Inert sink for the clientside callback below; lives in the root layout (create_app_layout).
LANGUAGE_SYNC_STORE_ID = "language-sync-store"


def create_language_selector(on_dark_background: bool = True) -> html.Div:
    """Compact selector with the globe icon, styled like the navbar's client selector."""
    label_class = "text-white-50 me-2" if on_dark_background else "text-muted me-2"
    return html.Div(
        [
            html.Span(
                html.I(className="fas fa-globe", style={"fontSize": "0.75rem"}),
                className=label_class,
                title=t("lang.selector_label"),
            ),
            dcc.Dropdown(
                id=LANGUAGE_SELECTOR_ID,
                options=[{"label": name, "value": code} for code, name in LANGUAGES.items()],
                value=current_language(),
                clearable=False,
                searchable=False,
                style={"width": "120px", "fontSize": "0.85rem"},
                className="client-compact-selector language-selector",
            ),
        ],
        className="d-flex align-items-center",
        **{"aria-label": t("lang.selector_label")},
    )


def register_language_callbacks(app: Dash) -> None:
    """Persist the chosen language in the cookie and reload to apply it.

    Clientside on purpose: the cookie has to be written by the browser, and a
    reload is the one step that makes the server re-render all static text. The
    dropdown is seeded with the active language, so the callback that Dash fires
    when the control first appears finds nothing to change and does nothing.
    """
    app.clientside_callback(
        """
        function(language) {
            if (!language || !window.appI18n) {
                throw window.dash_clientside.PreventUpdate;
            }
            if (language === window.appI18n.currentLanguage()) {
                throw window.dash_clientside.PreventUpdate;
            }
            window.appI18n.setLanguage(language);
            return window.dash_clientside.no_update;
        }
        """,
        Output(LANGUAGE_SYNC_STORE_ID, "data"),
        Input(LANGUAGE_SELECTOR_ID, "value"),
        prevent_initial_call=True,
    )
