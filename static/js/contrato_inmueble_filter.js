(function () {
  "use strict";
  var cfg = window.contratoInmuebleFiltros || {};
  var selProyecto = document.getElementById("filtro-proyecto-contrato");
  var selPoligono = document.getElementById("filtro-poligono-contrato");
  var selInmueble = document.getElementById("id_inmueble");
  if (!selInmueble || !selProyecto || !selPoligono) {
    return;
  }

  function proyectoMatch(opt) {
    var v = selProyecto.value;
    if (!v) return true;
    return opt.getAttribute("data-proyecto-id") === v;
  }

  function poligonoMatch(opt) {
    var v = selPoligono.value;
    if (!v) return true;
    return (opt.getAttribute("data-poligono-id") || "") === v;
  }

  function applyInmuebleFilter() {
    var firstVisible = null;
    var i;
    var opt;
    for (i = 0; i < selInmueble.options.length; i++) {
      opt = selInmueble.options[i];
      if (!opt.value) {
        opt.hidden = false;
        opt.disabled = false;
        continue;
      }
      var show = proyectoMatch(opt) && poligonoMatch(opt);
      // disabled es más compatible que hidden en algunos navegadores con <select>
      opt.hidden = !show;
      opt.disabled = !show;
      if (show && firstVisible === null) {
        firstVisible = opt;
      }
    }
    var cur = selInmueble.selectedOptions[0];
    if (cur && (cur.hidden || cur.disabled)) {
      selInmueble.value = firstVisible ? firstVisible.value : "";
    }
  }

  function refreshPoligonoOptions() {
    var pv = selProyecto.value;
    var i;
    var opt;
    for (i = 0; i < selPoligono.options.length; i++) {
      opt = selPoligono.options[i];
      if (!opt.value) {
        opt.hidden = false;
        opt.disabled = false;
        continue;
      }
      var pp = opt.getAttribute("data-proyecto-id");
      var hidePol = !!(pv && pp !== pv);
      opt.hidden = hidePol;
      opt.disabled = hidePol;
    }
    var cur = selPoligono.selectedOptions[0];
    if (cur && cur.hidden) {
      selPoligono.value = "";
    }
    applyInmuebleFilter();
  }

  selProyecto.addEventListener("change", refreshPoligonoOptions);
  selPoligono.addEventListener("change", applyInmuebleFilter);

  // Nuevo contrato: asegurar filtros en "Todos" para no ocultar lotes por valores previos del navegador.
  if (!cfg.proyectoInicial) {
    selProyecto.value = "";
  }
  if (!cfg.poligonoInicial) {
    selPoligono.value = "";
  }

  if (cfg.proyectoInicial) {
    selProyecto.value = cfg.proyectoInicial;
  }
  refreshPoligonoOptions();
  if (cfg.poligonoInicial) {
    selPoligono.value = cfg.poligonoInicial;
    applyInmuebleFilter();
  }
})();
