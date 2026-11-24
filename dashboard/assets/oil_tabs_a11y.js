/* Keyboard access for the Monitor de Aceite tabs (ui_notes_improved.md §6).
 *
 * Dash renders a dcc.Tab as a plain <div>, which the keyboard cannot reach. The Oil tabs carry the
 * `oil-tab` class; this script makes each one focusable (Tab), operable (Enter / Space) and announces
 * it as a tab to assistive technology, and keeps `aria-selected` in step with the selected tab. It
 * only touches elements with that class, and re-applies itself when Dash re-renders them.
 */
(function () {
    "use strict";

    function enhance(tab) {
        if (!tab.dataset.oilTabA11y) {
            tab.dataset.oilTabA11y = "1";
            tab.setAttribute("role", "tab");
            tab.setAttribute("tabindex", "0");
            tab.addEventListener("keydown", function (event) {
                if (event.key === "Enter" || event.key === " " || event.key === "Spacebar") {
                    event.preventDefault();
                    tab.click();
                }
            });
            var bar = tab.parentElement;
            if (bar && !bar.getAttribute("role")) {
                bar.setAttribute("role", "tablist");
            }
        }
        tab.setAttribute("aria-selected", tab.classList.contains("tab--selected") ? "true" : "false");
    }

    function scan() {
        document.querySelectorAll(".oil-tab").forEach(enhance);
    }

    var scheduled = false;
    function schedule() {
        if (scheduled) { return; }
        scheduled = true;
        window.requestAnimationFrame(function () {
            scheduled = false;
            scan();
        });
    }

    function start() {
        scan();
        new MutationObserver(schedule).observe(document.body, {
            childList: true, subtree: true, attributes: true, attributeFilter: ["class"],
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }
})();
