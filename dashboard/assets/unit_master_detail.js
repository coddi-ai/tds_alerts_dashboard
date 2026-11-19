/**
 * Unit Detail (Resumen > Unidad) - the unit list's browser-side behaviour.
 *
 * The page (dashboard/components/unit_summary.py) renders the whole list: every unit of the
 * fleet, grouped by Estado, as real links, plus the detail header with Anterior / "n / total" /
 * Siguiente. What is *shown* of that list is the user's: the search text filters it and each
 * group opens and closes. This script applies both, and points Anterior / Siguiente at the
 * neighbouring *shown* unit, so the buttons and the counter always describe what the list shows:
 *
 *   shown unit = matches the search AND sits in an open group
 *
 * - "n / total" is the selected unit's place among the shown units. When the selected unit is not
 *   one of them (filtered out, or its group is closed) it stays selected in the detail, the
 *   counter reads "– / total", and Anterior / Siguiente go to the nearest shown unit before /
 *   after it in list order.
 * - Anterior is disabled when nothing shown comes before the selected unit, Siguiente when
 *   nothing shown comes after it.
 *
 * Opening another unit rebuilds the page (Dash Pages re-runs the layout), so the search text and
 * the groups the user opened or closed are kept in sessionStorage and put back on every render.
 * Everything is delegated on `document` / found through a MutationObserver, since the nodes are
 * replaced on every navigation. Units are opened by clicking their own <a>, which is a dcc.Link:
 * it navigates through Dash's client-side router, so nothing reloads.
 */
