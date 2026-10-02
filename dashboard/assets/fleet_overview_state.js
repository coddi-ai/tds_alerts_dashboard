/**
 * Fleet Overview - client-side view state (Phase 2, Required Changes #5).
 *
 * Dash Pages tears down and rebuilds the Fleet Overview's component tree on
 * every navigation away/back to it (no server-side session tied to "the
 * user's Fleet Overview instance"), so band expanded/collapsed state and
 * scroll position can't be kept in a Dash callback's memory - they're
 * persisted here in sessionStorage instead, and reapplied whenever the
 * Fleet Overview's cards (re)render.
 *
 * All bookkeeping is done through event delegation / a MutationObserver
 * rather than binding listeners to specific nodes, since those nodes are
 * replaced whenever dashboard/callbacks/overview_general_callbacks.py
 * re-renders #overview-fleet-cards (e.g. on client switch).
 */

(function () {
    var STORAGE_KEY_COLLAPSED = 'fleetOverviewCollapsedBands';
    var STORAGE_KEY_SCROLL = 'fleetOverviewScrollY';

    function isFleetOverviewPath() {
        return window.location.pathname.indexOf('/overview/general') !== -1;
    }

    function getCollapsedBands() {
        try {
            return JSON.parse(sessionStorage.getItem(STORAGE_KEY_COLLAPSED) || '[]');
        } catch (e) {
            return [];
        }
    }

    function setCollapsedBands(list) {
        try {
            sessionStorage.setItem(STORAGE_KEY_COLLAPSED, JSON.stringify(list));
        } catch (e) {
            // sessionStorage unavailable (private mode, etc.) - collapse still
            // works for this render, it just won't survive navigation.
        }
    }

    function applyCollapsedState() {
        var collapsed = getCollapsedBands();
        document.querySelectorAll('[data-fleet-band]').forEach(function (section) {
            var band = section.getAttribute('data-fleet-band');
            var body = section.querySelector('[data-fleet-band-body]');
            var toggle = section.querySelector('[data-fleet-band-toggle]');
            if (!body || !toggle) {
                return;
            }
            var isCollapsed = collapsed.indexOf(band) !== -1;
            body.style.display = isCollapsed ? 'none' : '';
            toggle.classList.toggle('fleet-band-collapsed', isCollapsed);
        });
    }

    function restoreScroll() {
        var y = parseInt(sessionStorage.getItem(STORAGE_KEY_SCROLL) || '0', 10);
        if (y > 0) {
            window.scrollTo(0, y);
        }
    }

    // Toggle a band on click (event delegation - survives re-renders).
    document.addEventListener('click', function (e) {
        var toggle = e.target.closest('[data-fleet-band-toggle]');
        if (!toggle) {
            return;
        }
        var section = toggle.closest('[data-fleet-band]');
        var body = section && section.querySelector('[data-fleet-band-body]');
        if (!section || !body) {
            return;
        }
        var band = section.getAttribute('data-fleet-band');
        var collapsed = getCollapsedBands();
        var idx = collapsed.indexOf(band);
        var willCollapse = idx === -1;
        if (willCollapse) {
            collapsed.push(band);
        } else {
            collapsed.splice(idx, 1);
        }
        setCollapsedBands(collapsed);
        body.style.display = willCollapse ? 'none' : '';
        toggle.classList.toggle('fleet-band-collapsed', willCollapse);
    });

    // Persist scroll position continuously while on the Fleet Overview page.
    var scrollTimer = null;
    window.addEventListener('scroll', function () {
        if (!isFleetOverviewPath()) {
            return;
        }
        if (scrollTimer) {
            return;
        }
        scrollTimer = window.setTimeout(function () {
            scrollTimer = null;
            try {
                sessionStorage.setItem(STORAGE_KEY_SCROLL, String(window.scrollY));
            } catch (e) {
                // ignore
            }
        }, 150);
    });

    // Reapply collapsed-band state and restore scroll whenever the Fleet
    // Overview's cards (re)appear in the DOM.
    var observer = new MutationObserver(function () {
        if (!isFleetOverviewPath()) {
            return;
        }
        if (!document.getElementById('overview-fleet-cards')) {
            return;
        }
        applyCollapsedState();
        restoreScroll();
    });

    document.addEventListener('DOMContentLoaded', function () {
        var root = document.getElementById('app-content-wrapper') || document.body;
        observer.observe(root, { childList: true, subtree: true });
    });
})();
