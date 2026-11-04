/**
 * Reportes > Reportabilidad: acciones de los elementos que Dash redibuja con cada filtro.
 *
 * Fichas, tarjetas, filas de la lista, botones del visor, cabeceras de la tabla y paginador
 * se recrean en cada render, asi que no llevan n_clicks (un elemento nuevo parte en 0 y
 * dispararia el callback sin clic). Llevan `data-rp="<accion>"` mas sus datos
 * (`data-rp-key`, `-ctx`, `-col`, `-page`, `-state`) y este script, delegado en document,
 * deja la accion en el Store `reporting-action`; dashboard/callbacks/reporting_callbacks.py
 * decide que hacer con ella.
 *
 * Las tarjetas y fichas son <a href="...?report=<clave>">: un clic normal abre el informe en
 * la pagina (preventDefault + accion); Ctrl/Cmd/Shift/Alt + clic, o el boton central, dejan
 * al navegador abrir el enlace. Si Dash no expone set_props, el enlace funciona igual.
 *
 * Foco: al redibujar se pierde el elemento pulsado, asi que se devuelve el foco al que lo
 * reemplaza (`data-rp-focus` es su identidad estable); al abrir un informe va al titulo del
 * informe y al cerrarlo, a la pestaña activa.
 */
(function () {
    var FOCUS_WAIT_MS = 1500;
    var FOCUS_POLL_MS = 50;

    function payload(el) {
        var d = el.dataset;
        return {
            type: d.rp,
            key: d.rpKey,
            ctx: d.rpCtx,
            col: d.rpCol,
            page: d.rpPage,
            state: d.rpState,
            nonce: Date.now() + Math.random()
        };
    }

    function focusWhenReady(find, original) {
        var waited = 0;
        var timer = setInterval(function () {
            waited += FOCUS_POLL_MS;
            var replaced = !original || !original.isConnected || original.offsetParent === null;
            var target = replaced ? find() : null;
            if (target && !target.disabled && target.offsetParent !== null) {
                clearInterval(timer);
                target.focus({ preventScroll: false });
            } else if (waited >= FOCUS_WAIT_MS) {
                clearInterval(timer);
            }
        }, FOCUS_POLL_MS);
    }

    function restoreFocus(el, action) {
        var token = el.getAttribute('data-rp-focus');
        if (action === 'close') {
            focusWhenReady(function () { return document.querySelector('#reporting-body .rp-tab--on'); }, null);
            return;
        }
        var heading = function () { return document.querySelector('#reporting-viewer .rp-report__unit'); };
        if (!token) {
            if (action === 'open') {
                focusWhenReady(heading, el);
            }
            return;
        }
        focusWhenReady(function () {
            var next = document.querySelector('[data-rp-focus="' + token.replace(/"/g, '\\"') + '"]');
            return next && !next.disabled ? next : heading();
        }, el);
    }

    document.addEventListener('click', function (event) {
        if (event.defaultPrevented || event.button !== 0) {
            return;
        }
        var el = event.target.closest ? event.target.closest('[data-rp]') : null;
        if (!el || el.disabled) {
            return;
        }
        var setProps = window.dash_clientside && window.dash_clientside.set_props;
        if (!setProps) {
            return;  // sin set_props los enlaces siguen funcionando por su href
        }
        if (el.tagName === 'A' && (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)) {
            return;
        }
        event.preventDefault();
        var data = payload(el);
        setProps('reporting-action', { data: data });
        restoreFocus(el, data.type);
    });
})();
