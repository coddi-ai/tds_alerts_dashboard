/*
 * UI language preference (Español / English).
 *
 * The preference lives in the `app_language` cookie: it persists across visits and,
 * unlike a Dash store, it is sent with every request - so the server can render the
 * whole UI (layouts and callback outputs) in the right language. Missing or invalid
 * means Spanish, the default.
 *
 * Switching rewrites the cookie and reloads the page. The UI is built server-side, so
 * a reload is what re-renders every piece of static text; the URL is kept, so the
 * user stays on the same screen.
 */
(function () {
    var COOKIE = "app_language";
    var SUPPORTED = ["es", "en"];
    var DEFAULT = "es";
    var ONE_YEAR = 60 * 60 * 24 * 365;

    function readCookie() {
        var parts = document.cookie ? document.cookie.split("; ") : [];
        for (var i = 0; i < parts.length; i++) {
            var pair = parts[i].split("=");
            if (pair[0] === COOKIE) {
                return decodeURIComponent(pair.slice(1).join("="));
            }
        }
        return null;
    }

    function currentLanguage() {
        var value = (readCookie() || "").slice(0, 2).toLowerCase();
        return SUPPORTED.indexOf(value) >= 0 ? value : DEFAULT;
    }

    function setLanguage(language) {
        if (SUPPORTED.indexOf(language) < 0) {
            return;
        }
        document.cookie = COOKIE + "=" + language + "; path=/; max-age=" + ONE_YEAR + "; SameSite=Lax";
        window.location.reload();
    }

    // `messages` is written by /_i18n/messages.js (loaded before this asset); merge, don't replace.
    function translate(key, fallback, params) {
        var messages = (window.appI18n && window.appI18n.messages) || {};
        var text = Object.prototype.hasOwnProperty.call(messages, key) ? messages[key] : fallback;
        if (typeof text !== "string") {
            return text;
        }
        return text.replace(/\{(\w+)\}/g, function (match, name) {
            return params && Object.prototype.hasOwnProperty.call(params, name) ? params[name] : match;
        });
    }

    window.appI18n = Object.assign(window.appI18n || {}, {
        currentLanguage: currentLanguage,
        setLanguage: setLanguage,
        t: translate
    });
    document.documentElement.lang = currentLanguage();
})();
