from src.i18n import page_title, t
import dash
from dash import html

from config.users import is_admin
from dashboard.auth import resolve_authenticated_username
from dashboard.tabs.tab_user_registry import create_layout


def layout(**kwargs):
    # The route guard already keeps non-admins out, but it reads the role the browser sends.
    # Re-check on the server, from the session, so a tampered page state cannot open this page.
    username = resolve_authenticated_username()
    if not username or not is_admin(username):
        return html.Div(t("user_registry.forbidden"), className="text-muted mt-4", role="alert")
    return create_layout(**kwargs)


dash.register_page(
    __name__,
    path="/admin/registro-usuarios",
    title=page_title("page.title.admin_user_registry"),
    layout=layout,
)
