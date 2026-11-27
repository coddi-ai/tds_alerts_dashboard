/* Keep the fleet table and its filter in place while reviewing an equipment record. */
(function () {
    "use strict";

    let origin;
    let activePage;
    let activeView;

    function scrollPositions(element) {
        const positions = [];
        for (let node = element.parentElement; node; node = node.parentElement) {
            if (node.scrollHeight > node.clientHeight || node.scrollWidth > node.clientWidth) {
                positions.push([node, node.scrollLeft, node.scrollTop]);
            }
        }
        return positions;
    }

    document.addEventListener("click", (event) => {
        const action = event.target.closest("[data-emin-open-unit], [data-emin-back]");
        const setProps = window.dash_clientside?.set_props;
        if (!action || !activePage?.contains(action) || !setProps) return;
        event.preventDefault();

        if (action.hasAttribute("data-emin-back")) {
            setProps("emin-history-view-tabs", {value: "fleet"});
        } else {
            origin = {action, positions: scrollPositions(action)};
            const unit = action.dataset.eminOpenUnit;
            const record = action.dataset.eminOpenRecord;
            setProps("emin-beta-focused-record", {data: record === undefined ? null : {unit, record: Number(record)}});
            setProps("emin-history-unit", {value: unit});
            setProps("emin-history-view-tabs", {value: "unit"});
        }
    });

    window.dash_clientside = window.dash_clientside || {};
    window.dash_clientside.eminHistory = {
        switchView(value) {
            const page = document.querySelector(".emin-beta-page");
            if (page !== activePage) {
                activePage = page;
                activeView = undefined;
                if (!page?.contains(origin?.action)) origin = undefined;
            }
            const detail = value === "unit";
            if (value !== activeView) {
                activeView = value;
                requestAnimationFrame(() => requestAnimationFrame(() => {
                    if (!page?.isConnected || activeView !== value || !origin) return;
                    if (detail) {
                        const heading = document.getElementById("emin-history-detail-heading");
                        heading?.focus({preventScroll: true});
                        heading?.scrollIntoView({block: "start"});
                    } else {
                        origin.action.focus({preventScroll: true});
                        for (const [node, left, top] of origin.positions) {
                            if (node.isConnected) node.scrollTo(left, top);
                        }
                        origin = undefined;
                    }
                }));
            }
            return [{display: detail ? "none" : "block"}, {display: detail ? "block" : "none"}];
        },
    };
}());
