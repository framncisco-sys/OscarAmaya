(function () {
  "use strict";

  var cfg = window.mapaEditorConfig || {};
  var selProyecto = document.getElementById("mapa-proyecto");
  var selPoligono = document.getElementById("mapa-poligono");
  var selLote = document.getElementById("mapa-lote");
  var btnReload = document.getElementById("mapa-reload");
  var btnSave = document.getElementById("mapa-save");
  var mapContainer = document.getElementById("mapa-lotes");
  if (!selProyecto || !selPoligono || !selLote || !mapContainer) return;

  var map = L.map("mapa-lotes", { crs: L.CRS.Simple, minZoom: -2 });
  var drawnItems = new L.FeatureGroup();
  var geoLayer = new L.FeatureGroup();
  map.addLayer(geoLayer);
  map.addLayer(drawnItems);
  var overlay = null;
  var currentData = null;
  var currentLoteId = "";

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
    return xyToLatLng(pt[0], pt[1]);
  }

  function latLngToPercent(pt) {
    return [Number(pt.lng.toFixed(4)), Number(pt.lat.toFixed(4))];
  }

  function styleByEstado(estado) {
    if (estado === "VENDIDO") return { color: "#9b1c1c", fillColor: "#ef4444" };
    if (estado === "RESERVADO") return { color: "#92400e", fillColor: "#f59e0b" };
    if (estado === "BLOQUEADO") return { color: "#374151", fillColor: "#6b7280" };
    return { color: "#0a4f94", fillColor: "#1d8cf8" };
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
      opt.textContent = (l.poligono_nombre ? l.poligono_nombre + " - " : "") + "Lote " + l.codigo;
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
        renderMapData(data);
        fillLoteOptions();
      });
  }

  function renderMapData(data) {
    geoLayer.clearLayers();
    drawnItems.clearLayers();
    if (overlay) {
      map.removeLayer(overlay);
      overlay = null;
    }
    if (!data.plano_url) return;
    var img = new Image();
    img.onload = function () {
      var bounds = boundsForImage(img.width, img.height);
      overlay = L.imageOverlay(data.plano_url, bounds).addTo(map);
      map.fitBounds(bounds);
      (data.features || []).forEach(function (f) {
        var coords = ((f.geometry || {}).coordinates || [])[0] || [];
        var latlngs = coords.map(percentToLatLng);
        if (!latlngs.length) return;
        var s = styleByEstado(f.properties.estado);
        var pol = L.polygon(latlngs, {
          color: s.color,
          fillColor: s.fillColor,
          weight: 1.2,
          fillOpacity: 0.28
        });
        pol.bindPopup("Lote " + f.properties.codigo + " (" + (f.properties.poligono_nombre || "Sin polígono") + ")");
        pol.feature = f;
        pol.on("click", function () {
          var id = this.feature && this.feature.id ? String(this.feature.id) : "";
          if (!id) return;
          selLote.value = id;
          currentLoteId = id;
          drawSelectedGeometry(id);
        });
        geoLayer.addLayer(pol);
      });
      if (currentLoteId) drawSelectedGeometry(currentLoteId);
    };
    img.src = data.plano_url;
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
    fetchProyectoData();
  });
  selPoligono.addEventListener("change", function () {
    currentLoteId = "";
    fetchProyectoData();
  });
  selLote.addEventListener("change", function () {
    currentLoteId = selLote.value || "";
    drawSelectedGeometry(currentLoteId);
  });
  btnSave.addEventListener("click", function () {
    saveCurrentGeometry(true);
  });

  // Inicializa pantalla: si hay un proyecto preseleccionado (o solo uno), cargar lotes de inmediato.
  if (!selProyecto.value && selProyecto.options.length === 2) {
    selProyecto.value = selProyecto.options[1].value;
  }
  refreshPoligonosByProyecto();
  if (selProyecto.value) {
    fetchProyectoData();
  }
})();
