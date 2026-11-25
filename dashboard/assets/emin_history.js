/* Keep the fleet position when an equipment link opens the detail tab. */
(function () {
    "use strict";

    let origin;
    let activeView;
    let activePage;

    function scrollPositions(element) {
        const positions = [];
        for (let node = element.parentElement; node; node = node.parentElement) {
            if (node.scrollHeight > node.clientHeight || node.scrollWidth > node.clientWidth) {
                positions.push([node, node.scrollLeft, node.scrollTop]);
            }
        }
        return positions;
    }

    function openChronology(kind, query) {
        const setProps = window.dash_clientside?.set_props;
        if (!setProps) return;
        setProps("emin-history-record-type", {value: kind});
        setProps("emin-history-record-search", {value: query});
        const type = document.getElementById("emin-history-record-type");
        type?.focus({preventScroll: true});
        type?.scrollIntoView({block: "center"});
    }

    document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-emin-open-unit], [data-emin-back], [data-emin-movement-filter], [data-emin-group-filter], [data-emin-record-filter]");
        const setProps = window.dash_clientside?.set_props;
        if (!button || !setProps) return;

        if (button.hasAttribute("data-emin-record-filter")) {
            openChronology(button.dataset.eminRecordFilter, button.dataset.eminRecordQuery || "");
            return;
        }

        if (button.hasAttribute("data-emin-movement-filter") || button.hasAttribute("data-emin-group-filter")) {
            if (button.hasAttribute("data-emin-movement-filter")) {
                setProps("emin-history-movement-filter", {value: button.dataset.eminMovementFilter});
            } else {
                setProps("emin-history-group", {value: button.dataset.eminGroupFilter});
            }
            const ranking = document.getElementById("emin-history-ranking-heading");
            ranking?.focus({preventScroll: true});
            ranking?.scrollIntoView({block: "start"});
            return;
        }

        if (button.hasAttribute("data-emin-back")) {
            setProps("emin-history-view-tabs", {value: "fleet"});
            return;
        }
        origin = {button, positions: scrollPositions(button)};
        const unit = button.dataset.eminOpenUnit;
        const period = button.dataset.eminPeriod;
        setProps("emin-history-evidence-context", {data: {unit, period: button.dataset.eminPeriod}});
        setProps("emin-history-unit", {value: unit});
        if (["week", "month", "quarter", "history"].includes(period)) {
            setProps("emin-history-trend-window", {value: period});
        }
        setProps("emin-history-view-tabs", {value: "unit"});
    });

    window.dash_clientside = window.dash_clientside || {};
    window.dash_clientside.eminHistory = {
        openFleetUnit(clickData) {
            const unit = clickData?.points?.[0]?.customdata?.[0];
            if (typeof unit !== "string" || !unit) {
                return [window.dash_clientside.no_update, window.dash_clientside.no_update, window.dash_clientside.no_update];
            }
            const period = clickData?.points?.[0]?.customdata?.[4];
            return [unit, "unit", ["week", "month", "quarter", "history"].includes(period) ? period : "week"];
        },
        openTrendDay(clickData) {
            const day = String(clickData?.points?.[0]?.x || "").slice(0, 10);
            if (/^\d{4}-\d{2}-\d{2}$/.test(day)) {
                openChronology("all", day);
            }
            return window.dash_clientside.no_update;
        },
        switchView(value) {
            const page = document.querySelector(".emin-history-page");
            if (page !== activePage) {
                activePage = page;
                activeView = undefined;
                if (!page?.contains(origin?.button)) origin = undefined;
            }
            const detail = value === "unit";
            if (value !== activeView) {
                activeView = value;
                requestAnimationFrame(() => requestAnimationFrame(() => {
                    if (!page?.isConnected || activeView !== value) return;
                    if (detail && origin) {
                        const heading = document.getElementById("emin-history-detail-heading");
                        heading?.focus({preventScroll: true});
                        heading?.scrollIntoView({block: "start"});
                    } else if (!detail && origin) {
                        if (origin.button.isConnected) origin.button.focus({preventScroll: true});
                        for (const [node, left, top] of origin.positions) {
                            if (node.isConnected) node.scrollTo(left, top);
                        }
                        origin = undefined;
                    }
                }));
            }
            return [{display: detail ? "none" : "block"}, {display: detail ? "block" : "none"}];
        }
    };
}());
