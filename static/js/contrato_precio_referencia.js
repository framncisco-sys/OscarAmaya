(function () {
  "use strict";
  var sel = document.getElementById("id_inmueble");
  var ref = document.getElementById("id_precio_lista_referencia");
  if (!sel || !ref) return;

  function aplicarPrecioLista() {
    var opt = sel.selectedOptions[0];
    if (!opt || !opt.value) return;
    var p = opt.getAttribute("data-precio-lista");
    if (!p) return;
    if (ref.value && String(ref.value).trim() !== "") return;
    ref.value = p;
  }

  sel.addEventListener("change", aplicarPrecioLista);
})();
