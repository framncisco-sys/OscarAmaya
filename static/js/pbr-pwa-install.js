/**
 * PWA: botón «Instalar app» (Chrome/Android) + guía elegante en iOS.
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

  function isIos() {
    return (
      /iPad|iPhone|iPod/.test(navigator.userAgent) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
    );
  }

  var deferred = null;
  var modalEl = null;

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

  function ensureModal() {
    if (modalEl) return modalEl;
    modalEl = document.createElement("div");
    modalEl.className = "pbr-install-modal";
    modalEl.hidden = true;
    modalEl.setAttribute("role", "dialog");
    modalEl.setAttribute("aria-modal", "true");
    modalEl.setAttribute("aria-labelledby", "pbr-install-modal-title");
    modalEl.innerHTML =
      '<div class="pbr-install-modal__backdrop" data-pbr-install-close></div>' +
      '<div class="pbr-install-modal__card">' +
      '  <button type="button" class="pbr-install-modal__x" data-pbr-install-close aria-label="Cerrar">×</button>' +
      '  <div class="pbr-install-modal__badge" aria-hidden="true">' +
      '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v12"/><path d="M8 11l4 4 4-4"/><path d="M5 19h14"/></svg>' +
      "  </div>" +
      '  <p class="pbr-install-modal__kicker">Paredes Desarrollos</p>' +
      '  <h2 id="pbr-install-modal-title" class="pbr-install-modal__title">Instalar en su iPhone</h2>' +
      '  <p class="pbr-install-modal__lead" data-pbr-install-lead></p>' +
      '  <ol class="pbr-install-modal__steps">' +
      "    <li><span>1</span> Toque <strong>Compartir</strong> en Safari (cuadro con flecha ↑).</li>" +
      "    <li><span>2</span> Elija <strong>Añadir a pantalla de inicio</strong>.</li>" +
      "    <li><span>3</span> Confirme con <strong>Añadir</strong>.</li>" +
      "  </ol>" +
      '  <div class="pbr-install-modal__actions">' +
      '    <button type="button" class="pbr-install-modal__btn" data-pbr-install-close>Entendido</button>' +
      "  </div>" +
      "</div>";
    document.body.appendChild(modalEl);
    modalEl.addEventListener("click", function (ev) {
      if (ev.target && ev.target.closest("[data-pbr-install-close]")) {
        closeModal();
      }
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && modalEl && !modalEl.hidden) closeModal();
    });
    return modalEl;
  }

  function openIosGuide(tip) {
    var el = ensureModal();
    var lead = el.querySelector("[data-pbr-install-lead]");
    if (lead) {
      lead.textContent =
        tip ||
        "En iPhone/iPad: toque Compartir y luego «Añadir a pantalla de inicio».";
    }
    el.hidden = false;
    document.body.classList.add("pbr-install-modal-open");
    var btn = el.querySelector(".pbr-install-modal__btn");
    if (btn) btn.focus();
  }

  function closeModal() {
    if (!modalEl) return;
    modalEl.hidden = true;
    document.body.classList.remove("pbr-install-modal-open");
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
      openIosGuide(btn.getAttribute("data-pbr-install-tip"));
      return;
    }
    deferred.prompt();
    deferred.userChoice.finally(function () {
      deferred = null;
      hideButtons();
    });
  });

  document.addEventListener("DOMContentLoaded", function () {
    if (isIos() && !isStandalone()) {
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
