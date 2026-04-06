(function () {
  function applyRows(v) {
    var nueva = v === "CASA_NUEVA";
    var segunda = v === "CASA_SEGUNDA";
    var panel = document.getElementById("inm-casa-panel");
    if (panel) {
      panel.style.display = nueva || segunda ? "block" : "none";
    }
    document.querySelectorAll(".inm-casa-row").forEach(function (el) {
      if (!nueva && !segunda) {
        el.style.display = "none";
        return;
      }
      var sub = el.getAttribute("data-inm-casa-sub");
      if (sub === "nueva") {
        el.style.display = nueva ? "" : "none";
      } else if (sub === "segunda") {
        el.style.display = segunda ? "" : "none";
      } else {
        el.style.display = "";
      }
    });
  }

  function sync() {
    var solo = document.getElementById("inm-casa-only-page");
    if (solo) {
      applyRows(solo.getAttribute("data-tipo") || "");
      return;
    }
    var sel = document.getElementById("id_tipo");
    if (!sel) return;
    applyRows(sel.value);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var sel = document.getElementById("id_tipo");
    if (sel) sel.addEventListener("change", sync);
    sync();
  });
})();
