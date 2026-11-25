/* Runtime theme colours: read CSS custom properties (cached), fall back to tokens.js. */
(function () {
  "use strict";

  const cache = new Map();
  const listeners = new Set();
  let watching = false;

  function theme() {
    return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  }

  function invalidate() {
    cache.clear();
    for (const fn of listeners) {
      try {
        fn();
      } catch (err) {
        console.error(err);
      }
    }
  }

  function css(token) {
    const key = token.startsWith("--") ? token : `--${token}`;
    if (cache.has(key)) return cache.get(key);
    const value = getComputedStyle(document.documentElement).getPropertyValue(key).trim();
    cache.set(key, value);
    return value;
  }

  function semantic(name) {
    const fromCss = css(name);
    if (fromCss) return fromCss;
    const table = typeof SEMANTIC !== "undefined" ? SEMANTIC[theme()] : null;
    return (table && table[name]) || "";
  }

  function chart(name) {
    const bare = name.startsWith("chart-") ? name.slice("chart-".length) : name;
    const fromCss = css(`chart-${bare}`);
    if (fromCss) return fromCss;
    const table = typeof CHART !== "undefined" ? CHART[theme()] : null;
    return (table && table[bare]) || "";
  }

  function onChange(fn) {
    listeners.add(fn);
  }

  function watch() {
    if (watching) return;
    watching = true;
    new MutationObserver((mutations) => {
      for (const m of mutations) {
        if (m.attributeName === "data-theme") {
          invalidate();
          return;
        }
      }
    }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  }

  window.ResiliTheme = { theme, semantic, chart, css, invalidate, onChange, watch };
})();
