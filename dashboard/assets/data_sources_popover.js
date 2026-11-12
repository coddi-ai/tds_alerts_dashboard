/**
 * "Fuentes de Datos" popover (`render_data_sources` in dashboard/components/data_sources.py).
 *
 * The trigger is a real <button class="ds-trigger" aria-haspopup="dialog" aria-expanded>; the
 * popover is the sibling `.ds-popover` (role="dialog"). Click on the trigger toggles it; the
 * close button, Escape and a click outside close it. On close the focus returns to the trigger
 * (after an outside click only if the click did not move focus to something else). The popover
 * is nudged back inside the viewport on narrow screens through --ds-shift.
 *
 * Listeners are delegated on document, so they survive the page content being re-rendered by a
 * Dash callback (a new client re-renders the component; a fresh one starts closed).
 */
(function () {
    var GUTTER = 16;

    function wrapOf(node) {
        return node && node.closest ? node.closest('.ds') : null;
    }

    function parts(wrap) {
        return {
            trigger: wrap.querySelector('.ds-trigger'),
            popover: wrap.querySelector('.ds-popover'),
        };
    }

    function isOpen(wrap) {
        var p = parts(wrap);
        return !!p.popover && !p.popover.hidden;
    }

    function place(wrap) {
        var popover = parts(wrap).popover;
        popover.style.setProperty('--ds-shift', '0px');
        var rect = popover.getBoundingClientRect();
        var viewport = document.documentElement.clientWidth;
        var shift = 0;
        if (rect.left < GUTTER) {
            shift = GUTTER - rect.left;
        } else if (rect.right > viewport - GUTTER) {
            shift = viewport - GUTTER - rect.right;
        }
        popover.style.setProperty('--ds-shift', shift + 'px');
    }

    function close(wrap, returnFocus) {
        var p = parts(wrap);
        if (!p.popover || p.popover.hidden) {
            return;
        }
        p.popover.hidden = true;
        p.trigger.setAttribute('aria-expanded', 'false');
        if (returnFocus) {
            p.trigger.focus();
        }
    }

    function closeAll(except, returnFocus) {
        document.querySelectorAll('.ds').forEach(function (wrap) {
            if (wrap !== except) {
                close(wrap, returnFocus);
            }
        });
    }

    function open(wrap) {
        closeAll(wrap, false);
        var p = parts(wrap);
        p.popover.hidden = false;
        p.trigger.setAttribute('aria-expanded', 'true');
        place(wrap);
        // Focus enters the dialog so its title is announced; Tab then reaches the close button.
        p.popover.focus({ preventScroll: true });
    }

    document.addEventListener('click', function (event) {
        var target = event.target;
        var trigger = target.closest ? target.closest('.ds-trigger') : null;
        if (trigger) {
            var wrap = wrapOf(trigger);
            if (isOpen(wrap)) {
                close(wrap, true);
            } else {
                open(wrap);
            }
            return;
        }
        var closeButton = target.closest ? target.closest('.ds-close') : null;
        if (closeButton) {
            close(wrapOf(closeButton), true);
            return;
        }
        document.querySelectorAll('.ds').forEach(function (wrap) {
            if (isOpen(wrap) && !wrap.contains(target)) {
                close(wrap, false);
                var active = document.activeElement;
                if (!active || active === document.body) {
                    parts(wrap).trigger.focus();
                }
            }
        });
    });

    document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape' && event.key !== 'Esc') {
            return;
        }
        document.querySelectorAll('.ds').forEach(function (wrap) {
            if (isOpen(wrap)) {
                event.stopPropagation();
                close(wrap, true);
            }
        });
    });

    window.addEventListener('resize', function () {
        document.querySelectorAll('.ds').forEach(function (wrap) {
            if (isOpen(wrap)) {
                place(wrap);
            }
        });
    });
})();
