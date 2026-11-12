/**
 * Client-side navigation for controls that are not links.
 *
 * Dash Pages routes without a reload when a dcc.Link changes the URL. A native <select>
 * (the Unit Detail's "Cambiar unidad") cannot be a link, so it does what dcc.Link does:
 * push the new URL and tell Dash's Location component about it. The listener is
 * delegated on document, so it keeps working when the page content is re-rendered.
 */
(function () {
    document.addEventListener('change', function (e) {
        var select = e.target.closest ? e.target.closest('select[data-unit-nav]') : null;
        if (!select || !select.value) {
            return;
        }
        window.history.pushState({}, '', select.value);
        window.dispatchEvent(new CustomEvent('_dashprivate_pushstate'));
        window.scrollTo(0, 0);
    });

    // Tabs (role="tablist"): the arrow keys, Home and End move between the tabs and select
    // the one they land on, as the WAI-ARIA tab pattern asks. Enter / Space select natively.
    document.addEventListener('keydown', function (e) {
        var tab = e.target.closest ? e.target.closest('[role="tab"]') : null;
        if (!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) {
            return;
        }
        var tabs = Array.prototype.slice.call(tab.closest('[role="tablist"]').querySelectorAll('[role="tab"]'));
        var index = tabs.indexOf(tab);
        var next = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1
            : (index + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
        e.preventDefault();
        tabs[next].focus();
        tabs[next].click();
    });

    // Choosing a tab re-renders its panel through a callback, and the page's loading wrapper
    // hides the content meanwhile, which drops keyboard focus. Give it back to the tab that was
    // chosen once it reports itself selected.
    var chosenTab = null;
    document.addEventListener('click', function (e) {
        var tab = e.target.closest ? e.target.closest('[role="tab"]') : null;
        chosenTab = tab ? tab.id : null;
    });
    new MutationObserver(function () {
        if (!chosenTab) {
            return;
        }
        var tab = document.getElementById(chosenTab);
        if (tab && tab.getAttribute('aria-selected') === 'true' && document.activeElement !== tab) {
            tab.focus();
        }
    }).observe(document.documentElement, {attributes: true, subtree: true, attributeFilter: ['aria-selected', 'class', 'style']});
})();
