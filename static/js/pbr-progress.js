/**
 * Barra de progreso global del sistema (navegación, formularios, fetch).
 * window.pbrProgress.start(label?) / set(n) / done(force?)
 */
(function () {
  "use strict";

  var root = document.getElementById("pbr-top-progress");
  var bar = document.getElementById("pbr-top-progress-bar");
  var labelEl = document.getElementById("pbr-top-progress-label");
  if (!root || !bar) return;

  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var active = false;
  var progress = 0;
  var trickleTimer = null;
  var hideTimer = null;
  var pending = 0;

  function clamp(n) {
    return Math.min(100, Math.max(0, n));
  }

  function render() {
    bar.style.width = progress + "%";
    root.classList.toggle("is-active", active);
    root.setAttribute("aria-hidden", active ? "false" : "true");
    if (labelEl) {
      var txt = labelEl.textContent || "";
      labelEl.hidden = !active || !txt;
    }
  }

  function clearTimers() {
    if (trickleTimer) {
      window.clearInterval(trickleTimer);
      trickleTimer = null;
    }
    if (hideTimer) {
      window.clearTimeout(hideTimer);
      hideTimer = null;
    }
  }

  function trickle() {
    if (!active) return;
    if (progress >= 92) return;
    var inc = progress < 30 ? 8 : progress < 60 ? 4 : progress < 85 ? 2 : 0.6;
    progress = clamp(progress + inc * (reduce ? 1.8 : 1));
    render();
  }

  function start(label) {
    pending += 1;
    clearTimers();
    active = true;
    if (typeof label === "string" && labelEl) {
      labelEl.textContent = label;
    }
    if (progress < 8 || progress >= 100) progress = 8;
    render();
    if (!reduce) {
      trickleTimer = window.setInterval(trickle, 420);
    }
  }

  function set(n) {
    if (!active) start("");
    progress = clamp(typeof n === "number" ? n : progress);
    render();
  }

  function done(force) {
    pending = Math.max(0, pending - 1);
    if (!force && pending > 0) return;
    pending = 0;
    clearTimers();
    progress = 100;
    render();
    root.classList.add("is-complete");
    hideTimer = window.setTimeout(function () {
      active = false;
      progress = 0;
      root.classList.remove("is-complete");
      if (labelEl) labelEl.textContent = "";
      render();
    }, reduce ? 160 : 380);
  }

  function sameOrigin(href) {
    try {
      var u = new URL(href, window.location.href);
      return u.origin === window.location.origin;
    } catch (e) {
      return false;
    }
  }

  function shouldSkipLink(a) {
    if (!a || !a.href) return true;
    if (a.target === "_blank" || a.hasAttribute("download")) return true;
    if (a.getAttribute("data-pbr-progress") === "skip") return true;
    if (a.getAttribute("data-pbr-offline") === "skip") return true;
    var href = a.getAttribute("href") || "";
    if (!href || href.charAt(0) === "#") return true;
    if (/^(mailto:|tel:|javascript:)/i.test(href)) return true;
    if (!sameOrigin(a.href)) return true;
    return false;
  }

  function shouldSkipForm(form) {
    if (!form) return true;
    if (form.getAttribute("data-pbr-progress") === "skip") return true;
    if (form.getAttribute("data-pbr-offline") === "skip") return true;
    if ((form.getAttribute("target") || "").toLowerCase() === "_blank") return true;
    return false;
  }

  document.addEventListener(
    "click",
    function (ev) {
      var a = ev.target && ev.target.closest ? ev.target.closest("a[href]") : null;
      if (!a || shouldSkipLink(a)) return;
      if (ev.defaultPrevented) return;
      if (ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
      start("Cargando página…");
    },
    true
  );

  document.addEventListener(
    "submit",
    function (ev) {
      var form = ev.target;
      if (!form || form.tagName !== "FORM") return;
      if (shouldSkipForm(form)) return;
      if (ev.defaultPrevented) return;
      var label = form.getAttribute("data-pbr-progress-label") || "Guardando…";
      start(label);
    },
    true
  );

  window.addEventListener("pageshow", function (ev) {
    if (ev.persisted) done(true);
  });

  window.addEventListener("load", function () {
    if (active) done(true);
  });

  if (window.fetch) {
    var nativeFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
      init = init || {};
      var method = (
        (init.method || (typeof input === "object" && input.method) || "GET")
      ).toUpperCase();
      var url = typeof input === "string" ? input : (input && input.url) || "";
      var isMutating = method !== "GET" && method !== "HEAD";
      var skip = false;
      if (init.headers) {
        if (init.headers["X-PBR-Progress"] === "skip") skip = true;
        if (init.headers.get && init.headers.get("X-PBR-Progress") === "skip") skip = true;
      }
      if (isMutating && !skip) start("Procesando…");
      return nativeFetch(input, init)
        .then(function (res) {
          if (isMutating && !skip) done();
          return res;
        })
        .catch(function (err) {
          if (isMutating && !skip) done(true);
          throw err;
        });
    };
  }

  window.pbrProgress = {
    start: start,
    set: set,
    done: done,
    isActive: function () {
      return active;
    },
  };
})();
