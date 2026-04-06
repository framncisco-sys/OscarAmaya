(function () {
  function sync() {
    var sel = document.getElementById("id_tipo");
    if (!sel) return;
    var v = sel.value;
    var casa = v === "CASA_NUEVA" || v === "CASA_SEGUNDA";
    var nueva = v === "CASA_NUEVA";
    var segunda = v === "CASA_SEGUNDA";
    var panel = document.getElementById("inm-casa-panel");
    if (panel) {
      panel.style.display = casa ? "block" : "none";
    }
    document.querySelectorAll(".inm-casa-row").forEach(function (el) {
      if (!casa) {
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

  document.addEventListener("DOMContentLoaded", function () {
    var sel = document.getElementById("id_tipo");
    if (sel) sel.addEventListener("change", sync);
    sync();
  });
})();
