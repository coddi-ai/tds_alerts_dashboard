/**
 * Explanation popover for status chips (`chip_button` in dashboard/components/fleet_overview.py).
 *
 * Every chip that carries an explanation is a <button data-tip="...">. The text shows while the
 * pointer is over it or it has keyboard focus, and click / Enter / Space pins it open; Escape
 * or a click elsewhere closes it. One popover element serves the whole page; listeners are
 * delegated on document, so they survive the page content being re-rendered.
 */
(function () {
    var popover = null;
    var current = null;   // button whose text is showing
    var pinned = false;   // opened by click / Enter / Space: stays until closed

    function ensurePopover() {
        if (!popover) {
            popover = document.createElement('div');
            popover.id = 'chip-popover';
            popover.setAttribute('role', 'tooltip');
            popover.hidden = true;
            document.body.appendChild(popover);
        }
        return popover;
    }

    function hide() {
        if (current) {
            current.removeAttribute('aria-describedby');
        }
        if (popover) {
            popover.hidden = true;
        }
        current = null;
        pinned = false;
    }

    function show(button) {
        var tip = button.getAttribute('data-tip');
        if (!tip) {
            return;
        }
        var box = ensurePopover();
        if (current && current !== button) {
            current.removeAttribute('aria-describedby');
        }
        box.textContent = tip;
        box.hidden = false;
        button.setAttribute('aria-describedby', 'chip-popover');
        var rect = button.getBoundingClientRect();
        var left = Math.min(Math.max(8, rect.left + window.scrollX), window.scrollX + document.documentElement.clientWidth - box.offsetWidth - 8);
        box.style.left = left + 'px';
        box.style.top = (rect.bottom + window.scrollY + 6) + 'px';
        current = button;
    }

    function chipOf(event) {
        return event.target.closest ? event.target.closest('[data-tip]') : null;
    }

    document.addEventListener('mouseover', function (e) {
        var button = chipOf(e);
        if (button && !pinned) {
            show(button);
        }
    });
    document.addEventListener('mouseout', function (e) {
        if (chipOf(e) && !pinned) {
            hide();
        }
    });
    document.addEventListener('focusin', function (e) {
        var button = chipOf(e);
        if (button && !pinned) {
            show(button);
        }
    });
    document.addEventListener('focusout', function (e) {
        if (chipOf(e) && !pinned) {
            hide();
        }
    });
    document.addEventListener('click', function (e) {
        var button = chipOf(e);
        if (!button) {
            hide();
            return;
        }
        if (pinned && current === button) {
            hide();
        } else {
            show(button);
            pinned = true;
        }
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            hide();
        }
    });
})();
