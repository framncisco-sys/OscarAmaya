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
    var t = String(el.value).replace(/\$/g, "").replace(/\s/g, "").trim();
    if (!t) return 0;
    if (t.indexOf(",") >= 0 && t.indexOf(".") >= 0) {
      if (t.lastIndexOf(",") > t.lastIndexOf(".")) {
        t = t.replace(/\./g, "").replace(",", ".");
      } else {
        t = t.replace(/,/g, "");
      }
    } else if (t.indexOf(",") >= 0) {
      var parts = t.split(",");
      if (parts.length === 2 && /^\d{1,2}$/.test(parts[1])) {
        t = parts[0].replace(/\./g, "") + "." + parts[1];
      } else {
        t = t.replace(/,/g, "");
      }
    }
    var n = parseFloat(t);
    return isFinite(n) ? n : 0;
  }

  function formatMoneyUS(n) {
    if (!isFinite(n) || n < 0) n = 0;
    return n.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function setMoney(el, n) {
    if (!el) return;
    if (!isFinite(n) || n < 0) n = 0;
    el.value = "$" + formatMoneyUS(n);
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

  /** Cuota del vendedor (meses 1–12 sin interés) y cuota desde mes 13 (PMT sobre saldo). */
  function planCuotasAPlazos(principalNeto, letraMin, annualPct, nCuotas) {
    var P = principalNeto;
    var n = nCuotas;
    var letra = letraMin;
    if (!n || n < 1 || !isFinite(letra) || letra <= 0) {
      return { letra: null, cuota13: null };
    }
    letra = Math.round(letra * 100) / 100;
    if (n <= 12) {
      return { letra: letra, cuota13: null };
    }
    if (!isFinite(P) || P < 0) P = 0;
    var tasa = isFinite(annualPct) && annualPct > 0 ? annualPct : 0;
    var saldo = P - letra * 12;
    if (saldo < 0) saldo = 0;
    var mesesRest = n - 12;
    var cuota13 = pmtCuota(saldo, tasa, mesesRest);
    cuota13 = Math.round(cuota13 * 100) / 100;
    return { letra: letra, cuota13: cuota13 };
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
    return "$" + formatMoneyUS(n);
  }

  function parseInteresAnual(el) {
    if (!el) return 0;
    var raw = String(el.value || "").trim();
    if (!raw) return 0;
    var m = raw.match(/(\d+(?:\.\d+)?)/);
    if (!m) return 0;
    var v = parseFloat(m[1]);
    return isFinite(v) && v >= 0 ? v : 0;
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
    var formRoot = document.getElementById("formato-aceptacion-form");
    var valorInmInicial = valorInm ? valorInm.value : "";

    function debeConservarPrecioVigente() {
      if (!formRoot) return false;
      if (formRoot.getAttribute("data-pbr-precio-fijado") === "1") return true;
      if (formRoot.getAttribute("data-pbr-validacion-precio") === "APROBADO") return true;
      var valorSol = document.getElementById("id_valor_inmueble_solicitado");
      var valorSis = document.getElementById("id_valor_inmueble_sistema");
      if (!valorSol || !valorSol.value) return false;
      var sol = parseFloat(String(valorSol.value).replace(/[$,]/g, ""));
      var sis = valorSis ? parseFloat(String(valorSis.value).replace(/[$,]/g, "")) : NaN;
      if (!isFinite(sol) || !isFinite(sis) || Math.abs(sol - sis) < 0.005) return false;
      var ini = parseFloat(String(valorInmInicial).replace(/[$,]/g, ""));
      return isFinite(ini) && Math.abs(ini - sol) < 0.005;
    }

    function restaurarPrecioVigente() {
      if (!debeConservarPrecioVigente() || !valorInm) return;
      var vigente =
        (formRoot && formRoot.getAttribute("data-pbr-precio-vigente")) ||
        valorInmInicial;
      if (!vigente) return;
      var p = parseFloat(String(vigente).replace(/[$,]/g, ""));
      if (!isFinite(p)) return;
      setMoney(valorInm, p);
      forzarActualizacionPlanCuotas(true);
      actualizarPrecioNegociadoInline();
    }

    var prima1 = document.getElementById("id_prima_1");
    var prima2 = document.getElementById("id_prima_2");
    var valorFin = document.getElementById("id_valor_financiamiento");
    var letra = document.getElementById("id_letra_mensual");
    var plazo = document.getElementById("id_plazo_txt");
    var numCuota = document.getElementById("id_num_cuota_txt");
    var interes = document.getElementById("id_interes_txt");
    var tipoFin = document.getElementById("id_tipo_financiamiento");
    var obsFin = document.getElementById("id_observaciones_financiamiento");
    var fechaPrimera = document.getElementById("id_fecha_primera_cuota");
    var fechaPagoMensual = document.getElementById("id_fecha_pago_mensual");
    var prima1Fecha = document.getElementById("id_prima_1_fecha");
    var prima2Fecha = document.getElementById("id_prima_2_fecha");
    var tbodyListado = document.getElementById("fmt-listado-cuotas-body");
    var planCuotasServidor = parseJSONScript("formato-plan-cuotas-servidor") || null;
    var usuarioEditoPlan = false;
    var actualizacionProgramatica = false;

    function debeUsarPlanServidor() {
      if (!planCuotasServidor || !planCuotasServidor.length || usuarioEditoPlan) return false;
      if (!formRoot) return true;
      var fijado = formRoot.getAttribute("data-pbr-precio-fijado") === "1";
      var aprobado = formRoot.getAttribute("data-pbr-validacion-precio") === "APROBADO";
      return fijado || aprobado || !!formRoot.getAttribute("data-pbr-precio-vigente");
    }

    function cuota13DesdeServidor() {
      if (!planCuotasServidor || !planCuotasServidor.length) return null;
      for (var i = 0; i < planCuotasServidor.length; i += 1) {
        var concepto = String(planCuotasServidor[i].concepto || "");
        if (concepto.indexOf("Cuota 13") !== 0) continue;
        var m = parseFloat(String(planCuotasServidor[i].monto || "").replace(/,/g, ""));
        return isFinite(m) && m > 0 ? m : null;
      }
      return null;
    }

    function valorInmuebleVigente() {
      if (debeConservarPrecioVigente() && formRoot) {
        var vigenteRaw = formRoot.getAttribute("data-pbr-precio-vigente") || "";
        var p = parseFloat(String(vigenteRaw).replace(/[$,]/g, ""));
        if (isFinite(p) && p > 0) return p;
      }
      return parseMoney(valorInm);
    }

    var mapOk = !!(selPol && selLote && hidLote && hidPol);

    function esContado() {
      return tipoFin && String(tipoFin.value || "") === "CONTADO";
    }

    function setPlazosCamposEnabled(enabled) {
      [letra, plazo, numCuota, interes, fechaPrimera, fechaPagoMensual].forEach(function (el) {
        if (!el) return;
        el.disabled = !enabled;
        if (!enabled) el.classList.add("is-readonly");
        else el.classList.remove("is-readonly");
      });
      if (valorFin) {
        valorFin.readOnly = !enabled;
      }
    }

    function aplicarTipoFinanciamiento() {
      if (esContado()) {
        if (valorFin) setMoney(valorFin, 0);
        if (letra) letra.value = "";
        if (plazo) plazo.value = "";
        if (numCuota) numCuota.value = "";
        if (interes) interes.value = "";
        setPlazosCamposEnabled(false);
        forzarActualizacionPlanCuotas(true);
        return;
      }
      setPlazosCamposEnabled(true);
      recalcFin();
    }

    function recalcLetra() {
      if (esContado()) {
        if (letra) letra.value = "";
        forzarActualizacionPlanCuotas(true);
        return;
      }
      if (plazo) {
        var years = parseInt(String(plazo.value || ""), 10);
        if (!isFinite(years) || years < 1) years = 0;
        if (years > 6) years = 6;
        var n = years * 12;
        if (numCuota) numCuota.value = n > 0 ? String(n) : "";
        // La cuota 1–12 la escribe el vendedor; no se calcula ni se pisa aquí.
      }
      forzarActualizacionPlanCuotas(debeUsarPlanServidor());
      actualizarResumenPlan();
    }

    function actualizarResumenPlan() {
      var box = document.getElementById("fmt-plan-plazos-resumen");
      if (!box) return;
      if (esContado()) {
        box.textContent = "Financiamiento: Contado (sin plan de cuotas).";
        return;
      }
      var years = plazo ? parseInt(String(plazo.value || ""), 10) : 0;
      if (!isFinite(years) || years < 1) {
        box.textContent =
          "Elija plazo (1–6 años). Escriba la cuota de los meses 1–12 (sin interés). Desde el mes 13 ya va con intereses.";
        return;
      }
      var n = nCuotasDesdeFormulario();
      if (!n) {
        box.textContent =
          "Elija plazo (1–6 años). Escriba la cuota de los meses 1–12 (sin interés). Desde el mes 13 ya va con intereses.";
        return;
      }
      var principal = principalFinanciamiento();
      var interVal = parseInteresAnual(interes);
      var letraVend = parseMoney(letra);
      if (!letraVend || letraVend <= 0) {
        box.textContent =
          "Escriba la cuota de los meses 1–12 (sin interés). Desde el mes 13 se reparte el saldo restante con intereses.";
        return;
      }
      var cuota13Srv = debeUsarPlanServidor() ? cuota13DesdeServidor() : null;
      var plan = planCuotasAPlazos(principal, letraVend, interVal, n);
      if (n <= 12) {
        box.textContent =
          "Plan " +
          years +
          " año(s): cuota del vendedor $" +
          formatMoneyUS(plan.letra) +
          " sin interés en las " +
          n +
          " cuotas.";
        return;
      }
      var cuota13Mostrar =
        cuota13Srv !== null && cuota13Srv > 0 ? cuota13Srv : plan.cuota13;
      box.textContent =
        "Meses 1–12: cuota del vendedor $" +
        formatMoneyUS(plan.letra) +
        " sin interés. Desde el mes 13: $" +
        formatMoneyUS(cuota13Mostrar) +
        " mensuales (saldo restante ÷ meses que faltan, con " +
        interVal +
        "% anual).";
    }

    function principalFinanciamiento() {
      var vi = valorInmuebleVigente();
      var p1 = parseMoney(prima1);
      var p2 = parseMoney(prima2);
      var fin = vi - p1 - p2;
      if (fin < 0) fin = 0;
      fin = Math.round(fin * 100) / 100;
      actualizacionProgramatica = true;
      try {
        if (valorFin) setMoney(valorFin, fin);
      } finally {
        actualizacionProgramatica = false;
      }
      return fin;
    }

    function recalcFin() {
      if (esContado()) {
        if (valorFin) setMoney(valorFin, 0);
        if (letra) letra.value = "";
        forzarActualizacionPlanCuotas(true);
        return;
      }
      principalFinanciamiento();
      recalcLetra();
    }

    function actualizarPrecioNegociadoInline() {
      var lineNeg = document.getElementById("pbr-precio-negociado-line");
      var panel = document.getElementById("pbr-precios-lote-panel");
      if (!lineNeg || !formRoot) return;
      var valPrecio = formRoot.getAttribute("data-pbr-validacion-precio") || "";
      if (valPrecio !== "APROBADO") {
        lineNeg.hidden = true;
        lineNeg.textContent = "";
        return;
      }
      var vigenteRaw = formRoot.getAttribute("data-pbr-precio-vigente") || "";
      var sistemaRaw = formRoot.getAttribute("data-pbr-precio-sistema") || "";
      var vigente = parseFloat(String(vigenteRaw).replace(/[$,]/g, ""));
      var sistema = parseFloat(String(sistemaRaw).replace(/[$,]/g, ""));
      if (valorInm && valorInm.value) {
        var viDom = parseMoney(valorInm);
        if (isFinite(viDom) && viDom > 0) vigente = viDom;
      }
      if (!isFinite(vigente) || vigente <= 0) {
        lineNeg.hidden = true;
        return;
      }
      if (isFinite(sistema) && sistema > 0 && Math.abs(vigente - sistema) < 0.005) {
        lineNeg.hidden = true;
        return;
      }
      lineNeg.hidden = false;
      var lbl = function (n) {
        return "$" + formatMoneyUS(n);
      };
      var txt =
        "✓ Precio negociado aprobado: " +
        lbl(vigente) +
        " USD (no usar precio de etapa";
      if (isFinite(sistema) && sistema > 0) {
        txt += "; etapa " + lbl(sistema);
      }
      txt += ")";
      lineNeg.textContent = txt;
      if (panel) panel.classList.add("pbr-precios-lote-panel--negociado");
    }

    var porcentajePrimaProyecto = null;
    var porcentajeReservaProyecto = null;

    function proyectoPorId(id) {
      for (var i = 0; i < proyectos.length; i++) {
        if (String(proyectos[i].id) === String(id)) return proyectos[i];
      }
      return null;
    }

    function actualizarInfoPrimaProyecto() {
      var box = document.getElementById("pbr-prima-proyecto-info");
      if (!box) return;
      var partes = [];
      if (porcentajeReservaProyecto != null && isFinite(porcentajeReservaProyecto)) {
        partes.push("Reserva: " + porcentajeReservaProyecto + "% del lote");
      }
      if (porcentajePrimaProyecto != null && isFinite(porcentajePrimaProyecto)) {
        partes.push("Prima total: " + porcentajePrimaProyecto + "% del lote");
      }
      if (!partes.length) {
        box.hidden = true;
        box.textContent = "";
        return;
      }
      var r = parseMoney(prima1);
      var p2 = parseMoney(prima2);
      box.hidden = false;
      box.textContent =
        partes.join(" · ") +
        (isFinite(r) || isFinite(p2)
          ? " → Reserva $" +
            formatMoneyUS(r || 0) +
            " + Prima a pagar $" +
            formatMoneyUS(p2 || 0)
          : "") +
        ".";
    }

    function aplicarReservaYPrimaDesdeProyecto(opts) {
      opts = opts || {};
      if (!prima1) {
        actualizarInfoPrimaProyecto();
        return;
      }
      var vi = parseMoney(valorInm);
      if (!isFinite(vi) || vi <= 0) {
        actualizarInfoPrimaProyecto();
        return;
      }
      if (porcentajeReservaProyecto != null && isFinite(porcentajeReservaProyecto)) {
        var reservaCalc = (vi * porcentajeReservaProyecto) / 100;
        if (reservaCalc < 0) reservaCalc = 0;
        setMoney(prima1, reservaCalc);
      } else if (opts.clearReserva) {
        prima1.value = "";
      }

      if (porcentajePrimaProyecto != null && isFinite(porcentajePrimaProyecto) && prima2) {
        var primaTotal = (vi * porcentajePrimaProyecto) / 100;
        var r = parseMoney(prima1);
        if (isFinite(r)) {
          var rest = primaTotal - r;
          if (rest < 0) rest = 0;
          setMoney(prima2, rest);
        }
      }
      actualizarInfoPrimaProyecto();
      recalcFin();
    }

    function setConfigFinancieraDesdeProyectoId(id) {
      var p = proyectoPorId(id);
      porcentajePrimaProyecto = null;
      porcentajeReservaProyecto = null;
      if (p) {
        if (
          p.porcentaje_prima !== undefined &&
          p.porcentaje_prima !== null &&
          String(p.porcentaje_prima) !== ""
        ) {
          var np = parseFloat(String(p.porcentaje_prima).replace(/,/g, ""));
          porcentajePrimaProyecto = isFinite(np) ? np : null;
        }
        if (
          p.porcentaje_reserva !== undefined &&
          p.porcentaje_reserva !== null &&
          String(p.porcentaje_reserva) !== ""
        ) {
          var nr = parseFloat(String(p.porcentaje_reserva).replace(/,/g, ""));
          porcentajeReservaProyecto = isFinite(nr) ? nr : null;
        }
      }
      aplicarReservaYPrimaDesdeProyecto();
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

      function etiquetaLote(L) {
        var cod = L.codigo_display || L.codigo || "—";
        var est = (L.estado_label || L.estado || "").trim();
        if (!est || String(L.estado || "") === "DISPONIBLE") return cod;
        return cod + " · " + est;
      }

      function ocultarAlertaLote() {
        var box = document.getElementById("fmt-lote-estado-alerta");
        if (!box) return;
        box.hidden = true;
        box.textContent = "";
        box.className = "fmt-lote-alerta";
      }

      function pintarAlertaLote(opts) {
        var box = document.getElementById("fmt-lote-estado-alerta");
        if (!box) return;
        opts = opts || {};
        var msg = opts.mensaje || "";
        if (!msg) {
          ocultarAlertaLote();
          return;
        }
        var cls = "fmt-lote-alerta";
        if (opts.cls) cls += " " + opts.cls;
        box.className = cls;
        box.textContent = msg;
        box.hidden = false;
      }

      function mostrarAlertaLote(L) {
        if (!L) {
          ocultarAlertaLote();
          return false;
        }
        var est = String(L.estado || "").toUpperCase();
        if (est === "DISPONIBLE" || !est) {
          pintarAlertaLote({
            mensaje:
              "✓ Este lote figura DISPONIBLE. Consultando estado actual…",
            cls: "fmt-lote-alerta--disponible",
          });
          return false;
        }
        var msg = "";
        var cls = "fmt-lote-alerta";
        if (est === "VENDIDO") {
          msg =
            "⚠ Este lote ya está PAGADO TOTALMENTE / VENDIDO. No se puede ofrecer a otro cliente. Elija un lote disponible.";
          cls += " fmt-lote-alerta--vendido";
        } else if (est === "RESERVADO") {
          var quien = (L.cliente_reserva || "").trim() || "otro cliente";
          var hasta = L.reserva_hasta
            ? " (vence " +
              String(L.reserva_hasta).slice(0, 10).split("-").reverse().join("/") +
              ")"
            : "";
          msg =
            "⚠ Este lote ya está RESERVADO por " +
            quien +
            hasta +
            ". No lo ofrezca a otro comprador: elija un lote disponible o espere a que se libere.";
          cls += " fmt-lote-alerta--reservado";
        } else if (est === "BLOQUEADO") {
          msg =
            "⚠ Este lote está BLOQUEADO. Consulte con gerencia antes de usarlo.";
          cls += " fmt-lote-alerta--bloqueado";
        } else {
          msg =
            "⚠ Este lote no está disponible (" +
            (L.estado_label || est) +
            ").";
          cls += " fmt-lote-alerta--bloqueado";
        }
        pintarAlertaLote({ mensaje: msg, cls: cls.replace("fmt-lote-alerta ", "") });
        return true;
      }

      var estadoUrlTpl = "";
      try {
        var tplRaw = parseJSONScript("formato-lote-estado-url-tpl");
        if (typeof tplRaw === "string") estadoUrlTpl = tplRaw;
      } catch (e) {}
      var estadoAbort = null;
      var estadoSeq = 0;

      function sincronizarCatalogoDesdeApi(data) {
        if (!data || data.id == null) return null;
        var id = String(data.id);
        var L = porId[id] || {};
        L.id = data.id;
        L.codigo = data.codigo != null ? data.codigo : L.codigo;
        if (data.codigo_display != null) L.codigo_display = data.codigo_display;
        L.estado = data.estado;
        L.estado_label = data.estado_label;
        L.cliente_reserva = data.cliente_reserva || "";
        L.reserva_hasta = data.reserva_hasta || "";
        L.ocupado = !!data.ocupado;
        porId[id] = L;
        var opt = selLote.querySelector('option[value="' + id + '"]');
        if (opt) {
          opt.textContent = etiquetaLote(L);
          if (L.ocupado) opt.dataset.ocupado = "1";
          else delete opt.dataset.ocupado;
        }
        return L;
      }

      function consultarEstadoLoteVivo(invId, opts) {
        opts = opts || {};
        if (!estadoUrlTpl || !invId) return;
        if (estadoAbort) {
          try {
            estadoAbort.abort();
          } catch (e) {}
        }
        estadoAbort = typeof AbortController !== "undefined" ? new AbortController() : null;
        var seq = ++estadoSeq;
        var url = estadoUrlTpl.replace("__ID__", encodeURIComponent(String(invId)));
        pintarAlertaLote({
          mensaje: "Consultando si el lote sigue disponible…",
          cls: "fmt-lote-alerta--consultando",
        });
        fetch(url, {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
          signal: estadoAbort ? estadoAbort.signal : undefined,
          cache: "no-store",
        })
          .then(function (r) {
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.json();
          })
          .then(function (data) {
            if (seq !== estadoSeq) return;
            if (!data || !data.ok) throw new Error("respuesta inválida");
            var L = sincronizarCatalogoDesdeApi(data);
            var allowExisting = !!opts.allowExisting;
            if (data.disponible) {
              pintarAlertaLote({
                mensaje: data.mensaje,
                cls: "fmt-lote-alerta--disponible",
              });
              return;
            }
            pintarAlertaLote({
              mensaje: data.mensaje,
              cls:
                data.estado === "VENDIDO"
                  ? "fmt-lote-alerta--vendido"
                  : data.estado === "RESERVADO"
                    ? "fmt-lote-alerta--reservado"
                    : "fmt-lote-alerta--bloqueado",
            });
            if (!allowExisting) {
              hidLote.value = "";
              if (areaM2) areaM2.value = "";
              if (areaV2) areaV2.value = "";
              selLote.value = "";
              if (L) hidPol.value = L.poligono_nombre || hidPol.value;
            }
          })
          .catch(function (err) {
            if (err && err.name === "AbortError") return;
            if (seq !== estadoSeq) return;
            // Si falla la red, deja el aviso del catálogo local.
            var L = porId[String(invId)];
            if (L) mostrarAlertaLote(L);
            else
              pintarAlertaLote({
                mensaje:
                  "No se pudo consultar el estado en vivo. Intente de nuevo o elija otro lote.",
                cls: "fmt-lote-alerta--consultando",
              });
          });
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
          o.textContent = etiquetaLote(L);
          if (L.ocupado) {
            o.dataset.ocupado = "1";
          }
          selLote.appendChild(o);
        });
      }

      function formatMoneyLabel(raw) {
        var n = parseFloat(String(raw || "").replace(/,/g, ""));
        if (!isFinite(n)) return "—";
        try {
          return (
            "$" +
            n.toLocaleString("en-US", {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })
          );
        } catch (e) {
          return "$" + n.toFixed(2);
        }
      }

      function mostrarPreciosLote(L) {
        var panel = document.getElementById("pbr-precios-lote-panel");
        var lineLista = document.getElementById("pbr-precio-lista-line");
        var lineEtapa = document.getElementById("pbr-precio-etapa-line");
        var aviso = document.getElementById("pbr-precio-etapa-aviso");
        if (!panel || !lineLista || !lineEtapa) return;
        if (!L) {
          panel.hidden = true;
          if (aviso) {
            aviso.hidden = true;
            aviso.textContent = "";
          }
          return;
        }
        panel.hidden = false;
        var listaRaw = L.precio_lista != null && L.precio_lista !== "" ? L.precio_lista : "";
        lineLista.textContent = "Precio lista (referencia): " + formatMoneyLabel(listaRaw);
        var etapaNombre = L.etapa_label || "etapa actual";
        var precioVenta =
          L.precio_etapa != null && L.precio_etapa !== ""
            ? L.precio_etapa
            : L.precio != null && L.precio !== ""
              ? L.precio
              : "";
        var faltante = !!L.precio_etapa_faltante || !precioVenta;
        if (faltante) {
          lineEtapa.textContent =
            "Precio actual (" + etapaNombre + "): no definido en el lote";
          if (aviso) {
            aviso.hidden = false;
            aviso.textContent =
              "Complete «Precio contado — " +
              etapaNombre +
              "» en el inventario del lote. " +
              "No se usará el Precio lista como precio de venta.";
          }
        } else {
          lineEtapa.textContent =
            "Precio actual (" + etapaNombre + "): " + formatMoneyLabel(precioVenta) +
            " — este es el valor de venta del formato";
          if (aviso) {
            aviso.hidden = true;
            aviso.textContent = "";
          }
        }
        actualizarPrecioNegociadoInline();
      }

      function aplicarInmueble(invId, opts) {
        opts = opts || {};
        var allowExisting = !!opts.allowExisting;
        var L = porId[String(invId)];
        if (!L) return;
        var ocupado = mostrarAlertaLote(L);
        if (ocupado && !allowExisting) {
          // No rellenar el formato con un lote no disponible (catálogo local).
          hidLote.value = "";
          hidPol.value = L.poligono_nombre || "";
          if (areaM2) areaM2.value = "";
          if (areaV2) areaV2.value = "";
          selLote.value = "";
          mostrarPreciosLote(null);
          consultarEstadoLoteVivo(invId, opts);
          return;
        }
        hidLote.value = L.codigo_display || L.codigo || "";
        hidPol.value = L.poligono_nombre || "";
        if (areaM2) areaM2.value = L.area_m2 || "";
        if (areaV2) areaV2.value = L.area_v2 || "";

        var precioVenta =
          L.precio_etapa != null && L.precio_etapa !== ""
            ? L.precio_etapa
            : L.precio != null && L.precio !== ""
              ? L.precio
              : "";
        var faltante = !!L.precio_etapa_faltante || !precioVenta;
        var formRoot = document.getElementById("formato-aceptacion-form");
        var precioFijado =
          formRoot && formRoot.getAttribute("data-pbr-precio-fijado") === "1";
        var conservarPrecioVigente =
          allowExisting && (precioFijado || debeConservarPrecioVigente());
        if (valorInm) {
          if (!faltante && !conservarPrecioVigente) {
            var p = parseFloat(String(precioVenta).replace(/,/g, ""));
            if (isFinite(p)) setMoney(valorInm, p);
          } else if (!allowExisting) {
            setMoney(valorInm, 0);
            valorInm.value = "";
          }
        }
        var valorSis = document.getElementById("id_valor_inmueble_sistema");
        if (valorSis) {
          if (!faltante && !(allowExisting && precioFijado)) {
            var ps = parseFloat(String(precioVenta).replace(/,/g, ""));
            if (isFinite(ps)) setMoney(valorSis, ps);
          } else if (!allowExisting) {
            setMoney(valorSis, 0);
            valorSis.value = "";
          }
        }
        var etapaHid = document.getElementById("id_etapa_venta_aplicada");
        if (etapaHid && L.etapa_codigo) etapaHid.value = L.etapa_codigo;
        var etapaInfo = document.getElementById("pbr-etapa-venta-info");
        if (etapaInfo) {
          if (L.etapa_label) {
            etapaInfo.hidden = false;
            etapaInfo.textContent =
              "Etapa del proyecto: " +
              L.etapa_label +
              (L.etapa_rango ? " (" + L.etapa_rango + ")" : "") +
              (typeof L.comprometidos === "number"
                ? " · Comprometidos: " + L.comprometidos
                : "");
          } else {
            etapaInfo.hidden = true;
            etapaInfo.textContent = "";
          }
        }
        mostrarPreciosLote(L);
        if (L.proyecto_id) {
          var yaTieneReserva =
            allowExisting &&
            (precioFijado || debeConservarPrecioVigente() || isFinite(parseMoney(prima1)));
          if (yaTieneReserva) {
            // Edición: cargar config del proyecto sin pisar reserva/prima guardadas.
            var pCfg = proyectoPorId(L.proyecto_id);
            porcentajePrimaProyecto = null;
            porcentajeReservaProyecto = null;
            if (pCfg) {
              if (pCfg.porcentaje_prima) {
                var nm = parseFloat(String(pCfg.porcentaje_prima).replace(/,/g, ""));
                porcentajePrimaProyecto = isFinite(nm) ? nm : null;
              }
              if (pCfg.porcentaje_reserva) {
                var np = parseFloat(String(pCfg.porcentaje_reserva).replace(/,/g, ""));
                porcentajeReservaProyecto = isFinite(np) ? np : null;
              }
            }
            actualizarInfoPrimaProyecto();
          } else {
            setConfigFinancieraDesdeProyectoId(L.proyecto_id);
          }
        }
        if (conservarPrecioVigente) {
          restaurarPrecioVigente();
        } else {
          recalcFin();
        }
        // Consulta en vivo: otro vendedor pudo reservar el lote al mismo tiempo.
        consultarEstadoLoteVivo(invId, opts);
      }

      selPol.addEventListener("change", function () {
        var v = selPol.value;
        fillLotes(v);
        hidLote.value = "";
        ocultarAlertaLote();
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
          ocultarAlertaLote();
          mostrarPreciosLote(null);
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
          setConfigFinancieraDesdeProyectoId(id);
          fillPoligonos(id);
          ocultarAlertaLote();
        });
      }

      if (selProyecto && selProyecto.value) {
        fillPoligonos(selProyecto.value);
        setConfigFinancieraDesdeProyectoId(selProyecto.value);
      }

      function restoreLote() {
        var cod = hidLote && hidLote.value ? hidLote.value.trim() : "";
        var polName = hidPol && hidPol.value ? hidPol.value.trim() : "";
        if (!cod) return;
        var found = null;
        Object.keys(lotesPorClave).forEach(function (clave) {
          (lotesPorClave[clave] || []).forEach(function (L) {
            var disp = (L.codigo_display || L.codigo || "").trim();
            var raw = (L.codigo || "").trim();
            if (disp !== cod && raw !== cod) return;
            if (polName && L.poligono_nombre && L.poligono_nombre !== polName) return;
            if (!found) found = L;
          });
        });
        if (!found) return;
        var proyId = String(found.proyecto_id);
        if (selProyecto) selProyecto.value = proyId;
        fillPoligonos(proyId);
        selPol.value = found.clave_poligono;
        fillLotes(found.clave_poligono);
        if (String(found.clave_poligono).startsWith("np:")) {
          hidPol.value = "";
        } else {
          hidPol.value = found.poligono_nombre || "";
        }
        selLote.value = String(found.id);
        // Al editar un formato ya guardado, conservar el lote aunque esté reservado.
        aplicarInmueble(found.id, { allowExisting: true });
      }

      restoreLote();
      forzarActualizacionPlanCuotas(true);
    }

    [prima1, prima2, valorInm].forEach(function (el) {
      if (el) el.addEventListener("input", recalcFin);
      if (el) el.addEventListener("change", recalcFin);
    });
    if (prima1) {
      prima1.addEventListener("input", function () {
        // Si corrigen la reserva a mano, recalcular solo la prima a pagar.
        var vi = parseMoney(valorInm);
        if (
          porcentajePrimaProyecto != null &&
          isFinite(porcentajePrimaProyecto) &&
          isFinite(vi) &&
          vi > 0 &&
          prima2
        ) {
          var r = parseMoney(prima1);
          if (isFinite(r)) {
            var rest = (vi * porcentajePrimaProyecto) / 100 - r;
            if (rest < 0) rest = 0;
            setMoney(prima2, rest);
          }
        }
        actualizarInfoPrimaProyecto();
        recalcFin();
      });
      prima1.addEventListener("change", function () {
        var vi = parseMoney(valorInm);
        if (
          porcentajePrimaProyecto != null &&
          isFinite(porcentajePrimaProyecto) &&
          isFinite(vi) &&
          vi > 0 &&
          prima2
        ) {
          var r = parseMoney(prima1);
          if (isFinite(r)) {
            var rest = (vi * porcentajePrimaProyecto) / 100 - r;
            if (rest < 0) rest = 0;
            setMoney(prima2, rest);
          }
        }
        actualizarInfoPrimaProyecto();
        recalcFin();
      });
    }
    if (valorInm) {
      valorInm.addEventListener("change", function () {
        aplicarReservaYPrimaDesdeProyecto();
      });
    }
    // Si no hay selector pero sí nombre de proyecto, intentar resolver config.
    if ((!selProyecto || !selProyecto.value) && nomProyecto) {
      var nom = String(nomProyecto.value || "").trim().toLowerCase();
      if (nom) {
        for (var pi = 0; pi < proyectos.length; pi++) {
          if (String(proyectos[pi].nombre || "").trim().toLowerCase() === nom) {
            setConfigFinancieraDesdeProyectoId(proyectos[pi].id);
            break;
          }
        }
      }
    }
    actualizarInfoPrimaProyecto();
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

    if (tipoFin) {
      tipoFin.addEventListener("change", aplicarTipoFinanciamiento);
    }

    var formEl = document.getElementById("formato-aceptacion-form");
    if (formEl) {
      function etiquetaCampo(el) {
        if (!el) return "Campo obligatorio";
        var field = el.closest(".field") || el.closest(".formato-papel__serie-field");
        if (field) {
          var lab = field.querySelector(".field__label");
          if (lab && lab.textContent) return lab.textContent.trim();
        }
        if (el.id === "id_numero_formulario") return "Nº formulario";
        if (el.name) return el.name.replace(/_/g, " ");
        return "Campo obligatorio";
      }

      function camposInvalidos(form) {
        var vistos = [];
        var out = [];
        form.querySelectorAll(":invalid").forEach(function (el) {
          if (!el || el.disabled || el.type === "hidden") return;
          if (vistos.indexOf(el) >= 0) return;
          vistos.push(el);
          out.push({ el: el, label: etiquetaCampo(el) });
        });
        return out;
      }

      function syncCamposAntesDeGuardar() {
        if (window.PbrTelIntl && typeof window.PbrTelIntl.format === "function") {
          formEl.querySelectorAll('input[data-tel-intl="1"]').forEach(function (el) {
            if (!el.disabled && !el.readOnly) window.PbrTelIntl.format(el);
          });
        }
        formEl.querySelectorAll(".input-monto-us, .input-numero-us").forEach(function (el) {
          if (!el.disabled && !el.readOnly && el.value) {
            el.dispatchEvent(new Event("blur", { bubbles: true }));
          }
        });
        if (mapOk && selLote && selLote.value) {
          var Lsync = porId[String(selLote.value)];
          if (Lsync) {
            if (hidLote) hidLote.value = Lsync.codigo_display || Lsync.codigo || "";
            if (hidPol) hidPol.value = Lsync.poligono_nombre || "";
          }
        } else if (mapOk && selPol && selPol.value && hidPol && !String(hidPol.value || "").trim()) {
          var optPol = selPol.selectedOptions && selPol.selectedOptions[0];
          if (optPol) hidPol.value = (optPol.textContent || "").trim();
        }
      }

      function marcarInvalido(el) {
        if (!el) return;
        var field = el.closest(".field") || el.closest(".formato-papel__serie-field");
        if (field) field.classList.add("field--invalid");
      }

      formEl.addEventListener("submit", function (ev) {
        var alerta = document.getElementById("formato-guardar-alerta");
        formEl.querySelectorAll(".field--invalid").forEach(function (node) {
          node.classList.remove("field--invalid");
        });
        if (alerta) {
          alerta.hidden = true;
          alerta.textContent = "";
        }
        syncCamposAntesDeGuardar();
        // Los campos disabled no viajan en el POST; reactivar antes de guardar.
        setPlazosCamposEnabled(true);
        if (plazo && numCuota) {
          var yearsSync = parseInt(String(plazo.value || ""), 10);
          if (isFinite(yearsSync) && yearsSync >= 1 && yearsSync <= 6) {
            numCuota.value = String(yearsSync * 12);
          }
        }
        if (esContado()) {
          if (valorFin) setMoney(valorFin, 0);
          if (letra) letra.value = "";
          if (plazo) plazo.value = "";
          if (numCuota) numCuota.value = "";
          if (interes) interes.value = "";
        }
        var elaborado = document.getElementById("id_elaborado_por");
        if (elaborado && elaborado.required && !String(elaborado.value || "").trim()) {
          ev.preventDefault();
          marcarInvalido(elaborado);
          elaborado.scrollIntoView({ behavior: "smooth", block: "center" });
          try {
            elaborado.focus({ preventScroll: true });
          } catch (eLab) {
            elaborado.focus();
          }
          if (alerta) {
            alerta.hidden = false;
            alerta.innerHTML =
              "<strong>No se guardó.</strong> Seleccione el asesor de ventas (Elaborado por).";
          }
          return;
        }
        if (!esContado()) {
          if (plazo && !String(plazo.value || "").trim()) {
            ev.preventDefault();
            marcarInvalido(plazo);
            plazo.scrollIntoView({ behavior: "smooth", block: "center" });
            try {
              plazo.focus({ preventScroll: true });
            } catch (ePl) {
              plazo.focus();
            }
            if (alerta) {
              alerta.hidden = false;
              alerta.innerHTML =
                "<strong>No se guardó.</strong> Elija el plazo (años) del financiamiento.";
            }
            return;
          }
          var letraVal = parseMoney(letra);
          if (!letraVal || letraVal <= 0) {
            ev.preventDefault();
            marcarInvalido(letra);
            if (letra) letra.scrollIntoView({ behavior: "smooth", block: "center" });
            try {
              if (letra) letra.focus({ preventScroll: true });
            } catch (eLt) {
              if (letra) letra.focus();
            }
            if (alerta) {
              alerta.hidden = false;
              alerta.innerHTML =
                "<strong>No se guardó.</strong> Escriba la cuota de los meses 1–12 (sin interés).";
            }
            return;
          }
        }
        formEl.checkValidity();
        var invalidos = camposInvalidos(formEl);
        if (invalidos.length) {
          ev.preventDefault();
          var primero = invalidos[0].el;
          marcarInvalido(primero);
          primero.scrollIntoView({ behavior: "smooth", block: "center" });
          try {
            primero.focus({ preventScroll: true });
          } catch (e1) {
            try {
              primero.focus();
            } catch (e2) {}
          }
          try {
            formEl.reportValidity();
          } catch (e3) {}
          if (alerta) {
            alerta.hidden = false;
            var lista = invalidos
              .slice(0, 4)
              .map(function (x) {
                return x.label;
              })
              .join(", ");
            alerta.textContent =
              "Complete: " +
              lista +
              (invalidos.length > 4 ? "…" : "") +
              ". La pantalla subió al primer campo pendiente.";
          }
          return;
        }
        var btn = document.getElementById("formato-guardar-btn");
        // Safari/iOS cancela el POST si deshabilitamos el botón en el mismo tick del submit.
        if (btn && !btn.disabled) {
          window.setTimeout(function () {
            btn.disabled = true;
            btn.textContent = "Guardando…";
          }, 0);
        }
      });
    }

    aplicarTipoFinanciamiento();

    function nCuotasDesdeFormulario() {
      if (plazo && plazo.value) {
        var y = parseInt(String(plazo.value).trim(), 10);
        if (isFinite(y) && y >= 1 && y <= 6) {
          var nPlazo = y * 12;
          if (numCuota) numCuota.value = String(nPlazo);
          return nPlazo;
        }
      }
      var raw = numCuota && numCuota.value ? String(numCuota.value).trim() : "";
      if (raw && /^\d+$/.test(raw)) {
        var n = parseInt(raw, 10);
        if (n >= 12 && n <= 72 && n % 12 === 0) return n;
      }
      return null;
    }

    function letraParaListado(n) {
      var L = parseMoney(letra);
      if (isFinite(L) && L > 0) return L;
      var vf = principalFinanciamiento();
      if (isFinite(vf) && vf > 0 && n > 0) return Math.round((vf / n) * 100) / 100;
      return null;
    }

    function sincronizarCamposFinancierosBruto() {
      if (formRoot && formRoot.getAttribute("data-pbr-validacion-precio") === "APROBADO") {
        restaurarPrecioVigente();
      }
      if (plazo && plazo.value) {
        var y = parseInt(String(plazo.value).trim(), 10);
        if (isFinite(y) && y >= 1 && y <= 6 && numCuota) {
          numCuota.value = String(y * 12);
        }
      }
      principalFinanciamiento();
    }

    function renderListadoDesdeServidor(plan) {
      if (!tbodyListado || !plan || !plan.length) return false;
      tbodyListado.innerHTML = "";
      plan.forEach(function (row) {
        var tr = document.createElement("tr");
        var montoStr = "—";
        if (row.monto) {
          var m = parseFloat(String(row.monto).replace(/,/g, ""));
          montoStr = isFinite(m) && m > 0 ? fmtMoney(m) : "—";
        }
        tr.innerHTML =
          "<td style=\"padding:0.35rem 0.5rem;border:1px solid #e2e8f0;\">" +
          (row.linea || "") +
          "</td><td style=\"padding:0.35rem 0.5rem;border:1px solid #e2e8f0;\">" +
          (row.concepto || "") +
          "</td><td style=\"padding:0.35rem 0.5rem;border:1px solid #e2e8f0;\">" +
          (row.fecha || "—") +
          "</td><td style=\"padding:0.35rem 0.5rem;border:1px solid #e2e8f0;text-align:right;\">" +
          montoStr +
          "</td>";
        tbodyListado.appendChild(tr);
      });
      return true;
    }

    function forzarActualizacionPlanCuotas(preferirServidor) {
      sincronizarCamposFinancierosBruto();
      if (
        preferirServidor !== false &&
        planCuotasServidor &&
        planCuotasServidor.length &&
        !usuarioEditoPlan
      ) {
        renderListadoDesdeServidor(planCuotasServidor);
        actualizarResumenPlan();
        actualizarPrecioNegociadoInline();
        return;
      }
      rebuildListadoCuotas();
      actualizarPrecioNegociadoInline();
    }

    function marcarPlanEditadoPorUsuario() {
      if (actualizacionProgramatica) return;
      usuarioEditoPlan = true;
      rebuildListadoCuotas();
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
        appendRow("Reserva", fmtDMY(f1), p1 > 0 ? fmtMoney(p1) : "—");
      }
      if (p2 > 0 || f2) {
        appendRow("Prima a pagar", fmtDMY(f2), p2 > 0 ? fmtMoney(p2) : "—");
      }

      var n = nCuotasDesdeFormulario();
      var fecha0 =
        (fechaPrimera && fechaPrimera.value ? parseDateInputValue(fechaPrimera.value) : null) ||
        (fechaPagoMensual && fechaPagoMensual.value ? parseDateInputValue(fechaPagoMensual.value) : null);
      if (n && !esContado()) {
        var principal = principalFinanciamiento();
        var interVal = parseInteresAnual(interes);
        var letraVal = parseMoney(letra);
        if (!isFinite(letraVal) || letraVal <= 0) letraVal = letraParaListado(n);
        if (!isFinite(letraVal) || letraVal <= 0 || !isFinite(principal) || principal <= 0) {
          var trWarn = document.createElement("tr");
          trWarn.innerHTML =
            "<td colspan=\"4\" class=\"muted\" style=\"padding:0.45rem 0.5rem;border:1px solid #e2e8f0;font-size:0.82rem;\">" +
            "Complete valor del inmueble, primas, plazo y cuota meses 1–12 para ver el plan.</td>";
          tbodyListado.appendChild(trWarn);
          actualizarResumenPlan();
          return;
        }
        var plan = planCuotasAPlazos(principal, letraVal, interVal, n);
        var i;
        for (i = 0; i < n; i += 1) {
          var vd = fecha0 ? addMonthsDate(fecha0, i) : null;
          var num = i + 1;
          var concepto;
          var monto;
          if (num <= 12 || plan.cuota13 === null) {
            concepto = "Cuota " + num + " (sin interés — cuota del vendedor)";
            monto = plan.letra;
          } else {
            concepto = "Cuota " + num + " (con interés " + interVal + "%)";
            monto = plan.cuota13;
          }
          appendRow(concepto, fmtDMY(vd), monto !== null ? fmtMoney(monto) : "—");
        }
      }

      if (linea === 0) {
        var tr0 = document.createElement("tr");
        tr0.innerHTML =
          "<td colspan=\"4\" class=\"muted\" style=\"padding:0.45rem 0.5rem;border:1px solid #e2e8f0;font-size:0.82rem;\">" +
          "Indique primas, fecha de primera cuota, plazo (1–6 años) y escriba la cuota de los meses 1–12 (sin interés). " +
          "Desde el mes 13: saldo restante (tras reserva, prima y 12 cuotas) repartido con interés.</td>";
        tbodyListado.appendChild(tr0);
      }
      actualizarResumenPlan();
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
      interes,
      tipoFin,
    ];
    listadoWatch.forEach(function (el) {
      if (!el) return;
      el.addEventListener("input", marcarPlanEditadoPorUsuario);
      el.addEventListener("change", marcarPlanEditadoPorUsuario);
    });

    // Reformatear montos al salir del campo (22,500.00)
    [valorInm, prima1, prima2, valorFin, letra].forEach(function (el) {
      if (!el) return;
      el.addEventListener("blur", function () {
        var n = parseMoney(el);
        if (String(el.value || "").trim() !== "") setMoney(el, n);
      });
    });

    forzarActualizacionPlanCuotas(true);
    window.setTimeout(function () {
      forzarActualizacionPlanCuotas(true);
    }, 150);
    window.setTimeout(function () {
      forzarActualizacionPlanCuotas(true);
    }, 800);
  });
})();