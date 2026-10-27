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

    // The user's own choice of collapsed bands, or null when they have made none: the page
    // then keeps the state it was rendered in (Anormal open, the rest collapsed).
    function getCollapsedBands() {
        try {
            var raw = sessionStorage.getItem(STORAGE_KEY_COLLAPSED);
            return raw === null ? null : JSON.parse(raw);
        } catch (e) {
            return null;
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

    // While a search is showing, the server decides which bands are open (the ones with
    // matches); the user's stored choice neither applies nor is overwritten.
    function searchActive() {
        return !!document.querySelector('[data-fleet-search="active"]');
    }

    function setBand(section, collapsed) {
        var body = section.querySelector('[data-fleet-band-body]');
        var toggle = section.querySelector('[data-fleet-band-toggle]');
        if (!body || !toggle) {
            return;
        }
        body.style.display = collapsed ? 'none' : '';
        toggle.classList.toggle('fleet-band-collapsed', collapsed);
        toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    }

    function applyCollapsedState() {
        var collapsed = getCollapsedBands();
        if (collapsed === null || searchActive()) {
            return;
        }
        document.querySelectorAll('[data-fleet-band]').forEach(function (section) {
            setBand(section, collapsed.indexOf(section.getAttribute('data-fleet-band')) !== -1);
        });
    }

    function restoreScroll() {
        if (searchActive()) {
            return;
        }
        var y = parseInt(sessionStorage.getItem(STORAGE_KEY_SCROLL) || '0', 10);
        if (y > 0) {
            window.scrollTo(0, y);
        }
    }

    // Toggle a band on click (event delegation - survives re-renders). Enter and Space on the
    // focused <button> arrive here as clicks.
    document.addEventListener('click', function (e) {
        var toggle = e.target.closest('[data-fleet-band-toggle]');
        if (!toggle) {
            return;
        }
        var section = toggle.closest('[data-fleet-band]');
        if (!section) {
            return;
        }
        setBand(section, toggle.getAttribute('aria-expanded') === 'true');
        if (searchActive()) {
            return;
        }
        var collapsed = [];
        document.querySelectorAll('[data-fleet-band]').forEach(function (other) {
            var otherToggle = other.querySelector('[data-fleet-band-toggle]');
            if (otherToggle && otherToggle.getAttribute('aria-expanded') === 'false') {
                collapsed.push(other.getAttribute('data-fleet-band'));
            }
        });
        setCollapsedBands(collapsed);
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
