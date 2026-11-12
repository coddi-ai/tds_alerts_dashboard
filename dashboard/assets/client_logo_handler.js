/**
 * Client logo fallback.
 *
 * The top bar shows the current client's logo (#client-logo-img, set by update_client_logo).
 * If the image cannot be loaded, the wrapper switches to data-logo-state="fallback" and the
 * CSS shows the bordered initials placeholder in its place - never a broken image or a gap.
 * A successful load switches it back.
 *
 * `error` and `load` do not bubble, so they are caught in the capture phase on document: that
 * works for an image Dash creates or re-sources at any time, with no per-element wiring.
 */
(function () {
    function onImageEvent(state) {
        return function (event) {
            var img = event.target;
            if (!img || img.id !== 'client-logo-img') {
                return;
            }
            // An empty src (no client yet) can raise `error`; that is not a missing asset.
            if (state === 'fallback' && !img.getAttribute('src')) {
                return;
            }
            var wrap = img.closest('.topbar-client-logo-wrap');
            if (wrap) {
                wrap.setAttribute('data-logo-state', state);
            }
        };
    }

    document.addEventListener('error', onImageEvent('fallback'), true);
    document.addEventListener('load', onImageEvent('loaded'), true);
})();
