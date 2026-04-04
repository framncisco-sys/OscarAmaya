/**
 * Formato de aceptación: proyecto → polígono → lote, financiamiento y fechas.
 */
(function () {
  "use strict";

  function parseJSONScript(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return null;
    }
  }

  function parseMoney(el) {
    if (!el || el.value === undefined || el.value === null) return 0;
    var t = String(el.value).replace(/,/g, "").replace(/\s/g, "").trim();
    if (!t) return 0;
    var n = parseFloat(t);
    return isFinite(n) ? n : 0;
  }

  function setMoney(el, n) {
    if (!el) return;
    if (!isFinite(n) || n < 0) n = 0;
    el.value = n.toFixed(2);
  }

  function pmtCuota(principal, annualPct, months) {
    var P = principal;
    var n = months;
    if (!n || n < 1 || !isFinite(P) || P <= 0) return null;
    var i = typeof annualPct === "number" ? annualPct : parseFloat(String(annualPct));
    if (!isFinite(i)) i = 0;
    if (i <= 0) return P / n;
    var r = i / 100 / 12;
    var pow = Math.pow(1 + r, n);
    if (!isFinite(pow) || pow === 1) return P / n;
    return (P * r * pow) / (pow - 1);
  }

  function parseDateInputValue(s) {
    var t = String(s || "").trim();
    if (!t) return null;
    if (/^\d{4}-\d{2}-\d{2}$/.test(t)) {
      var p = t.split("-");
      var y = parseInt(p[0], 10);
      var mo = parseInt(p[1], 10) - 1;
      var d = parseInt(p[2], 10);
      var dt = new Date(y, mo, d);
      return isFinite(dt.getTime()) ? dt : null;
    }
    var m = t.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})/);
    if (m) {
      var d0 = parseInt(m[1], 10);
      var m0 = parseInt(m[2], 10) - 1;
      var y0 = parseInt(m[3], 10);
      if (y0 < 100) y0 += 2000;
      var dt2 = new Date(y0, m0, d0);
      return isFinite(dt2.getTime()) ? dt2 : null;
    }
    return null;
  }

  function addMonthsDate(d, months) {
    if (!d || !isFinite(d.getTime())) return null;
    var day = d.getDate();
    var totalM = d.getMonth() + months;
    var y = d.getFullYear() + Math.floor(totalM / 12);
    var nm = ((totalM % 12) + 12) % 12;
    var last = new Date(y, nm + 1, 0).getDate();
    return new Date(y, nm, Math.min(day, last));
  }

  function fmtDMY(d) {
    if (!d || !isFinite(d.getTime())) return "—";
    var dd = String(d.getDate()).padStart(2, "0");
    var mm = String(d.getMonth() + 1).padStart(2, "0");
    return dd + "/" + mm + "/" + d.getFullYear();
  }

  function fmtMoney(n) {
    if (!isFinite(n) || n <= 0) return "—";
    return "$" + n.toFixed(2);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var proyectos = parseJSONScript("formato-proyectos-data") || [];
    var cat = parseJSONScript("formato-catalogo-inmuebles-data") || {};
    var polPorProy = cat.poligonosPorProyecto || {};
    var lotesPorClave = cat.lotesPorClave || {};
    var porId = cat.inmueblePorId || {};

    var selProyecto = document.getElementById("id-formato-proyecto-ayuda");
    var nomProyecto = document.getElementById("id_nombre_proyecto");
    var dirTerreno = document.getElementById("id_direccion_terreno");
    var selPol = document.getElementById("fmt-select-poligono");
    var selLote = document.getElementById("fmt-select-lote");
    var hidLote = document.getElementById("id_num_lote");
    var hidPol = document.getElementById("id_poligono_txt");
    var areaM2 = document.getElementById("id_area_m2_txt");
    var areaV2 = document.getElementById("id_area_v2_txt");
    var valorInm = document.getElementById("id_valor_inmueble");
    var prima1 = document.getElementById("id_prima_1");
    var prima2 = document.getElementById("id_prima_2");
    var valorFin = document.getElementById("id_valor_financiamiento");
    var letra = document.getElementById("id_letra_mensual");
    var plazo = document.getElementById("id_plazo_txt");
    var numCuota = document.getElementById("id_num_cuota_txt");
    var interes = document.getElementById("id_interes_txt");
    var obsFin = document.getElementById("id_observaciones_financiamiento");
    var fechaPrimera = document.getElementById("id_fecha_primera_cuota");
    var fechaPagoMensual = document.getElementById("id_fecha_pago_mensual");
    var prima1Fecha = document.getElementById("id_prima_1_fecha");
    var prima2Fecha = document.getElementById("id_prima_2_fecha");
    var tbodyListado = document.getElementById("fmt-listado-cuotas-body");

    var mapOk = !!(selPol && selLote && hidLote && hidPol);

    function recalcLetra() {
      if (plazo) {
        var years = parseInt(String(plazo.value || ""), 10);
        if (!isFinite(years) || years < 0) years = 0;
        var n = years * 12;
        if (numCuota) numCuota.value = n > 0 ? String(n) : "";

        if (letra && interes) {
          var principal = parseMoney(valorFin);
          var interVal = parseFloat(String(interes.value || ""));
          if (!isFinite(interVal) || interVal < 0) interVal = 0;
          var cuota = pmtCuota(principal, interVal, n);
          if (cuota === null) {
            letra.value = "";
          } else {
            letra.value = cuota.toFixed(2);
          }
        }
      }
      rebuildListadoCuotas();
    }

    function recalcFin() {
      var vi = parseMoney(valorInm);
      var p1 = parseMoney(prima1);
      var p2 = parseMoney(prima2);
      var fin = vi - p1 - p2;
      if (fin < 0) fin = 0;
      if (valorFin) setMoney(valorFin, fin);
      recalcLetra();
    }

    if (mapOk) {
      function fillPoligonos(proyectoId) {
        selPol.innerHTML = "";
        var o0 = document.createElement("option");
        o0.value = "";
        o0.textContent = "— Polígono —";
        selPol.appendChild(o0);
        if (!proyectoId) {
          selLote.innerHTML = "";
          var oL0 = document.createElement("option");
          oL0.value = "";
          oL0.textContent = "— No. de lote —";
          selLote.appendChild(oL0);
          return;
        }
        var pid = String(proyectoId);
        var pols = polPorProy[pid] || [];
        pols.forEach(function (p) {
          var o = document.createElement("option");
          o.value = String(p.id);
          o.textContent = p.nombre;
          selPol.appendChild(o);
        });
        var npKey = "np:" + pid;
        if (lotesPorClave[npKey] && lotesPorClave[npKey].length) {
          var onp = document.createElement("option");
          onp.value = npKey;
          onp.textContent = "— Lotes sin polígono —";
          selPol.appendChild(onp);
        }
        selLote.innerHTML = "";
        var oL = document.createElement("option");
        oL.value = "";
        oL.textContent = "— No. de lote —";
        selLote.appendChild(oL);
      }

      function fillLotes(clavePol) {
        selLote.innerHTML = "";
        var o0 = document.createElement("option");
        o0.value = "";
        o0.textContent = "— No. de lote —";
        selLote.appendChild(o0);
        if (!clavePol) return;
        var lotes = lotesPorClave[clavePol] || [];
        lotes.forEach(function (L) {
          var o = document.createElement("option");
          o.value = String(L.id);
          o.textContent = L.codigo;
          selLote.appendChild(o);
        });
      }

      function aplicarInmueble(invId) {
        var L = porId[String(invId)];
        if (!L) return;
        hidLote.value = L.codigo || "";
        hidPol.value = L.poligono_nombre || "";
        if (areaM2) areaM2.value = L.area_m2 || "";
        if (areaV2) areaV2.value = L.area_v2 || "";
        if (valorInm && L.precio) {
          var p = parseFloat(L.precio);
          if (isFinite(p)) setMoney(valorInm, p);
        }
        recalcFin();
      }

      selPol.addEventListener("change", function () {
        var v = selPol.value;
        fillLotes(v);
        hidLote.value = "";
        if (areaM2) areaM2.value = "";
        if (areaV2) areaV2.value = "";
        if (!v) {
          hidPol.value = "";
          return;
        }
        if (String(v).startsWith("np:")) {
          hidPol.value = "";
        } else {
          var opt = selPol.selectedOptions[0];
          hidPol.value = opt && opt.textContent ? opt.textContent.trim() : "";
        }
      });

      selLote.addEventListener("change", function () {
        var id = selLote.value;
        if (!id) {
          hidLote.value = "";
          return;
        }
        aplicarInmueble(id);
      });

      if (selProyecto && nomProyecto && dirTerreno) {
        selProyecto.addEventListener("change", function () {
          var id = selProyecto.value;
          if (!id) return;
          for (var i = 0; i < proyectos.length; i++) {
            if (String(proyectos[i].id) === String(id)) {
              nomProyecto.value = proyectos[i].nombre || "";
              dirTerreno.value = proyectos[i].direccion || "";
              break;
            }
          }
          fillPoligonos(id);
        });
      }

      if (selProyecto && selProyecto.value) {
        fillPoligonos(selProyecto.value);
      }

      function restoreLote() {
        var cod = hidLote && hidLote.value ? hidLote.value.trim() : "";
        var polName = hidPol && hidPol.value ? hidPol.value.trim() : "";
        if (!cod) return;
        var found = null;
        Object.keys(lotesPorClave).forEach(function (clave) {
          (lotesPorClave[clave] || []).forEach(function (L) {
            if (L.codigo.trim() !== cod) return;
            if (polName && L.poligono_nombre && L.poligono_nombre !== polName) return;
            if (!found) found = L;
          });
        });
        if (!found) return;
        var proyId = String(found.proyecto_id);
        if (selProyecto) selProyecto.value = proyId;
        fillPoligonos(proyId);
        selPol.value = found.clave_poligono;
        selPol.dispatchEvent(new Event("change", { bubbles: true }));
        selLote.value = String(found.id);
        selLote.dispatchEvent(new Event("change", { bubbles: true }));
      }

      restoreLote();
    }

    [prima1, prima2, valorInm].forEach(function (el) {
      if (el) el.addEventListener("input", recalcFin);
      if (el) el.addEventListener("change", recalcFin);
    });
    if (valorFin) {
      valorFin.addEventListener("input", recalcLetra);
      valorFin.addEventListener("change", recalcLetra);
    }
    if (plazo) {
      plazo.addEventListener("change", recalcLetra);
    }
    if (interes) {
      interes.addEventListener("input", recalcLetra);
      interes.addEventListener("change", recalcLetra);
    }

    function aplicarTextoObservacionesFinanciamiento() {
      if (!obsFin) return;
      var t = String(obsFin.value || "").toLowerCase();
      if (!t.trim()) return;
      if (/\b(sin\s*inter[eé]s|sin\s*interes|cero\s*inter[eé]s|0\s*%)\b/.test(t)) {
        if (interes && !String(interes.value || "").trim()) {
          interes.value = "0";
        }
      }
      var m = t.match(/\b(\d{1,2})\s*(?:años?|anos?)\b/);
      if (!m) m = t.match(/\bplazo\s*[:\s]*(\d{1,2})\b/);
      if (m && plazo && !String(plazo.value || "").trim()) {
        var y = parseInt(m[1], 10);
        if (y >= 0 && y <= 50) plazo.value = String(y);
      }
      recalcLetra();
    }

    if (obsFin) {
      obsFin.addEventListener("input", aplicarTextoObservacionesFinanciamiento);
      obsFin.addEventListener("blur", aplicarTextoObservacionesFinanciamiento);
    }

    function nCuotasDesdeFormulario() {
      var raw = numCuota && numCuota.value ? String(numCuota.value).trim() : "";
      if (raw && /^\d+$/.test(raw)) {
        var n = parseInt(raw, 10);
        return n > 0 ? n : null;
      }
      if (plazo && plazo.value) {
        var y = parseInt(String(plazo.value).trim(), 10);
        if (isFinite(y) && y > 0 && y <= 50) return y * 12;
      }
      return null;
    }

    function letraParaListado(n) {
      var L = letra && letra.value ? parseFloat(String(letra.value).replace(/,/g, "")) : NaN;
      if (isFinite(L) && L > 0) return L;
      var vf = parseMoney(valorFin);
      if (isFinite(vf) && vf > 0 && n > 0) return Math.round((vf / n) * 100) / 100;
      return null;
    }

    function rebuildListadoCuotas() {
      if (!tbodyListado) return;
      tbodyListado.innerHTML = "";
      var linea = 0;
      function appendRow(concepto, fechaStr, montoStr) {
        linea += 1;
        var tr = document.createElement("tr");
        tr.innerHTML =
          "<td style=\"padding:0.35rem 0.5rem;border:1px solid #e2e8f0;\">" +
          linea +
          "</td><td style=\"padding:0.35rem 0.5rem;border:1px solid #e2e8f0;\">" +
          concepto +
          "</td><td style=\"padding:0.35rem 0.5rem;border:1px solid #e2e8f0;\">" +
          fechaStr +
          "</td><td style=\"padding:0.35rem 0.5rem;border:1px solid #e2e8f0;text-align:right;\">" +
          montoStr +
          "</td>";
        tbodyListado.appendChild(tr);
      }

      var p1 = parseMoney(prima1);
      var p2 = parseMoney(prima2);
      var f1 = prima1Fecha && prima1Fecha.value ? parseDateInputValue(prima1Fecha.value) : null;
      var f2 = prima2Fecha && prima2Fecha.value ? parseDateInputValue(prima2Fecha.value) : null;
      if (p1 > 0 || f1) {
        appendRow("Prima 1", fmtDMY(f1), p1 > 0 ? fmtMoney(p1) : "—");
      }
      if (p2 > 0 || f2) {
        appendRow("Prima 2", fmtDMY(f2), p2 > 0 ? fmtMoney(p2) : "—");
      }

      var n = nCuotasDesdeFormulario();
      var fecha0 =
        (fechaPrimera && fechaPrimera.value ? parseDateInputValue(fechaPrimera.value) : null) ||
        (fechaPagoMensual && fechaPagoMensual.value ? parseDateInputValue(fechaPagoMensual.value) : null);
      if (n && fecha0) {
        var letraN = letraParaListado(n);
        var i;
        for (i = 0; i < n; i += 1) {
          var vd = addMonthsDate(fecha0, i);
          appendRow("Cuota " + (i + 1), fmtDMY(vd), letraN !== null ? fmtMoney(letraN) : "—");
        }
      }

      if (linea === 0) {
        var tr0 = document.createElement("tr");
        tr0.innerHTML =
          "<td colspan=\"4\" class=\"muted\" style=\"padding:0.45rem 0.5rem;border:1px solid #e2e8f0;font-size:0.82rem;\">" +
          "Indique primas (monto o fecha), fecha de primera cuota o «Fecha de pago mensual», y plazo o número de cuotas para ver el plan.</td>";
        tbodyListado.appendChild(tr0);
      }
    }

    var listadoWatch = [
      prima1,
      prima2,
      prima1Fecha,
      prima2Fecha,
      fechaPrimera,
      fechaPagoMensual,
      numCuota,
      plazo,
      letra,
      valorFin,
    ];
    listadoWatch.forEach(function (el) {
      if (!el) return;
      el.addEventListener("input", rebuildListadoCuotas);
      el.addEventListener("change", rebuildListadoCuotas);
    });

    recalcFin();
    rebuildListadoCuotas();
  });
})();
