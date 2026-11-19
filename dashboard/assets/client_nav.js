/**
 * Client-side keyboard and focus handling for tabs (role="tablist").
 *
 * Dash re-renders a tab's panel through a callback; the handlers are delegated on document, so
 * they keep working when the page content is re-rendered.
 */
(function () {
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