(function () {
    var KEY_QUERY = 'unitListQuery';
    var KEY_CLOSED = 'unitListClosedGroups';
    var UNIT_PATH = '/overview/unit/';
    var SEARCH_ID = 'unit-list-search';

    function read(key) {
        try {
            return sessionStorage.getItem(key);
        } catch (e) {
            return null;
        }
    }

    function write(key, value) {
        try {
            if (value === null) {
                sessionStorage.removeItem(key);
            } else {
                sessionStorage.setItem(key, value);
            }
        } catch (e) {
            // sessionStorage unavailable (private mode, ...): the list still works for this render.
        }
    }

    function listNode() {
        return document.querySelector('[data-unit-list]');
    }

    function unitItems(list) {
        return Array.prototype.slice.call(list.querySelectorAll('[data-unit-item]'));
    }

    function groupOf(item) {
        return item.closest('[data-unit-group]');
    }

    function isOpen(group) {
        var toggle = group.querySelector('[data-unit-group-toggle]');
        return !!toggle && toggle.getAttribute('aria-expanded') === 'true';
    }

    function setOpen(group, open) {
        var toggle = group.querySelector('[data-unit-group-toggle]');
        var body = group.querySelector('.unit-group__items');
        if (!toggle || !body) {
            return;
        }
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        body.hidden = !open;
    }

    function searchBox(list) {
        return list.querySelector('#' + SEARCH_ID);
    }

    function query(list) {
        var input = searchBox(list);
        return input ? input.value.trim().toLowerCase() : '';
    }

    function matches(item, needle) {
        return needle === '' || item.getAttribute('data-unit-item').toLowerCase().indexOf(needle) !== -1;
    }

    /** Search: hide the units that do not match, and the groups with none; the group's count
     *  reads "matches/total" while searching. */
    function applySearch(list) {
        var needle = query(list);
        var anyMatch = false;
        list.querySelectorAll('[data-unit-group]').forEach(function (group) {
            var items = unitItems(group);
            var found = 0;
            items.forEach(function (item) {
                var match = matches(item, needle);
                item.hidden = !match;
                if (match) {
                    found += 1;
                }
            });
            var count = group.querySelector('[data-unit-group-count]');
            if (count) {
                count.textContent = '(' + (needle === '' ? items.length : found + '/' + items.length) + ')';
            }
            group.hidden = needle !== '' && found === 0;
            anyMatch = anyMatch || found > 0;
        });
        var empty = list.querySelector('[data-unit-no-match]');
        if (empty) {
            empty.hidden = needle === '' || anyMatch;
        }
    }

    function isShown(item) {
        var group = groupOf(item);
        return !item.hidden && !!group && !group.hidden && isOpen(group);
    }

    /** The unit Anterior / Siguiente open from the selected one, and the counter text. */
    function navigation(list) {
        var all = unitItems(list);
        var selected = list.getAttribute('data-unit-list');
        var selectedIndex = -1;
        all.forEach(function (item, index) {
            if (item.getAttribute('data-unit-item') === selected) {
                selectedIndex = index;
            }
        });
        var shown = all.filter(isShown);
        var position = selectedIndex === -1 ? -1 : shown.indexOf(all[selectedIndex]);
        var prev = null;
        var next = null;
        if (selectedIndex !== -1) {
            // Nearest shown unit on each side in list order: when the selected unit is itself
            // shown these are simply its neighbours among the shown ones.
            all.forEach(function (item, index) {
                if (isShown(item)) {
                    if (index < selectedIndex) {
                        prev = item;
                    } else if (index > selectedIndex && next === null) {
                        next = item;
                    }
                }
            });
        }
        return {prev: prev, next: next, position: position, total: shown.length};
    }

    function refresh(list) {
        var state = navigation(list);
        var buttons = {prev: state.prev, next: state.next};
        document.querySelectorAll('[data-unit-nav]').forEach(function (button) {
            var target = buttons[button.getAttribute('data-unit-nav')];
            button.disabled = !target;
            button._unitTarget = target || null;
        });
        var counter = document.querySelector('[data-unit-position]');
        if (counter) {
            var format = counter.getAttribute('data-unit-position-format') || '{n} / {total}';
            counter.textContent = format
                .replace('{n}', state.position === -1 ? '–' : String(state.position + 1))
                .replace('{total}', String(state.total));
        }
    }

    function closedGroups(list) {
        var closed = [];
        list.querySelectorAll('[data-unit-group]').forEach(function (group) {
            if (!isOpen(group)) {
                closed.push(group.getAttribute('data-unit-group'));
            }
        });
        return closed;
    }

    function scrollToSelected(list) {
        var container = list.querySelector('.unit-list__groups');
        var link = list.querySelector('.unit-item--selected');
        if (!container || !link || !link.offsetParent) {
            return;
        }
        var item = link.closest('[data-unit-item]');
        container.scrollTop = Math.max(0, item.offsetTop - container.clientHeight / 2);
    }

    function initialise(list) {
        list._unitReady = true;
        var input = searchBox(list);
        var stored_query = read(KEY_QUERY) || '';
        if (input && stored_query !== '') {
            // The box is a dcc.Input: tell Dash (its React state) as well as the element, or the
            // next render of it would put the empty value back.
            var setProps = window.dash_clientside && window.dash_clientside.set_props;
            if (setProps) {
                setProps(SEARCH_ID, {value: stored_query});
            }
            input.value = stored_query;
        }
        var stored = read(KEY_CLOSED);
        if (stored !== null) {
            var closed = [];
            try {
                closed = JSON.parse(stored);
            } catch (e) {
                closed = [];
            }
            list.querySelectorAll('[data-unit-group]').forEach(function (group) {
                setOpen(group, closed.indexOf(group.getAttribute('data-unit-group')) === -1);
            });
        }
        // Coming to a unit from outside the list (a fleet row, a link) must not leave it hidden
        // inside a group the user had closed before.
        var selected = list.querySelector('.unit-item--selected');
        if (selected) {
            selected.setAttribute('aria-current', 'page');
        }
        var selectedGroup = selected ? groupOf(selected) : null;
        if (selectedGroup && !isOpen(selectedGroup)) {
            setOpen(selectedGroup, true);
        }
        applySearch(list);
        refresh(list);
        scrollToSelected(list);
    }

    document.addEventListener('input', function (e) {
        var input = e.target.id === SEARCH_ID ? e.target : null;
        var list = input ? input.closest('[data-unit-list]') : null;
        if (!list) {
            return;
        }
        write(KEY_QUERY, input.value === '' ? null : input.value);
        applySearch(list);
        refresh(list);
    });

    document.addEventListener('click', function (e) {
        var toggle = e.target.closest ? e.target.closest('[data-unit-group-toggle]') : null;
        if (toggle) {
            var group = toggle.closest('[data-unit-group]');
            var list = toggle.closest('[data-unit-list]');
            setOpen(group, !isOpen(group));
            write(KEY_CLOSED, JSON.stringify(closedGroups(list)));
            refresh(list);
            return;
        }
        var button = e.target.closest ? e.target.closest('[data-unit-nav]') : null;
        if (button && !button.disabled && button._unitTarget) {
            // The item's own link: Dash's router handles it like any click on the list.
            var link = button._unitTarget.querySelector('a');
            if (link) {
                link.click();
            }
        }
    });

    /* The unit's alerts list: a click anywhere on a row opens that alert, through the row's own
     * "Ver Detalle" link. The link is a plain <a> inside the table, so its click would reload the
     * page; both it and the row go through Dash's router instead, like dcc.Link does. A click with
     * Ctrl / Cmd / Shift / Alt, or the middle button, is left to the browser (new tab / window). */
    function openThroughRouter(href) {
        window.history.pushState({}, '', href);
        window.dispatchEvent(new CustomEvent('_dashprivate_pushstate'));
        window.scrollTo(0, 0);
    }

    document.addEventListener('click', function (e) {
        var table = e.target.closest ? e.target.closest('[data-unit-alert-table]') : null;
        if (!table || e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) {
            return;
        }
        var link = e.target.closest('a[href]');
        var cell = e.target.closest('td');
        if (!link && cell) {
            var row = cell.closest('tr');
            link = row ? row.querySelector('a[href]') : null;
        }
        if (!link || !table.contains(link)) {
            return;
        }
        e.preventDefault();
        openThroughRouter(link.getAttribute('href'));
        // Captured, because the table's own cell handlers stop the click before it bubbles up here.
    }, true);

    var pending = false;
    new MutationObserver(function () {
        if (pending) {
            return;
        }
        pending = true;
        window.requestAnimationFrame(function () {
            pending = false;
            var list = listNode();
            if (list) {
                if (!list._unitReady) {
                    initialise(list);
                }
            } else if (window.location.pathname.indexOf(UNIT_PATH) === -1) {
                // Left the unit pages: the next visit starts with an empty search.
                write(KEY_QUERY, null);
            }
        });
    }).observe(document.documentElement, {childList: true, subtree: true});
})();
