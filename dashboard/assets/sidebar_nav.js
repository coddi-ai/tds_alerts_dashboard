/**
 * Sidebar sections: independent expand/collapse, and the flyouts of the icon-only rail.
 *
 * The markup comes from dashboard/layout.py::build_menu_items (a `.nav-section` per section,
 * with a `.nav-section-header` button and its `.nav-section-links`) and is re-rendered by a
 * Dash callback on every navigation and client switch. State therefore lives here, keyed by
 * section id, and is written as a <style> element outside React's tree - so a re-render can
 * neither lose it nor be confused by it.
 *
 *   expanded sidebar: a header toggles its own section; the others are untouched.
 *   rail (#dashboard-shell.sidebar-collapsed): a header opens that section's links as a flyout
 *   beside the icon; one flyout at a time. Choosing a link, clicking elsewhere, or Escape
 *   closes it. The rail itself is left collapsed.
 *
 * Section state is session-only on purpose (every load starts fully expanded): whether it
 * should persist is still an open product decision. The rail/expanded preference already
 * persists through #sidebar-collapsed-store.
 */
(function () {
    var STYLE_ID = 'sidebar-nav-state';
    var collapsedSections = new Set();
    var openFlyout = null;      // section id of the open flyout, rail mode only
    var flyoutTop = 0;
    var wasRail = false;
    var observedShell = null;
    var shellObserver = null;
    var scheduled = false;

    function isRail() {
        var shell = document.getElementById('dashboard-shell');
        return !!shell && shell.classList.contains('sidebar-collapsed');
    }

    function safeId(id) {
        return String(id).replace(/[^A-Za-z0-9_-]/g, '');
    }

    function headers() {
        return Array.prototype.slice.call(document.querySelectorAll('.nav-section-header'));
    }

    function stateCss() {
        var rules = [];
        collapsedSections.forEach(function (id) {
            rules.push(
                '#dashboard-shell:not(.sidebar-collapsed) .nav-section[data-section="' + safeId(id) + '"] .nav-section-links{display:none}'
            );
        });
        if (openFlyout !== null && isRail()) {
            rules.push(
                '#dashboard-shell.sidebar-collapsed .nav-section[data-section="' + safeId(openFlyout) + '"] .nav-section-links{display:block;top:' + flyoutTop + 'px}'
            );
        }
        return rules.join('\n');
    }

    /** Bring the DOM in line with the state above; writes only what differs. */
    function sync() {
        scheduled = false;
        var rail = isRail();
        if (rail !== wasRail) {
            openFlyout = null;
            wasRail = rail;
        }
        var buttons = headers();
        if (openFlyout !== null && !buttons.some(function (b) { return b.dataset.section === openFlyout; })) {
            openFlyout = null;  // the section left the menu (client switch)
        }

        var style = document.getElementById(STYLE_ID);
        if (!style) {
            style = document.createElement('style');
            style.id = STYLE_ID;
            document.head.appendChild(style);
        }
        var css = stateCss();
        if (style.textContent !== css) {
            style.textContent = css;
        }

        buttons.forEach(function (button) {
            var id = button.dataset.section;
            var expanded = rail ? openFlyout === id : !collapsedSections.has(id);
            var value = expanded ? 'true' : 'false';
            if (button.getAttribute('aria-expanded') !== value) {
                button.setAttribute('aria-expanded', value);
            }
        });

        bindShell();
    }

    function schedule() {
        if (!scheduled) {
            scheduled = true;
            window.requestAnimationFrame(sync);
        }
    }

    /** The shell's class flips between rail and expanded; watch whichever shell is current. */
    function bindShell() {
        var shell = document.getElementById('dashboard-shell');
        if (shell === observedShell) {
            return;
        }
        if (shellObserver) {
            shellObserver.disconnect();
        }
        observedShell = shell;
        if (shell) {
            shellObserver = new MutationObserver(schedule);
            shellObserver.observe(shell, {attributes: true, attributeFilter: ['class']});
        }
    }

    function toggleFlyout(button) {
        var id = button.dataset.section;
        if (openFlyout === id) {
            openFlyout = null;
            sync();
            return;
        }
        openFlyout = id;
        flyoutTop = Math.round(button.getBoundingClientRect().top);
        sync();
        // The panel only has a height once shown: pull it up if it would run off the screen.
        var panel = document.getElementById(button.getAttribute('aria-controls'));
        if (panel) {
            var overflow = flyoutTop + panel.getBoundingClientRect().height - (window.innerHeight - 8);
            if (overflow > 0) {
                flyoutTop = Math.max(8, flyoutTop - Math.round(overflow));
                sync();
            }
        }
    }

    document.addEventListener('click', function (e) {
        var target = e.target;
        if (!target.closest) {
            return;
        }
        var header = target.closest('.nav-section-header');
        if (header) {
            if (isRail()) {
                toggleFlyout(header);
            } else {
                var id = header.dataset.section;
                if (collapsedSections.has(id)) {
                    collapsedSections.delete(id);
                } else {
                    collapsedSections.add(id);
                }
                sync();
            }
            return;
        }
        // A flyout link navigates (Dash handles the href) and the flyout closes with it;
        // a click anywhere outside the flyout closes it too.
        if (openFlyout !== null && !target.closest('.nav-section-links')) {
            openFlyout = null;
            sync();
        } else if (openFlyout !== null && target.closest('.nav-menu-item')) {
            openFlyout = null;
            sync();
        }
    });

    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape' || openFlyout === null) {
            return;
        }
        var button = document.querySelector('.nav-section-header[data-section="' + safeId(openFlyout) + '"]');
        openFlyout = null;
        sync();
        if (button) {
            button.focus();
        }
    });

    // The menu is replaced by callbacks, and the dashboard itself appears after login.
    new MutationObserver(schedule).observe(document.documentElement, {childList: true, subtree: true});
    schedule();
})();
