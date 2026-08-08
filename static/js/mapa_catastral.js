(function () {
  "use strict";

  var cfg = window.mapaCatastralConfig || {};
  var selProyecto = document.getElementById("catastral-proyecto");
  var selPoligono = document.getElementById("catastral-poligono");
  var selLote = document.getElementById("catastral-lote");
  var btnReload = document.getElementById("catastral-reload");
  var btnSave = document.getElementById("catastral-save");
  var mapEl = document.getElementById("mapa-catastral");
  if (!selProyecto || !selPoligono || !selLote || !mapEl) return;

  var map = L.map("mapa-catastral", { zoomControl: true });
  var drawnItems = new L.FeatureGroup();
  var geoLayer = new L.FeatureGroup();
  map.addLayer(geoLayer);
  map.addLayer(drawnItems);

  /** Marcador temporal al buscar coordenadas (no se guarda en BD). */
  var searchMarkerLayer = L.layerGroup().addTo(map);

  var osm = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  });
  var esriSat = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    {
      maxZoom: 19,
      attribution: "Tiles &copy; Esri",
    }
  );

  var baseLayers = { OpenStreetMap: osm, "Satélite (Esri)": esriSat };
  if (
    cfg.googleMapsEnabled &&
    typeof google !== "undefined" &&
    google.maps &&
    L.gridLayer &&
    typeof L.gridLayer.googleMutant === "function"
  ) {
    baseLayers["Google mapa"] = L.gridLayer.googleMutant({ type: "roadmap" });
    baseLayers["Google satélite"] = L.gridLayer.googleMutant({ type: "satellite" });
  }
  L.control.layers(baseLayers, {}).addTo(map);
  osm.addTo(map);

  // El Salvador por defecto
  map.setView([13.8, -89.0], 9);

  var drawControl = new L.Control.Draw({
    edit: { featureGroup: drawnItems, remove: true },
    draw: {
      rectangle: false,
      circle: false,
      circlemarker: false,
      marker: false,
      polyline: false,
      polygon: { allowIntersection: false, showArea: true },
    },
  });
  map.addControl(drawControl);

  var currentData = null;
  var currentLoteId = "";

  var inpLat = document.getElementById("catastral-lat");
  var inpLng = document.getElementById("catastral-lng");
  var inpLine = document.getElementById("catastral-coords-line");
  var btnBuscarCoords = document.getElementById("catastral-buscar-coords");
  var btnLimpiarBusqueda = document.getElementById("catastral-limpiar-busqueda");

  function normalizeCoordText(t) {
    t = String(t || "")
      .replace(/^\uFEFF/, "")
      .replace(/\u00a0/g, " ")
      .trim();
    t = t.replace(/[\u2018\u2019\u2032]/g, "'").replace(/[\u201c\u201d\u2033]/g, '"');
    return t;
  }

  /** Coma decimal solo antes de comillas de segundos: 26,4" -> 26.4" (no toca 13°30'). */
  function normalizeDecimalCommaInDms(t) {
    return t.replace(/(\d+),(\d{1,4})(?=["\u201c\u201d\u2033])/g, "$1.$2");
  }

  function parseCoordToken(s) {
    if (s == null || s === "") return NaN;
    var t = normalizeCoordText(s);
    t = normalizeDecimalCommaInDms(t);
    // Permitir: 13.6929 | 13,6929 | 13°30'26.4"N | 88°16'03.7"W
    var hasHem = /[NSEW]/i.test(t);
    var nums = t.match(/-?\d+(?:\.\d+)?/g);
    if (!nums || !nums.length) return NaN;
    if (nums.length === 1 && !hasHem) {
      if (t.indexOf(",") >= 0 && t.indexOf(".") < 0) {
        t = t.replace(",", ".");
      }
      var dec = parseFloat(t);
      return isNaN(dec) ? NaN : dec;
    }
    var deg = parseFloat(nums[0]);
    var min = nums.length > 1 ? parseFloat(nums[1]) : 0;
    var sec = nums.length > 2 ? parseFloat(nums[2]) : 0;
    if (isNaN(deg) || isNaN(min) || isNaN(sec)) return NaN;
    var sign = 1;
    if (/S/i.test(t) || /W/i.test(t)) sign = -1;
    if (/^-/.test(nums[0])) sign = -1;
    return sign * (Math.abs(deg) + min / 60 + sec / 3600);
  }

  /**
   * Separa latitud y longitud en una sola línea (DMS o decimal).
   * Prioridad: bloque que termina en N/S + bloque que termina en E/W (evita fallos con espacios raros).
   */
  function parseLineCoords(line) {
    var raw = normalizeCoordText(line);
    if (!raw) return null;

    var pair = raw.match(/^(.+?[NS])\s+(.+?[EW])$/i);
    if (pair) {
      var lat1 = parseCoordToken(pair[1]);
      var lng1 = parseCoordToken(pair[2]);
      if (!isNaN(lat1) && !isNaN(lng1)) return { lat: lat1, lng: lng1 };
    }
    pair = raw.match(/^(.+?[EW])\s+(.+?[NS])$/i);
    if (pair) {
      var lng2 = parseCoordToken(pair[1]);
      var lat2 = parseCoordToken(pair[2]);
      if (!isNaN(lat2) && !isNaN(lng2)) return { lat: lat2, lng: lng2 };
    }

    var parts = raw.split(/[,;]/).map(function (p) {
      return p.trim();
    }).filter(Boolean);
    if (parts.length >= 2) {
      var a = parseCoordToken(parts[0]);
      var b = parseCoordToken(parts[1]);
      if (!isNaN(a) && !isNaN(b)) return { lat: a, lng: b };
    }

    parts = raw.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) {
      var p0 = parseCoordToken(parts[0]);
      var p1 = parseCoordToken(parts[1]);
      if (!isNaN(p0) && !isNaN(p1)) return { lat: p0, lng: p1 };
    }

    return null;
  }

  function readCoordsFromInputs() {
    if (inpLine && inpLine.value.trim()) {
      var parsed = parseLineCoords(inpLine.value);
      if (parsed) return { lat: parsed.lat, lng: parsed.lng, fromLine: true };
      return {
        lat: NaN,
        lng: NaN,
        fromLine: true,
        lineParseFailed: true,
      };
    }
    return {
      lat: inpLat ? parseCoordToken(inpLat.value) : NaN,
      lng: inpLng ? parseCoordToken(inpLng.value) : NaN,
      fromLine: false,
    };
  }

  function goToSearchCoords() {
    var o = readCoordsFromInputs();
    var lat = o.lat;
    var lng = o.lng;
    if (o.lineParseFailed) {
      alert(
        "No se pudo leer la línea pegada. Pruebe:\n" +
          "• Decimal: 13.5073, -89.2688\n" +
          "• Grados (una línea, con espacio entre lat y long): 13°30'26.4\"N 89°16'03.7\"W"
      );
      return;
    }
    if (isNaN(lat) || isNaN(lng)) {
      alert(
        "Ingrese latitud y longitud (números), o una línea con ambas separadas por coma o espacio (ej. 13.69, -89.21)."
      );
      return;
    }
    if (lat < -90 || lat > 90 || lng < -180 || lng > 180) {
      alert("Latitud entre -90 y 90; longitud entre -180 y 180.");
      return;
    }
    searchMarkerLayer.clearLayers();
    var mk = L.marker([lat, lng], { title: "Punto de búsqueda" });
    mk.bindPopup(
      "<strong>Punto de referencia</strong><br>" +
        lat.toFixed(6) +
        ", " +
        lng.toFixed(6) +
        "<br><span class='muted'>Use el dibujo de polígono para delimitar el lote.</span>"
    );
    searchMarkerLayer.addLayer(mk);
    var z = Math.max(map.getZoom(), 17);
    map.setView([lat, lng], z);
    mk.openPopup();
    if (o.fromLine && inpLat && inpLng) {
      inpLat.value = String(lat);
      inpLng.value = String(lng);
    }
  }

  function clearSearchMarker() {
    searchMarkerLayer.clearLayers();
  }

  var STYLES = {
    contado: { color: "#0d47a1", fillColor: "#1565c0", weight: 2, fillOpacity: 0.55 },
    reservado: { color: "#e65100", fillColor: "#ff9800", weight: 2, fillOpacity: 0.55 },
    disponible: { color: "#424242", fillColor: "#ffffff", weight: 2, fillOpacity: 0.75 },
    bloqueado: { color: "#424242", fillColor: "#9e9e9e", weight: 2, fillOpacity: 0.55 },
  };

  function styleForFeature(f) {
    var key = (f.properties && f.properties.mapa_style) || "disponible";
    return STYLES[key] || STYLES.disponible;
  }

  function getFeatureByLoteId(loteId) {
    if (!currentData || !currentData.features) return null;
    for (var i = 0; i < currentData.features.length; i++) {
      var f = currentData.features[i];
      if (String(f.id) === String(loteId)) return f;
    }
    return null;
  }

  function latLngsFromGeoJsonPolygon(geom) {
    var coords = ((geom || {}).coordinates || [])[0] || [];
    return coords.map(function (pt) {
      return L.latLng(pt[1], pt[0]);
    });
  }

  function ringToGeoJson(ringLatLngs) {
    var ring = ringLatLngs.map(function (ll) {
      return [Number(ll.lng.toFixed(7)), Number(ll.lat.toFixed(7))];
    });
    if (ring.length && (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1])) {
      ring.push([ring[0][0], ring[0][1]]);
    }
    return ring;
  }

  function polygonToRing(layer) {
    var latlngs = layer.getLatLngs();
    if (!latlngs || !latlngs[0] || !latlngs[0].length) return [];
    return ringToGeoJson(latlngs[0]);
  }

  function drawSelectedGeometry(loteId) {
    drawnItems.clearLayers();
    var feature = getFeatureByLoteId(loteId);
    if (!feature || !feature.geometry) return;
    var latlngs = latLngsFromGeoJsonPolygon(feature.geometry);
    if (!latlngs.length) return;
    var pol = L.polygon(latlngs, { color: "#003366", weight: 2, fillOpacity: 0.15 });
    drawnItems.addLayer(pol);
    if (pol.getBounds && pol.getBounds().isValid()) {
      map.fitBounds(pol.getBounds(), { padding: [24, 24], maxZoom: 18 });
    }
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

  /** La URL de Django es .../inmueble/0/guardar/ — no termina en 0/ (termina en guardar/). */
  function urlGuardarInmueble(inmuebleId) {
    return (cfg.apiGuardarBase || "").replace(
      /\/inmueble\/\d+\//,
      "/inmueble/" + inmuebleId + "/"
    );
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
      alert("La geometría se solapa con otro lote catastral. Ajuste el dibujo antes de guardar.");
      return;
    }
    var payload = { geometry: { type: "Polygon", coordinates: [ring] } };
    var url = urlGuardarInmueble(inmuebleId);
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
            alert("Geometría catastral guardada.");
          }
          fetchProyectoData();
        });
      })
      .catch(function (err) {
        alert("Error al guardar (red o respuesta no válida). " + (err && err.message ? err.message : ""));
      });
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
      var suffix = l.tiene_geometria_catastral ? "" : " (sin polígono en mapa)";
      opt.textContent =
        (l.poligono_nombre ? l.poligono_nombre + " - " : "") +
        "Lote " +
        (l.codigo_display || l.codigo) +
        suffix;
      selLote.appendChild(opt);
    });
    if (prev) selLote.value = prev;
    currentLoteId = selLote.value || "";
  }

  function fetchProyectoData() {
    var pid = selProyecto.value;
    if (!pid) return;
    var url = cfg.apiCatastralBase.replace(/0\/$/, pid + "/");
    var pol = selPoligono.value;
    if (pol) url += "?poligono_id=" + encodeURIComponent(pol);
    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        currentData = data;
        renderGeoJson(data);
        fillLoteOptions();
      });
  }

  function renderGeoJson(data) {
    geoLayer.clearLayers();
    drawnItems.clearLayers();
    var coll = {
      type: "FeatureCollection",
      features: data.features || [],
    };
    var gj = L.geoJSON(coll, {
      style: function (feat) {
        return styleForFeature(feat);
      },
      onEachFeature: function (feature, layer) {
        var html = (feature.properties && feature.properties.popup_html) || "";
        layer.bindPopup(html, { maxWidth: 420, className: "mapa-catastral-popup-wrap" });
        layer.on("click", function () {
          var id = feature.id != null ? String(feature.id) : "";
          if (!id) return;
          selLote.value = id;
          currentLoteId = id;
          drawSelectedGeometry(id);
        });
      },
    });
    geoLayer.addLayer(gj);
    if (gj.getBounds && gj.getBounds().isValid()) {
      map.fitBounds(gj.getBounds(), { padding: [20, 20], maxZoom: 18 });
    }
    if (currentLoteId) drawSelectedGeometry(currentLoteId);
  }

  map.on(L.Draw.Event.CREATED, function (e) {
    drawnItems.clearLayers();
    drawnItems.addLayer(e.layer);
    if (selLote.value) {
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

  if (btnBuscarCoords) {
    btnBuscarCoords.addEventListener("click", goToSearchCoords);
  }
  if (btnLimpiarBusqueda) {
    btnLimpiarBusqueda.addEventListener("click", clearSearchMarker);
  }
  function bindEnterToSearch(el) {
    if (!el) return;
    el.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") {
        ev.preventDefault();
        goToSearchCoords();
      }
    });
  }
  bindEnterToSearch(inpLat);
  bindEnterToSearch(inpLng);
  bindEnterToSearch(inpLine);

  if (!selProyecto.value && selProyecto.options.length === 2) {
    selProyecto.value = selProyecto.options[1].value;
  }
  refreshPoligonosByProyecto();
  if (selProyecto.value) {
    fetchProyectoData();
  }
})();
