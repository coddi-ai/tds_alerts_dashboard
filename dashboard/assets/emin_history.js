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

    document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-emin-open-unit], [data-emin-back]");
        const setProps = window.dash_clientside?.set_props;
        if (!button || !setProps) return;

        if (button.hasAttribute("data-emin-back")) {
            setProps("emin-history-view-tabs", {value: "fleet"});
            return;
        }
        origin = {button, positions: scrollPositions(button)};
        const unit = button.dataset.eminOpenUnit;
        setProps("emin-history-evidence-context", {data: {unit, period: button.dataset.eminPeriod}});
        setProps("emin-history-unit", {value: unit});
        setProps("emin-history-view-tabs", {value: "unit"});
    });

    window.dash_clientside = window.dash_clientside || {};
    window.dash_clientside.eminHistory = {
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
