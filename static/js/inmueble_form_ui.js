/**
 * Inmueble: secciones según tipo (lote / casa / local), geolocalización y galería (arrastrar/soltar).
 */
(function () {
  "use strict";

  function splitTipos(s) {
    return (s || "").trim().split(/\s+/).filter(Boolean);
  }

  function refreshSecciones() {
    var sel = document.getElementById("id_tipo");
    if (!sel) return;
    var t = sel.value || "";
    document.querySelectorAll(".inmueble-sec[data-show-tipos]").forEach(function (sec) {
      var tipos = splitTipos(sec.getAttribute("data-show-tipos"));
      var ok = tipos.indexOf(t) >= 0;
      sec.classList.toggle("is-visible", ok);
    });
    document.querySelectorAll("h2.inmueble-sec-title[data-show-tipos]").forEach(function (h) {
      var tipos = splitTipos(h.getAttribute("data-show-tipos"));
      h.style.display = tipos.indexOf(t) >= 0 ? "" : "none";
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
    var selTipo = document.getElementById("id_tipo");
    if (selTipo) {
      selTipo.addEventListener("change", refreshSecciones);
      refreshSecciones();
    }

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
