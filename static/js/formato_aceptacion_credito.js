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

    var mapOk = !!(selPol && selLote && hidLote && hidPol);

    function recalcLetra() {
      if (!plazo) return;
      var years = parseInt(String(plazo.value || ""), 10);
      if (!isFinite(years) || years < 0) years = 0;
      var n = years * 12;
      if (numCuota) numCuota.value = n > 0 ? String(n) : "";

      if (!letra || !interes) return;
      var principal = parseMoney(valorFin);
      var interVal = parseFloat(String(interes.value || ""));
      if (!isFinite(interVal) || interVal < 0) interVal = 0;
      var cuota = pmtCuota(principal, interVal, n);
      if (cuota === null) {
        letra.value = "";
        return;
      }
      letra.value = cuota.toFixed(2);
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

    recalcFin();
  });
})();
