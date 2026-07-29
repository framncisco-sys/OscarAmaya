/**
 * Máscaras El Salvador solo para DUI / NIT en formato de aceptación.
 * Teléfonos: ver static/js/pbr-tel-intl.js (toda la app).
 */
(function () {
  "use strict";

  function digitsOnly(s) {
    return String(s || "").replace(/\D/g, "");
  }

  function formatDUI(el) {
    var d = digitsOnly(el.value).slice(0, 9);
    if (d.length <= 8) {
      el.value = d;
    } else {
      el.value = d.slice(0, 8) + "-" + d.slice(8, 9);
    }
  }

  function formatNIT(el) {
    var d = digitsOnly(el.value).slice(0, 14);
    var p = [];
    if (d.length > 0) p.push(d.substring(0, Math.min(4, d.length)));
    if (d.length > 4) p.push(d.substring(4, Math.min(10, d.length)));
    if (d.length > 10) p.push(d.substring(10, Math.min(13, d.length)));
    if (d.length > 13) p.push(d.substring(13, 14));
    el.value = p.join("-");
  }

  function bind(el, fmt) {
    if (!el) return;
    el.addEventListener("input", function () {
      fmt(el);
    });
    el.addEventListener("blur", function () {
      fmt(el);
    });
    if (el.value) fmt(el);
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (!document.getElementById("formato-aceptacion-form")) return;
    bind(document.getElementById("id_dui_numero"), formatDUI);
    bind(document.getElementById("id_nit_numero"), formatNIT);
  });
})();
