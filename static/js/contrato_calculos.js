(function () {
  "use strict";

  var IVA_TASA = 0.13;
  var MOD_SIN_FIN = "SIN_FINANCIAMIENTO";

  function num(el) {
    if (!el) return null;
    var v = String(el.value || "").replace(",", ".").trim();
    if (v === "") return null;
    var n = parseFloat(v);
    return isFinite(n) ? n : null;
  }

  function intOrNull(el) {
    if (!el || !el.value) return null;
    var n = parseInt(el.value, 10);
    return isFinite(n) ? n : null;
  }

  function pmt(precio, anos, tasaAnualPct, modalidad) {
    if (modalidad === MOD_SIN_FIN) return "";
    if (precio == null || anos == null) return "";
    var n = anos * 12;
    if (n <= 0) return "";
    var r = (tasaAnualPct != null ? tasaAnualPct : 0) / 100 / 12;
    var P = precio;
    if (r === 0) return (P / n).toFixed(2);
    var factor = Math.pow(1 + r, n);
    var pay = (P * r * factor) / (factor - 1);
    return pay.toFixed(2);
  }

  function formatMoney(s) {
    return s === "" ? "" : s;
  }

  function recalc() {
    var pf = num(document.getElementById("id_precio_final"));
    var plan = intOrNull(document.getElementById("id_plan_anos"));
    var tasa = num(document.getElementById("id_tasa_interes_anual"));
    var modSel = document.getElementById("id_modalidad_financiamiento");
    var modalidad = modSel ? modSel.value : "";
    var pct = num(document.getElementById("id_comision_porcentaje"));

    var elIva = document.getElementById("id_desglose_iva_monto");
    var elCuota = document.getElementById("id_cuota_mensual_estimada");
    var elCom = document.getElementById("id_comision_monto");

    if (elIva) {
      elIva.value =
        pf != null ? (Math.round(pf * IVA_TASA * 100) / 100).toFixed(2) : "";
    }
    if (elCuota) {
      elCuota.value = formatMoney(pmt(pf, plan, tasa, modalidad));
    }
    if (elCom) {
      elCom.value =
        pf != null && pct != null
          ? (Math.round((pf * pct) / 100 * 100) / 100).toFixed(2)
          : "";
    }
  }

  var ids = [
    "id_precio_final",
    "id_plan_anos",
    "id_tasa_interes_anual",
    "id_modalidad_financiamiento",
    "id_comision_porcentaje",
  ];

  function bind() {
    var i;
    var el;
    for (i = 0; i < ids.length; i++) {
      el = document.getElementById(ids[i]);
      if (el) {
        el.addEventListener("change", recalc);
        el.addEventListener("input", recalc);
      }
    }
    recalc();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
