/**
 * PWA: botón «Instalar app» (Chrome/Android beforeinstallprompt).
 * Oculto si ya corre en display-mode standalone o no hay prompt.
 */
(function () {
  "use strict";

  function isStandalone() {
    try {
      if (window.matchMedia("(display-mode: standalone)").matches) return true;
      if (window.navigator.standalone === true) return true;
    } catch (e) {}
    return false;
  }

  var deferred = null;

  function hideButtons() {
    document.querySelectorAll("[data-pbr-install]").forEach(function (el) {
      el.hidden = true;
    });
  }

  function showButtons() {
    if (isStandalone()) {
      hideButtons();
      return;
    }
    document.querySelectorAll("[data-pbr-install]").forEach(function (el) {
      el.hidden = false;
    });
  }

  if (isStandalone()) {
    document.addEventListener("DOMContentLoaded", hideButtons);
    return;
  }

  window.addEventListener("beforeinstallprompt", function (ev) {
    ev.preventDefault();
    deferred = ev;
    showButtons();
  });

  window.addEventListener("appinstalled", function () {
    deferred = null;
    hideButtons();
  });

  document.addEventListener("click", function (ev) {
    var btn = ev.target && ev.target.closest("[data-pbr-install]");
    if (!btn) return;
    ev.preventDefault();
    if (!deferred) {
      /* iOS / sin prompt: instrucción breve */
      var tip = btn.getAttribute("data-pbr-install-tip");
      if (tip) window.alert(tip);
      return;
    }
    deferred.prompt();
    deferred.userChoice.finally(function () {
      deferred = null;
      hideButtons();
    });
  });

  document.addEventListener("DOMContentLoaded", function () {
    /* En iOS Safari no hay beforeinstallprompt: mostrar tip de «Añadir a inicio» */
    var ios =
      /iPad|iPhone|iPod/.test(navigator.userAgent) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    if (ios && !isStandalone()) {
      document.querySelectorAll("[data-pbr-install]").forEach(function (el) {
        el.hidden = false;
        if (!el.getAttribute("data-pbr-install-tip")) {
          el.setAttribute(
            "data-pbr-install-tip",
            "En iPhone/iPad: toque Compartir y luego «Añadir a pantalla de inicio»."
          );
        }
      });
    }
  });
})();
