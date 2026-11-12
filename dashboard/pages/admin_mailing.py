"""Admin → Mailing: manual send of the alert summary email (documentation/mailling/03)."""

import dash
from dash import html

from config.users import is_admin
from dashboard.auth import resolve_authenticated_username
from dashboard.tabs.tab_mailing import create_layout
from src.i18n import page_title, t


def layout(**kwargs):
    # The route guard already keeps non-admins out, but it reads the role the browser sends.
    # Re-check on the server, from the session, so a tampered page state cannot open this page.
    username = resolve_authenticated_username()
    if not username or not is_admin(username):
        return html.Div(t("mailing.forbidden"), className="text-muted mt-4", role="alert")
    return create_layout()


dash.register_page(
    __name__,
    path="/admin/mailing",
    title=page_title("page.title.admin_mailing"),
    layout=layout,
)
