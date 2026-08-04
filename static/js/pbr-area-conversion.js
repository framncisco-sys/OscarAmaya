/**
 * Conversión automática: varas cuadradas → m² en formularios de inmueble.
 * 1 v² ≈ 0.698896 m²
 */
(function () {
  var M2_POR_V2 = 0.698896;

  function strip(s) {
    return String(s || "")
      .trim()
      .replace(/\s/g, "")
      .replace(/\$/g, "")
      .replace(/\u00a0/g, "");
  }

  function parseNum(s) {
    s = strip(s);
    if (!s) return NaN;
    if (s.indexOf(",") >= 0 && s.indexOf(".") >= 0) {
      if (s.lastIndexOf(",") > s.lastIndexOf(".")) {
        s = s.replace(/\./g, "").replace(",", ".");
      } else {
        s = s.replace(/,/g, "");
      }
    } else if (s.indexOf(",") >= 0) {
      var parts = s.split(",");
      if (parts.length === 2 && /^\d{1,4}$/.test(parts[1])) {
        s = parts[0].replace(/\./g, "") + "." + parts[1];
      } else {
        s = s.replace(/,/g, "");
      }
    }
    var n = parseFloat(s);
    return isFinite(n) ? n : NaN;
  }

  function formatUS(n, decimals) {
    if (!isFinite(n)) return "";
    var fixed = n.toFixed(decimals);
    var parts = fixed.split(".");
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return parts.join(".");
  }

  function bind() {
    var v2 = document.getElementById("id_area_varas_cuadradas");
    var m2 = document.getElementById("id_area_m2");
    if (!v2 || !m2 || v2.dataset.pbrAreaBound === "1") return;
    v2.dataset.pbrAreaBound = "1";

    function syncFromVaras() {
      var n = parseNum(v2.value);
      if (!isFinite(n)) {
        if (!strip(v2.value)) m2.value = "";
        return;
      }
      m2.value = formatUS(n * M2_POR_V2, 4);
    }

    v2.addEventListener("input", syncFromVaras);
    v2.addEventListener("change", syncFromVaras);
    v2.addEventListener("blur", syncFromVaras);
    if (strip(v2.value)) syncFromVaras();
  }

  document.addEventListener("DOMContentLoaded", bind);
  window.pbrBindAreaConversion = bind;
})();
