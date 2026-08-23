(function () {
  "use strict";

  var cfg = window.mapaEditorConfig || {};
  var selProyecto = document.getElementById("mapa-proyecto");
  var selPoligono = document.getElementById("mapa-poligono");
  var selLote = document.getElementById("mapa-lote");
  var btnReload = document.getElementById("mapa-reload");
  var btnAuto = document.getElementById("mapa-auto");
  var btnSave = document.getElementById("mapa-save");
  var mapContainer = document.getElementById("mapa-lotes");
  var resumenEl = document.getElementById("mapa-resumen");
  var panelEl = document.getElementById("mapa-lotes-panel");
  var tablaBody = document.getElementById("mapa-lotes-tabla-body");
  var detalleEl = document.getElementById("mapa-lote-detalle");
  if (!selProyecto || !selPoligono || !selLote || !mapContainer) return;

  var map = L.map("mapa-lotes", { crs: L.CRS.Simple, minZoom: -2 });
  var drawnItems = new L.FeatureGroup();
  var geoLayer = new L.FeatureGroup();
  map.addLayer(geoLayer);
  map.addLayer(drawnItems);
  var overlay = null;
  var currentData = null;
  var currentLoteId = "";
  var polygonLayersById = {};
  var autoGeometriaRunning = false;
  var autoGeometriaDoneFor = "";
  var autoRefreshTimer = null;
  var imageWidth = 100;
  var imageHeight = 100;

  var drawControl = new L.Control.Draw({
    edit: { featureGroup: drawnItems, remove: true },
    draw: {
      rectangle: { shapeOptions: { color: "#003366", weight: 2 } },
      circle: false,
      circlemarker: false,
      marker: false,
      polyline: false,
      polygon: { allowIntersection: false, showArea: true },
    },
  });
  map.addControl(drawControl);

  function boundsForImage(width, height) {
    return [[0, 0], [height, width]];
  }

  function xyToLatLng(x, y) {
    return L.latLng(y, x);
  }

  function percentToLatLng(pt) {
    // GeoJSON del mapa editor se guarda en porcentaje 0..100.
    var x = (Number(pt[0]) / 100) * imageWidth;
    var y = (Number(pt[1]) / 100) * imageHeight;
    return xyToLatLng(x, y);
  }

  function latLngToPercent(pt) {
    if (!imageWidth || !imageHeight) return [0, 0];
    var xPct = (pt.lng / imageWidth) * 100;
    var yPct = (pt.lat / imageHeight) * 100;
    xPct = Math.max(0, Math.min(100, xPct));
    yPct = Math.max(0, Math.min(100, yPct));
    return [Number(xPct.toFixed(4)), Number(yPct.toFixed(4))];
  }

  /** Misma leyenda que mapa catastral: contado / reservado / disponible / bloqueado */
  var STYLES_PLANO = {
    contado: { color: "#0d47a1", fillColor: "#1565c0", weight: 2, fillOpacity: 0.55 },
    reservado: { color: "#e65100", fillColor: "#ff9800", weight: 2, fillOpacity: 0.55 },
    disponible: { color: "#424242", fillColor: "#ffffff", weight: 2, fillOpacity: 0.75 },
    bloqueado: { color: "#424242", fillColor: "#9e9e9e", weight: 2, fillOpacity: 0.55 },
  };

  function styleForPlanoFeature(f) {
    var key = (f.properties && f.properties.mapa_style) || "disponible";
    return STYLES_PLANO[key] || STYLES_PLANO.disponible;
  }

  function badgeClass(styleKey) {
    if (styleKey === "contado") return "badge badge--vendido";
    if (styleKey === "reservado") return "badge badge--reservado";
    if (styleKey === "bloqueado") return "badge badge--bloqueado";
    return "badge badge--disponible";
  }

  function loteRowById(loteId) {
    if (!currentData || !currentData.lotes) return null;
    for (var i = 0; i < currentData.lotes.length; i++) {
      if (String(currentData.lotes[i].id) === String(loteId)) return currentData.lotes[i];
    }
    return null;
  }

  function renderResumen(resumen) {
    if (!resumenEl || !resumen) return;
    if (!resumen.total) {
      resumenEl.hidden = true;
      return;
    }
    resumenEl.hidden = false;
    resumenEl.innerHTML =
      "<strong>" +
      resumen.total +
      "</strong> lote(s): " +
      (resumen.disponible || 0) +
      " disponibles · " +
      (resumen.reservado || 0) +
      " reservados · " +
      (resumen.contado || 0) +
      " vendidos · " +
      (resumen.bloqueado || 0) +
      " bloqueados" +
      (resumen.sin_geometria
        ? " · <span class=\"mapa-resumen__aviso\">" +
          resumen.sin_geometria +
          " sin polígono dibujado en el plano</span>"
        : "") +
      " · actualizado " +
      new Date().toLocaleTimeString("es-SV", { hour: "2-digit", minute: "2-digit" });
  }

  function setResumenMensaje(html) {
    if (!resumenEl) return;
    resumenEl.hidden = false;
    resumenEl.innerHTML = html;
  }

  function autoGeometriaUrl() {
    var pid = selProyecto.value;
    if (!pid || !cfg.apiAutoGeometriaBase) return "";
    return cfg.apiAutoGeometriaBase.replace(/0\/?$/, pid + "/");
  }

  function ejecutarAutoGeometria(force) {
    var pid = selProyecto.value;
    if (!pid || autoGeometriaRunning) {
      return Promise.resolve(false);
    }
    var key = pid + ":" + (selPoligono.value || "");
    if (!force && autoGeometriaDoneFor === key) {
      return Promise.resolve(false);
    }
    var url = autoGeometriaUrl();
    if (!url) return Promise.resolve(false);

    autoGeometriaRunning = true;
    if (btnAuto) btnAuto.disabled = true;
    setResumenMensaje(
      '<span class="mapa-resumen__aviso">Detectando y delimitando lotes en el plano…</span>'
    );

    var payload = {};
    if (selPoligono.value) payload.poligono_id = parseInt(selPoligono.value, 10);

    return fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": cfg.csrfToken || "",
      },
      body: JSON.stringify(payload),
      credentials: "same-origin",
    })
      .then(function (res) {
        return res.json().then(function (body) {
          if (!res.ok || !body.ok) {
            var err = (body && body.error) || "No se pudo detectar lotes automáticamente.";
            setResumenMensaje('<span class="mapa-resumen__aviso">' + err + "</span>");
            return false;
          }
          if (body.guardados > 0) {
            setResumenMensaje(
              "<strong>" +
                body.guardados +
                "</strong> lote(s) delimitados automáticamente en el plano."
            );
          }
          return true;
        });
      })
      .catch(function () {
        setResumenMensaje(
          '<span class="mapa-resumen__aviso">Error de red al detectar lotes en el plano.</span>'
        );
        return false;
      })
      .finally(function () {
        autoGeometriaRunning = false;
        autoGeometriaDoneFor = key;
        if (btnAuto) btnAuto.disabled = false;
      });
  }

  function showDetalleLote(lote) {
    if (!detalleEl || !lote) {
      if (detalleEl) detalleEl.hidden = true;
      return;
    }
    detalleEl.hidden = false;
    detalleEl.innerHTML = lote.popup_html || "";
  }

  function focusLoteOnMap(loteId) {
    var layer = polygonLayersById[String(loteId)];
    if (layer && layer.openPopup) {
      layer.openPopup();
      if (layer.getBounds && layer.getBounds().isValid()) {
        map.fitBounds(layer.getBounds(), { padding: [24, 24], maxZoom: 2 });
      }
      return true;
    }
    return false;
  }

  function seleccionarLote(loteId, loteRow) {
    currentLoteId = String(loteId || "");
    selLote.value = currentLoteId;
    drawSelectedGeometry(currentLoteId);
    if (loteRow) showDetalleLote(loteRow);
    if (tablaBody) {
      Array.prototype.forEach.call(tablaBody.querySelectorAll("tr"), function (tr) {
        tr.classList.toggle("is-selected", tr.getAttribute("data-lote-id") === currentLoteId);
      });
    }
    if (currentLoteId && !focusLoteOnMap(currentLoteId) && loteRow) {
      showDetalleLote(loteRow);
    }
  }

  function renderLotesTabla(lotes) {
    if (!tablaBody || !panelEl) return;
    tablaBody.innerHTML = "";
    if (!lotes || !lotes.length) {
      panelEl.hidden = true;
      return;
    }
    panelEl.hidden = false;
    lotes.forEach(function (l) {
      var tr = document.createElement("tr");
      tr.setAttribute("data-lote-id", String(l.id));
      tr.tabIndex = 0;
      var fmtCell = "—";
      if (l.formato_numero) {
        var num = String(l.formato_numero);
        while (num.length < 4) num = "0" + num;
        if (l.formato_url) {
          fmtCell = '<a href="' + l.formato_url + '" class="link-action">#' + num + "</a>";
        } else {
          fmtCell = "#" + num;
        }
      }
      tr.innerHTML =
        "<td><strong>" +
        (l.codigo_display || l.codigo) +
        "</strong></td>" +
        "<td>" +
        (l.poligono_nombre || "—") +
        "</td>" +
        '<td><span class="' +
        badgeClass(l.mapa_style) +
        '">' +
        (l.estado_display || l.estado) +
        "</span></td>" +
        "<td>" +
        (l.cliente || "—") +
        "</td>" +
        "<td>" +
        fmtCell +
        "</td>" +
        "<td>" +
        (l.tiene_geometria ? "Sí" : '<span class="muted">Sin dibujar</span>') +
        "</td>";
      tr.addEventListener("click", function () {
        seleccionarLote(l.id, l);
      });
      tr.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          seleccionarLote(l.id, l);
        }
      });
      tablaBody.appendChild(tr);
    });
    if (currentLoteId) {
      Array.prototype.forEach.call(tablaBody.querySelectorAll("tr"), function (tr) {
        tr.classList.toggle("is-selected", tr.getAttribute("data-lote-id") === currentLoteId);
      });
    }
  }

  function getFeatureByLoteId(loteId) {
    if (!currentData || !currentData.features) return null;
    for (var i = 0; i < currentData.features.length; i++) {
      var f = currentData.features[i];
      if (String(f.id) === String(loteId)) return f;
    }
    return null;
  }

  function drawSelectedGeometry(loteId) {
    drawnItems.clearLayers();
    var feature = getFeatureByLoteId(loteId);
    if (!feature) return;
    var coords = ((feature.geometry || {}).coordinates || [])[0] || [];
    if (!coords.length) return;
    var latlngs = coords.map(percentToLatLng);
    var pol = L.polygon(latlngs, { color: "#003366", weight: 2, fillOpacity: 0.2 });
    drawnItems.addLayer(pol);
    if (pol.getBounds && pol.getBounds().isValid()) {
      map.fitBounds(pol.getBounds(), { padding: [20, 20], maxZoom: 2 });
    }
  }

  function polygonToRing(layer) {
    var latlngs = layer.getLatLngs();
    if (!latlngs || !latlngs[0] || !latlngs[0].length) return [];
    var ring = latlngs[0].map(latLngToPercent);
    if (ring.length && (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1])) {
      ring.push([ring[0][0], ring[0][1]]);
    }
    return ring;
  }

  function saveCurrentGeometry(showSuccessMessage) {
    var inmuebleId = selLote.value;
    if (!inmuebleId) {
      alert("Seleccione un lote a editar.");
      return;
    }
    var layer = null;
    drawnItems.eachLayer(function (l) { layer = l; });
    if (!layer) {
      alert("Dibuje el polígono del lote antes de guardar.");
      return;
    }
    var ring = polygonToRing(layer);
    if (!ring.length) {
      alert("Polígono inválido.");
      return;
    }
    if (hasOverlap(ring, inmuebleId)) {
      alert("La geometría se solapa con otro lote. Ajuste el dibujo antes de guardar.");
      return;
    }
    var payload = { geometry: { type: "Polygon", coordinates: [ring] } };
    var url = (cfg.apiGuardarBase || "").replace(
      /\/inmueble\/\d+\//,
      "/inmueble/" + inmuebleId + "/"
    );
    fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": cfg.csrfToken || "",
      },
      body: JSON.stringify(payload),
      credentials: "same-origin",
    })
      .then(function (res) {
        return res.json().then(function (body) {
          if (!res.ok) {
            alert((body && body.error) || "Error HTTP " + res.status);
            return;
          }
          if (!body.ok) {
            alert((body && body.error) || "No se pudo guardar.");
            return;
          }
          if (showSuccessMessage) {
            alert("Geometría guardada.");
          }
          fetchProyectoData();
        });
      })
      .catch(function (err) {
        alert("Error al guardar (red o respuesta no válida). " + (err && err.message ? err.message : ""));
      });
  }

  function segments(ring) {
    var out = [];
    for (var i = 0; i < ring.length - 1; i++) out.push([ring[i], ring[i + 1]]);
    return out;
  }

  function ccw(a, b, c) {
    return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0]);
  }

  function segIntersects(s1, s2) {
    var a = s1[0], b = s1[1], c = s2[0], d = s2[1];
    return ccw(a, c, d) !== ccw(b, c, d) && ccw(a, b, c) !== ccw(a, b, d);
  }

  function pointInPolygon(pt, ring) {
    var x = pt[0], y = pt[1], inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var xi = ring[i][0], yi = ring[i][1];
      var xj = ring[j][0], yj = ring[j][1];
      var intersect = yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / ((yj - yi) || 1e-9) + xi;
      if (intersect) inside = !inside;
    }
    return inside;
  }

  function hasOverlap(ring, inmuebleId) {
    if (!currentData || !currentData.features) return false;
    var segA = segments(ring);
    for (var i = 0; i < currentData.features.length; i++) {
      var f = currentData.features[i];
      if (String(f.id) === String(inmuebleId)) continue;
      var ringB = (((f.geometry || {}).coordinates || [])[0] || []);
      if (!ringB.length) continue;
      var segB = segments(ringB);
      for (var a = 0; a < segA.length; a++) {
        for (var b = 0; b < segB.length; b++) {
          if (segIntersects(segA[a], segB[b])) return true;
        }
      }
      if (pointInPolygon(ring[0], ringB) || pointInPolygon(ringB[0], ring)) return true;
    }
    return false;
  }

  function refreshPoligonosByProyecto() {
    var pid = selProyecto.value;
    Array.prototype.forEach.call(selPoligono.options, function (opt) {
      if (!opt.value) {
        opt.hidden = false;
        return;
      }
      var op = opt.getAttribute("data-proyecto-id");
      opt.hidden = !!(pid && op !== pid);
    });
    if (selPoligono.selectedOptions[0] && selPoligono.selectedOptions[0].hidden) {
      selPoligono.value = "";
    }
  }

  function fillLoteOptions() {
    var prev = currentLoteId || selLote.value;
    selLote.innerHTML = '<option value="">Seleccione lote</option>';
    if (!currentData || !currentData.lotes) return;
    currentData.lotes.forEach(function (l) {
      if (selPoligono.value && String(l.poligono_id || "") !== selPoligono.value) return;
      var opt = document.createElement("option");
      opt.value = String(l.id);
      var suf = l.tiene_geometria_plano ? "" : " (sin polígono en plano)";
      opt.textContent =
        (l.poligono_nombre ? l.poligono_nombre + " - " : "") +
        "Lote " +
        (l.codigo_display || l.codigo) +
        suf;
      selLote.appendChild(opt);
    });
    if (prev) selLote.value = prev;
    currentLoteId = selLote.value || "";
  }

  function fetchProyectoData() {
    var pid = selProyecto.value;
    if (!pid) return;
    var url = cfg.apiProyectoBase.replace(/0\/$/, pid + "/");
    var pol = selPoligono.value;
    if (pol) url += "?poligono_id=" + encodeURIComponent(pol);
    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        currentData = data;
        var needsAuto =
          data.resumen &&
          data.resumen.sin_geometria > 0 &&
          data.resumen.total > 0;
        if (needsAuto) {
          return ejecutarAutoGeometria(false).then(function (didAuto) {
            if (didAuto) {
              return fetch(url).then(function (r2) { return r2.json(); });
            }
            return data;
          });
        }
        return data;
      })
      .then(function (data) {
        if (!data) return;
        currentData = data;
        renderMapData(data);
        fillLoteOptions();
        renderResumen(data.resumen);
        renderLotesTabla(data.lotes);
      });
  }

  function renderMapData(data) {
    geoLayer.clearLayers();
    drawnItems.clearLayers();
    polygonLayersById = {};
    if (overlay) {
      map.removeLayer(overlay);
      overlay = null;
    }
    if (!data.plano_url && !data.plano_imagen_url) return;
    var imgUrl = data.plano_imagen_url || data.plano_url;
    var img = new Image();
    img.onload = function () {
      imageWidth = img.width || 100;
      imageHeight = img.height || 100;
      var bounds = boundsForImage(img.width, img.height);
      overlay = L.imageOverlay(imgUrl, bounds).addTo(map);
      map.fitBounds(bounds);
      (data.features || []).forEach(function (f) {
        var coords = ((f.geometry || {}).coordinates || [])[0] || [];
        var latlngs = coords.map(percentToLatLng);
        if (!latlngs.length) return;
        var s = styleForPlanoFeature(f);
        var pol = L.polygon(latlngs, {
          color: s.color,
          fillColor: s.fillColor,
          weight: s.weight != null ? s.weight : 1.2,
          fillOpacity: s.fillOpacity != null ? s.fillOpacity : 0.28
        });
        var html =
          (f.properties && f.properties.popup_html) ||
          "Lote " +
            (f.properties.codigo_display || f.properties.codigo) +
            " (" +
            (f.properties.poligono_nombre || "Sin polígono") +
            ")";
        pol.bindPopup(html, { maxWidth: 420, className: "mapa-catastral-popup-wrap" });
        pol.bindTooltip(f.properties.codigo_display || f.properties.codigo || "Lote", {
          permanent: true,
          direction: "center",
          className: "mapa-lote-tooltip",
        });
        pol.feature = f;
        pol.on("click", function () {
          var id = this.feature && this.feature.id ? String(this.feature.id) : "";
          if (!id) return;
          seleccionarLote(id, loteRowById(id));
        });
        polygonLayersById[String(f.id)] = pol;
        geoLayer.addLayer(pol);
      });
      if (currentLoteId) drawSelectedGeometry(currentLoteId);
    };
    img.src = imgUrl;
  }

  if (btnAuto) {
    btnAuto.addEventListener("click", function () {
      autoGeometriaDoneFor = "";
      ejecutarAutoGeometria(true).then(function (ok) {
        if (ok) fetchProyectoData();
      });
    });
  }

  map.on(L.Draw.Event.CREATED, function (e) {
    drawnItems.clearLayers();
    drawnItems.addLayer(e.layer);
    if (selLote.value) {
      // Guardado inmediato al terminar el dibujo (sin recargar la página).
      saveCurrentGeometry(false);
    }
  });

  btnReload.addEventListener("click", fetchProyectoData);
  selProyecto.addEventListener("change", function () {
    refreshPoligonosByProyecto();
    currentLoteId = "";
    autoGeometriaDoneFor = "";
    fetchProyectoData();
  });
  selPoligono.addEventListener("change", function () {
    currentLoteId = "";
    autoGeometriaDoneFor = "";
    fetchProyectoData();
  });
  selLote.addEventListener("change", function () {
    seleccionarLote(selLote.value || "", loteRowById(selLote.value));
  });
  btnSave.addEventListener("click", function () {
    saveCurrentGeometry(true);
  });

  if (autoRefreshTimer) window.clearInterval(autoRefreshTimer);
  autoRefreshTimer = window.setInterval(function () {
    if (selProyecto.value) fetchProyectoData();
  }, 90000);

  // Inicializa pantalla: si hay un proyecto preseleccionado (o solo uno), cargar lotes de inmediato.
  if (!selProyecto.value && selProyecto.options.length === 2) {
    selProyecto.value = selProyecto.options[1].value;
  }
  refreshPoligonosByProyecto();
  if (selProyecto.value) {
    fetchProyectoData();
  }
})();
