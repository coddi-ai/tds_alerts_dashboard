"""Sortable, paginated tables of the Monitor de Aceite (the fleet matrix and the frequency panel).

Both are built from plain HTML, not a `dash_table`: their cells are real buttons (Tab / Enter),
carry chips and bars, and every one of them knows its own row. A click is resolved from the unit
and component written in the button's id, never from the row's position in the current page, so
page 2, a re-sorted table or a filtered one open the right unit (Requirement 3).

State lives in two stores per table:
  * `<table>-data`: what the filters produced (server computed, one entry per row);
  * `<table>-view`: `{sort: {col, dir} | None, page, rev, expanded}` - how that data is shown.
A controller callback turns header clicks, pager clicks, the group toggle and new data into the
next view; the render callback only reads the two stores.

`expanded` is whether the table's collapsed group of columns (the fleet matrix's "Otros componentes")
is open. It lives in the view, so it survives paging, sorting and even a change of filters.
"""

from __future__ import annotations

import uuid
from typing import Callable, Dict, Optional

from dash import ALL, Input, Output, State, ctx, dcc, html
from dash.exceptions import PreventUpdate

from src.i18n import t

PAGE_SIZE = 30

ASC, DESC = "asc", "desc"


def new_revision() -> str:
    """A token that differs on every data build, so an identical result still resets the view."""
    return uuid.uuid4().hex


def initial_view() -> dict:
    return {"sort": None, "page": 0, "rev": None, "expanded": False}


