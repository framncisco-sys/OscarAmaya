/**
 * Máscaras El Salvador: DUI 00000000-0, NIT 0000-000000-000-0, teléfono 0000-0000.
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

  function formatPhoneSV(el) {
    var d = digitsOnly(el.value);
    if (d.length >= 11 && d.slice(0, 3) === "503") {
      d = d.slice(3);
    }
    d = d.slice(0, 8);
    if (d.length <= 4) {
      el.value = d;
    } else {
      el.value = d.slice(0, 4) + "-" + d.slice(4, 8);
    }
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

    var phoneIds = [
      "id_telefono_domicilio",
      "id_telefono_notificacion",
      "id_telefono_trabajo",
      "id_ref_com_tel_1",
      "id_ref_com_tel_2",
      "id_ref_com_tel_3",
      "id_ref_per_tel_1",
      "id_ref_per_tel_2",
      "id_ref_per_tel_3",
    ];
    phoneIds.forEach(function (id) {
      bind(document.getElementById(id), formatPhoneSV);
    });
  });
})();
