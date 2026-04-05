/**
 * Inmueble: modo Lotificación / Casa / Alquiler → secciones + filtro de tipo;
 * geolocalización y galería (arrastrar/soltar).
 */
(function () {
  "use strict";

  function splitTok(s) {
    return (s || "").trim().split(/\s+/).filter(Boolean);
  }

  function matchesDyn(el, modo, tipo) {
    var dm = el.getAttribute("data-show-modo");
    var dt = el.getAttribute("data-show-tipos");
    var ms = dm ? splitTok(dm) : [];
    var ts = dt ? splitTok(dt) : [];
    if (ms.length && ms.indexOf(modo) < 0) return false;
    if (ts.length && ts.indexOf(tipo) < 0) return false;
    return true;
  }

  function filterTipoPorModo(selModo, tipoSelect) {
    if (!selModo || !tipoSelect) return;
    var modo = selModo.value || "LOTIFICACION";
    var firstVis = null;
    Array.prototype.forEach.call(tipoSelect.options, function (opt) {
      if (!opt.value) {
        opt.hidden = false;
        return;
      }
      var mods = splitTok(opt.getAttribute("data-modos"));
      var ok = mods.indexOf(modo) >= 0;
      opt.hidden = !ok;
      if (ok && !firstVis) firstVis = opt;
    });
    var selOpt = tipoSelect.selectedOptions[0];
    if (selOpt && selOpt.hidden && firstVis) {
      tipoSelect.value = firstVis.value;
    }
  }

  function refreshAll(selModo, selTipo) {
    var modo = selModo && selModo.value ? selModo.value : "LOTIFICACION";
    filterTipoPorModo(selModo, selTipo);
    var tipo = selTipo && selTipo.value ? selTipo.value : "";
    var q =
      ".inmueble-sec[data-show-modo], .inmueble-sec[data-show-tipos], " +
      "h2.inmueble-sec-title[data-show-modo], h2.inmueble-sec-title[data-show-tipos], " +
      "p.inmueble-dyn[data-show-modo]";
    document.querySelectorAll(q).forEach(function (el) {
      if (matchesDyn(el, modo, tipo)) el.classList.add("is-visible");
      else el.classList.remove("is-visible");
    });
  }

  function syncPortadaHidden() {
    var hidden = document.getElementById("inmueble-portada-val");
    if (!hidden) return;
    var input = document.getElementById("inmueble-galeria-input");
    var n = input && input.files ? input.files.length : 0;
    if (n > 0) {
      var idx = parseInt(hidden.getAttribute("data-nueva-idx") || "0", 10) || 0;
      if (idx < 0 || idx >= n) idx = 0;
      hidden.value = "nueva:" + idx;
      return;
    }
    var pick = document.querySelector("input[name='imagen_portada_pick']:checked");
    if (pick) hidden.value = pick.value;
    else hidden.value = "";
  }

  document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("inmueble-form-main");
    var selModo = document.getElementById("id_modo_catalogo");
    var selTipo = document.getElementById("id_tipo");

    function runRefresh() {
      refreshAll(selModo, selTipo);
    }
    if (selModo) selModo.addEventListener("change", runRefresh);
    if (selTipo) selTipo.addEventListener("change", runRefresh);
    runRefresh();

    var btnGeo = document.getElementById("inmueble-btn-geo");
    var latEl = document.getElementById("id_latitud");
    var lonEl = document.getElementById("id_longitud");
    if (btnGeo && latEl && lonEl && navigator.geolocation) {
      btnGeo.addEventListener("click", function () {
        btnGeo.disabled = true;
        navigator.geolocation.getCurrentPosition(
          function (pos) {
            latEl.value = pos.coords.latitude.toFixed(6);
            lonEl.value = pos.coords.longitude.toFixed(6);
            btnGeo.disabled = false;
          },
          function () {
            btnGeo.disabled = false;
            alert("No se pudo obtener la ubicación. Revise permisos del navegador.");
          },
          { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 }
        );
      });
    } else if (btnGeo && (!navigator.geolocation || !latEl || !lonEl)) {
      btnGeo.style.display = "none";
    }

    var drop = document.getElementById("inmueble-galeria-drop");
    var input = document.getElementById("inmueble-galeria-input");
    var prev = document.getElementById("inmueble-galeria-prev");
    var hidden = document.getElementById("inmueble-portada-val");
    var hint = document.getElementById("inmueble-galeria-portada-hint");

    function renderNombresArchivos() {
      if (!input || !prev) return;
      prev.innerHTML = "";
      var files = input.files;
      if (!files || !files.length) {
        if (hint) hint.style.display = "none";
        syncPortadaHidden();
        return;
      }
      var i;
      for (i = 0; i < files.length; i += 1) {
        var sp = document.createElement("span");
        sp.textContent = files[i].name;
        prev.appendChild(sp);
      }
      if (hint && hidden) {
        hint.style.display = "";
        hint.innerHTML =
          "Portada entre las <strong>nuevas</strong> fotos: elija el índice (0 = primera). " +
          "<label class='muted'>Índice <input type='number' id='inmueble-nueva-portada-idx' min='0' max='" +
          (files.length - 1) +
          "' value='0' style='width:3.5rem;margin-left:0.25rem;' /></label>";
        var num = document.getElementById("inmueble-nueva-portada-idx");
        if (num) {
          num.addEventListener("input", function () {
            var v = parseInt(num.value, 10);
            if (!isFinite(v) || v < 0) v = 0;
            if (v >= files.length) v = files.length - 1;
            hidden.setAttribute("data-nueva-idx", String(v));
            syncPortadaHidden();
          });
          hidden.setAttribute("data-nueva-idx", "0");
        }
      }
      syncPortadaHidden();
    }

    if (drop && input) {
      drop.addEventListener("click", function () {
        input.click();
      });
      drop.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          input.click();
        }
      });
      ["dragenter", "dragover"].forEach(function (ev) {
        drop.addEventListener(ev, function (e) {
          e.preventDefault();
          drop.classList.add("is-dragover");
        });
      });
      ["dragleave", "drop"].forEach(function (ev) {
        drop.addEventListener(ev, function (e) {
          e.preventDefault();
          drop.classList.remove("is-dragover");
        });
      });
      drop.addEventListener("drop", function (e) {
        var dt = e.dataTransfer;
        if (!dt || !dt.files || !dt.files.length) return;
        input.files = dt.files;
        renderNombresArchivos();
      });
      input.addEventListener("change", renderNombresArchivos);
    }

    document.querySelectorAll("input.inmueble-pick-portada").forEach(function (r) {
      r.addEventListener("change", syncPortadaHidden);
    });

    if (form) {
      form.addEventListener("submit", function () {
        syncPortadaHidden();
      });
    }

    syncPortadaHidden();
  });
})();