def total_pages(total_rows: int, page_size: int = PAGE_SIZE) -> int:
    return max(1, -(-int(total_rows) // page_size))


def clamp_page(page: int, total_rows: int, page_size: int = PAGE_SIZE) -> int:
    return max(0, min(int(page), total_pages(total_rows, page_size) - 1))


def next_view(view: Optional[dict], trigger: dict, *, total_rows: int, first_dirs: Dict[str, str],
              page_size: int = PAGE_SIZE) -> dict:
    """The view after one interaction.

    `trigger` is one of: `{"kind": "data", "rev": ...}` (new rows: back to page 1, same sort),
    `{"kind": "sort", "col": ...}` (a header: first click uses the column's natural direction - `first_dirs[col]`,
    else `first_dirs["*"]`, else ascending - and the next ones flip it; back to page 1), `{"kind": "page", "dir": "prev" | "next"}`
    and `{"kind": "group", "columns": [...]}` (open / close the group of those columns: the page and the sort stay, except
    that closing a group takes away a sort on a column that is no longer there).
    """
    view = dict(view or initial_view())
    kind = trigger.get("kind")
    if kind == "data":
        view.update(page=0, rev=trigger.get("rev"))
    elif kind == "sort":
        column = trigger["col"]
        current = view.get("sort") or {}
        if current.get("col") == column:
            direction = DESC if current.get("dir") == ASC else ASC
        else:
            direction = first_dirs.get(column, first_dirs.get("*", ASC))
        view.update(sort={"col": column, "dir": direction}, page=0)
    elif kind == "page":
        step = -1 if trigger.get("dir") == "prev" else 1
        view["page"] = clamp_page(int(view.get("page") or 0) + step, total_rows, page_size)
    elif kind == "group":
        view["expanded"] = not view.get("expanded")
        if not view["expanded"] and (view.get("sort") or {}).get("col") in set(trigger.get("columns") or ()):
            view["sort"] = None
    return view


def page_slice(rows: list, view: Optional[dict], page_size: int = PAGE_SIZE) -> tuple:
    """`(rows of the current page, page index, first row number)`; the page is clamped to the data."""
    page = clamp_page((view or {}).get("page") or 0, len(rows), page_size)
    start = page * page_size
    return rows[start:start + page_size], page, start


def sort_button(table: str, col_id: str, label: str, view: Optional[dict]) -> html.Button:
    """Header button; the arrow shows the active column and direction."""
    sort = (view or {}).get("sort") or {}
    active = sort.get("col") == col_id
    arrow = ("▲" if sort.get("dir") == ASC else "▼") if active else "↕"
    return html.Button(
        [html.Span(label), html.Span(arrow, className="oil-sort__arrow", **{"aria-hidden": "true"})],
        id={"type": f"{table}-sort", "col": col_id},
        className="oil-sort",
        type="button",
        n_clicks=0,
        title=t("oil_table.ordenar_por", columna=label),
        **{"data-active": "true" if active else "false"},
    )


def sortable_th(table: str, col_id: str, label: str, view: Optional[dict], *, align: str = "center",
                scope: str = "col", extra_class: str = "", **attrs) -> html.Th:
    """`<th aria-sort>` holding the sort button of one column. `extra_class` and `attrs` (e.g. `rowSpan`)
    go on the `<th>`."""
    sort = (view or {}).get("sort") or {}
    if sort.get("col") == col_id:
        aria_sort = "ascending" if sort.get("dir") == ASC else "descending"
    else:
        aria_sort = "none"
    return html.Th(
        sort_button(table, col_id, label, view),
        scope=scope,
        className=" ".join(filter(None, ["oil-col-left" if align == "left" else "oil-col-center", extra_class])),
        **{"aria-sort": aria_sort},
        **attrs,
    )


def pager(table: str, *, page: int, total_rows: int, page_size: int = PAGE_SIZE) -> html.Nav:
    """"Mostrando x-y de N" with Anterior / Siguiente buttons."""
    pages = total_pages(total_rows, page_size)
    first = page * page_size + 1 if total_rows else 0
    last = min(total_rows, (page + 1) * page_size)
    return html.Nav(
        [
            html.Span(t("oil_table.mostrando", desde=first, hasta=last, total=total_rows), role="status"),
            html.Div(
                [
                    html.Button(t("oil_table.anterior"), id={"type": f"{table}-page", "dir": "prev"},
                                type="button", n_clicks=0, disabled=page <= 0),
                    html.Span(t("oil_table.pagina", pagina=page + 1, paginas=pages), className="align-self-center"),
                    html.Button(t("oil_table.siguiente"), id={"type": f"{table}-page", "dir": "next"},
                                type="button", n_clicks=0, disabled=page >= pages - 1),
                ],
                className="oil-pager__buttons",
            ),
        ],
        className="oil-pager",
        **{"aria-label": t("oil_table.paginacion")},
    )


def stores(table: str, data=None) -> list:
    """The two stores a table needs, to be placed in the tab layout."""
    return [
        dcc.Store(id=f"{table}-data", data=data),
        dcc.Store(id=f"{table}-view", data=initial_view()),
    ]


def register_view_controller(app, table: str, first_dirs: Dict[str, str],
                             rows_of: Callable[[dict], int] = lambda data: len((data or {}).get("rows", []))) -> None:
    """Wire `<table>-data`, the header buttons, the pager buttons and the group toggle to `<table>-view`.

    A table with no group of columns simply never renders a toggle: the pattern then matches nothing.
    The toggle needs the columns of the group (`data["grouped"]`) to drop a sort on a column that
    closing the group hides.
    """

    @app.callback(
        Output(f"{table}-view", "data"),
        Input(f"{table}-data", "data"),
        Input({"type": f"{table}-sort", "col": ALL}, "n_clicks"),
        Input({"type": f"{table}-page", "dir": ALL}, "n_clicks"),
        Input({"type": f"{table}-group", "name": ALL}, "n_clicks"),
        State(f"{table}-view", "data"),
        prevent_initial_call=True,
    )
    def _update_view(data, _sort_clicks, _page_clicks, _group_clicks, view):
        trigger_id = ctx.triggered_id
        if trigger_id is None:
            raise PreventUpdate
        if trigger_id == f"{table}-data":
            return next_view(view, {"kind": "data", "rev": (data or {}).get("rev")},
                             total_rows=rows_of(data), first_dirs=first_dirs)
        # A header, pager or group button. Re-rendered buttons arrive with a zero click count: not a click.
        if not ctx.triggered or not ctx.triggered[0].get("value"):
            raise PreventUpdate
        if trigger_id.get("type") == f"{table}-sort":
            return next_view(view, {"kind": "sort", "col": trigger_id["col"]},
                             total_rows=rows_of(data), first_dirs=first_dirs)
        if trigger_id.get("type") == f"{table}-group":
            return next_view(view, {"kind": "group", "columns": (data or {}).get("grouped", [])},
                             total_rows=rows_of(data), first_dirs=first_dirs)
        return next_view(view, {"kind": "page", "dir": trigger_id["dir"]},
                         total_rows=rows_of(data), first_dirs=first_dirs)
