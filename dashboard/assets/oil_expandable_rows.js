/* Expandable rows of the Monitor de Aceite lists (Panel de Frecuencia: the detail of a unit).
 *
 * The markup is plain HTML written by Dash:
 *   <button data-oil-expand aria-expanded="false" aria-controls="<id of the detail row>">   one per unit
 *   <tr id="<id>" hidden>                                                                     its detail
 *   <button data-oil-expand-all="<id of the list container>"
 *           data-label-expand="..." data-label-collapse="...">                                the "all" switch
 *
 * One delegated click listener (so it keeps working whenever Dash re-renders the list) opens or closes
 * the detail named by the button's own `aria-controls`: never a row position. Real buttons give the
 * keyboard (Tab, Enter, Space) for free, and toggling in place keeps the focus on the button.
 * "all" acts on the rows that are in the DOM, which is the current page. The words of the "all" button
 * come from its data attributes; this file holds no text.
 */
(function () {
    "use strict";

    function isOpen(button) {
        return button.getAttribute("aria-expanded") === "true";
    }

    function setOpen(button, open) {
        button.setAttribute("aria-expanded", open ? "true" : "false");
        var detail = document.getElementById(button.getAttribute("aria-controls"));
        if (detail) {
            detail.hidden = !open;
        }
    }

    function togglesIn(container) {
        return Array.prototype.slice.call(container.querySelectorAll("[data-oil-expand]"));
    }

    function containerOf(allButton) {
        return document.getElementById(allButton.getAttribute("data-oil-expand-all"));
    }

    /* The "all" button shows its collapse label when every row of the list is open and its expand label
       otherwise, and is disabled when the list has no rows. Writes only what changed, so watching the
       DOM for re-renders never feeds on its own updates. */
    function syncAll(allButton) {
        var container = containerOf(allButton);
        var toggles = container ? togglesIn(container) : [];
        var allOpen = toggles.length > 0 && toggles.every(isOpen);
        var label = allButton.querySelector(".oil-expand-all__label") || allButton;
        var text = allOpen ? allButton.getAttribute("data-label-collapse") : allButton.getAttribute("data-label-expand");
        if (text && label.textContent !== text) {
            label.textContent = text;
        }
        var disabled = toggles.length === 0;
        if (allButton.disabled !== disabled) {
            allButton.disabled = disabled;
        }
    }

    function syncEvery() {
        document.querySelectorAll("[data-oil-expand-all]").forEach(syncAll);
    }

    document.addEventListener("click", function (event) {
        var target = event.target;
        if (!target || !target.closest) { return; }

        var all = target.closest("[data-oil-expand-all]");
        if (all) {
            var container = containerOf(all);
            if (!container) { return; }
            var toggles = togglesIn(container);
            var open = !(toggles.length > 0 && toggles.every(isOpen));
            toggles.forEach(function (button) { setOpen(button, open); });
            syncAll(all);
            return;
        }

        var toggle = target.closest("[data-oil-expand]");
        if (toggle) {
            setOpen(toggle, !isOpen(toggle));
            syncEvery();
        }
    });

    var scheduled = false;
    function schedule() {
        if (scheduled) { return; }
        scheduled = true;
        window.requestAnimationFrame(function () {
            scheduled = false;
            syncEvery();
        });
    }

    function start() {
        syncEvery();
        new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }
})();
