/**
 * Formato US en inputs: miles con coma, decimales con punto.
 * .input-monto-us / .input-monto-us--symbol → $25,136.72
 * .input-numero-us → 1,234.5678
 */
(function () {
  function stripMoney(s) {
    return String(s || "")
      .trim()
      .replace(/\s/g, "")
      .replace(/\$/g, "")
      .replace(/\u00a0/g, "");
  }

  function normalizeToDot(s) {
    s = stripMoney(s);
    if (!s) return "";
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
    return s;
  }

  function parseNum(s) {
    var n = parseFloat(normalizeToDot(s));
    return isFinite(n) ? n : NaN;
  }

  function formatUS(n, decimals, withSymbol) {
    if (!isFinite(n)) return "";
    var d = Math.max(0, Math.min(8, decimals | 0));
    var fixed = n.toFixed(d);
    var parts = fixed.split(".");
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    var out = parts.join(".");
    return withSymbol ? "$" + out : out;
  }

  function bind(el) {
    if (!el || el.dataset.pbrMoneyBound === "1") return;
    el.dataset.pbrMoneyBound = "1";
    var isMoney = el.classList.contains("input-monto-us");
    var withSymbol = el.classList.contains("input-monto-us--symbol");
    var decimals = isMoney ? 2 : parseInt(el.getAttribute("data-decimals") || "4", 10);
    if (!isFinite(decimals)) decimals = isMoney ? 2 : 4;

    function reformat() {
      var n = parseNum(el.value);
      if (!isFinite(n)) return;
      el.value = formatUS(n, decimals, isMoney && withSymbol);
    }

    el.addEventListener("blur", reformat);
    el.addEventListener("change", reformat);
    // Al enfocar, dejar editable sin forzar; al salir se formatea.
    if (el.value) reformat();
  }

  function scan(root) {
    var scope = root || document;
    scope.querySelectorAll(".input-monto-us, .input-numero-us").forEach(bind);
  }

  document.addEventListener("DOMContentLoaded", function () {
    scan(document);
  });
  window.pbrBindMoneyInputs = scan;
})();
