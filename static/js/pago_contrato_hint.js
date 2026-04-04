(function () {
  "use strict";

  var sel = document.getElementById("id_contrato");
  var selFmt = document.getElementById("id_formato_aceptacion");
  var panel = document.getElementById("pago-contrato-resumen");
  var conceptoSel = document.getElementById("id_concepto");
  var cuotasN = document.getElementById("id_cuotas_incluidas");
  var wrapCuotasN = document.getElementById("pago-field-cuotas-n");
  var elFecha = document.getElementById("id_fecha");
  var elMonto = document.getElementById("id_monto");

  if (!sel || !panel) return;

  var tablaWrap = document.getElementById("pago-cuotas-tabla-wrap");
  var useTablaCuotas = tablaWrap && tablaWrap.getAttribute("data-enabled") === "1";

  var isEdit = /\/pagos\/\d+\/editar\//.test(window.location.pathname);
  var primeraEjecucion = true;

  function parseInt10(s) {
    var n = parseInt(String(s || "0"), 10);
    return isNaN(n) ? 0 : n;
  }

  function formatDate(iso) {
    if (!iso) return "—";
    var p = String(iso).split("-");
    if (p.length === 3) return p[2] + "/" + p[1] + "/" + p[0];
    return iso;
  }

  function parsePendientes(opt) {
    var raw = opt.getAttribute("data-pendientes-json");
    if (!raw) return [];
    try {
      var t = document.createElement("textarea");
      t.innerHTML = raw;
      return JSON.parse(t.value);
    } catch (e) {
      return [];
    }
  }

  function sumDecimalStrings(slice) {
    var t = 0;
    for (var i = 0; i < slice.length; i++) {
      t += parseFloat(String(slice[i].m).replace(",", ".")) || 0;
    }
    return Math.round(t * 100) / 100;
  }

  function setSpan(id, text) {
    var e = document.getElementById(id);
    if (e) e.textContent = text && String(text).trim() ? text : "—";
  }

  function getPanelOpt() {
    if (selFmt && selFmt.value) {
      var fo = selFmt.selectedOptions[0];
      if (fo && fo.getAttribute("data-cuotas-todas-json") != null) {
        return fo;
      }
    }
    if (!sel) return null;
    return sel.selectedOptions[0];
  }

  function populateFormato(opt) {
    var box = document.getElementById("pago-formato-aceptacion");
    var link = document.getElementById("pago-fmt-link");
    var btnLetra = document.getElementById("pago-fmt-usar-letra");
    if (!box) return;
    var fid = opt && opt.getAttribute("data-formato-id");
    if (!fid) {
      box.style.display = "none";
      if (link) {
        link.style.display = "none";
        link.href = "#";
      }
      if (btnLetra) btnLetra.style.display = "none";
      return;
    }
    box.style.display = "block";
    setSpan("pago-fmt-num", opt.getAttribute("data-formato-numero"));
    var lett = opt.getAttribute("data-formato-letra-mensual") || "";
    var url = opt.getAttribute("data-formato-edit-url") || "";
    if (link) {
      if (url) {
        link.href = url;
        link.style.display = "inline";
      } else {
        link.style.display = "none";
      }
    }
    if (btnLetra) {
      btnLetra.style.display = lett ? "inline-block" : "none";
    }
  }

  function syncContratoDesdeFormato() {
    if (!selFmt || !sel) return;
    var fo = selFmt.selectedOptions[0];
    if (selFmt.value && fo) {
      var cid = fo.getAttribute("data-contrato-id");
      if (cid) {
        sel.value = cid;
        return;
      }
    }
    var flags = document.getElementById("pago-form-flags");
    if (flags && flags.getAttribute("data-ocultar-contrato") === "1" && !selFmt.value) {
      sel.value = "";
    }
  }

  var btnUsarLetra = document.getElementById("pago-fmt-usar-letra");
  if (btnUsarLetra && elMonto) {
    btnUsarLetra.addEventListener("click", function () {
      var opt = getPanelOpt();
      if (!opt) return;
      var lett = opt.getAttribute("data-formato-letra-mensual") || "";
      if (lett) elMonto.value = lett;
    });
  }

  function update() {
    syncContratoDesdeFormato();
    var opt = getPanelOpt();
    if (!opt || !opt.value) {
      panel.style.display = "none";
      return;
    }
    panel.style.display = "block";

    var esCuota =
      conceptoSel && String(conceptoSel.value || "").toUpperCase() === "CUOTA";
    if (wrapCuotasN) {
      wrapCuotasN.style.display = esCuota ? "" : "none";
    }

    var cliente = opt.getAttribute("data-cliente") || "";
    var cnum = opt.getAttribute("data-contrato-numero") || "";
    var elCli = document.getElementById("pago-hint-cliente");
    var elCnum = document.getElementById("pago-hint-contrato-num");
    if (elCli) elCli.textContent = cliente || "—";
    if (elCnum) elCnum.textContent = cnum || "—";

    var fpl = opt.getAttribute("data-formato-plazo") || "";
    var fnc = opt.getAttribute("data-formato-num-cuotas") || "";
    var fin = opt.getAttribute("data-formato-interes") || "";
    var elFmtFin = document.getElementById("pago-hint-fmt-fin");
    if (elFmtFin) {
      var parts = [fpl, fnc, fin].filter(function (p) {
        return p && String(p).trim();
      });
      elFmtFin.textContent = parts.length
        ? parts.join(" · ")
        : "— (sin formato vinculado)";
    }

    var nTotal = parseInt10(opt.getAttribute("data-n-cuotas-total"));
    var nPag = parseInt10(opt.getAttribute("data-n-cuotas-pagadas"));
    var elCnt = document.getElementById("pago-hint-cuotas-contador");
    if (elCnt) {
      if (nTotal === 0) {
        elCnt.textContent = "Sin cuotas programadas en este contrato";
      } else {
        elCnt.textContent =
          nPag +
          " pagada" +
          (nPag === 1 ? "" : "s") +
          " de " +
          nTotal +
          " en el plan";
      }
    }

    var cm = opt.getAttribute("data-cuota-mensual") || "";
    var cmFuente = opt.getAttribute("data-cuota-mensual-fuente") || "";
    var elCuota = document.getElementById("pago-hint-cuota");
    if (elCuota) {
      if (cm) {
        var suf =
          cmFuente === "formato"
            ? " (formato de aceptación)"
            : cmFuente === "contrato"
              ? " (estimada del contrato; sin letra en formato)"
              : "";
        elCuota.textContent = "$" + cm + suf;
      } else {
        elCuota.textContent = "— (defina letra en el formato o cuota en el contrato)";
      }
    }

    var pv = opt.getAttribute("data-prox-vence") || "";
    var pm = opt.getAttribute("data-prox-monto") || "";
    var pn = opt.getAttribute("data-prox-numero") || "";
    var elV = document.getElementById("pago-hint-vence");
    var elM = document.getElementById("pago-hint-cuota-monto");
    var elN = document.getElementById("pago-hint-nro");
    if (elV) elV.textContent = formatDate(pv);
    if (elM) elM.textContent = pm ? "$" + pm : "—";
    if (elN) elN.textContent = pn || "—";

    populateFormato(opt);

    var aplic = document.getElementById("pago-hint-aplicacion-cuota");
    if (!aplic) return;

    var fmtLetra = opt.getAttribute("data-formato-letra-mensual") || "";

    if (!esCuota) {
      var nPlan = parseInt10(opt.getAttribute("data-n-cuotas-total"));
      if (useTablaCuotas && nPlan > 0) {
        aplic.innerHTML =
          "Concepto distinto de «Cuota de financiamiento»: la <strong>tabla de abajo</strong> muestra el plan de cuotas solo como referencia (sin marcar pagos). " +
          "Para liquidar cuotas en el calendario elija <strong>Cuota de financiamiento</strong> y marque las casillas desde la primera pendiente.";
      } else {
        aplic.innerHTML =
          "Concepto distinto de «Cuota de financiamiento»: este movimiento no liquida el calendario de cuotas. " +
          "Si elige <strong>Cuota de financiamiento</strong>, podrá marcar cuotas en la tabla y ajustar monto y fecha.";
      }
      aplic.style.color = "#475569";
      return;
    }

    if (nTotal === 0) {
      aplic.innerHTML =
        "Concepto «Cuota»: aún no hay filas en el calendario de este contrato. Cárguelas en «Contratos» → «Editar» → «Cuotas programadas (calendario)»." +
        (fmtLetra
          ? " Letra mensual en <strong>formato de aceptación</strong>: <strong>$" +
            fmtLetra +
            "</strong> (referencia documental hasta tener calendario)."
          : "");
      aplic.style.color = "#b45309";
      return;
    }

    var pend = parsePendientes(opt);
    var kMax = pend.length > 0 ? Math.min(200, pend.length) : 1;
    var k = cuotasN ? Math.max(1, Math.min(parseInt10(cuotasN.value) || 1, kMax)) : 1;
    if (cuotasN) {
      cuotasN.value = String(k);
      cuotasN.setAttribute("max", String(Math.max(1, pend.length)));
    }

    if (pend.length === 0) {
      aplic.innerHTML =
        "Concepto «Cuota»: no hay cuotas pendientes en el calendario (puede que ya estén pagadas). No podrá guardar como cuota hasta que existan filas pendientes." +
        (fmtLetra
          ? " Letra en formato de aceptación: <strong>$" + fmtLetra + "</strong>."
          : "");
      aplic.style.color = "#b91c1c";
      primeraEjecucion = false;
      return;
    }

    if (useTablaCuotas) {
      aplic.innerHTML =
        "Concepto «Cuota»: use la <strong>tabla de cuotas</strong> debajo para marcar la(s) que liquida este pago (consecutivas desde la primera pendiente). El monto y la fecha se ajustan al grupo marcado.";
      aplic.style.color = "#0f766e";
      primeraEjecucion = false;
      return;
    }

    var slice = pend.slice(0, k);
    var n0 = slice[0].n;
    var n1 = slice[slice.length - 1].n;
    var sumTxt = sumDecimalStrings(slice).toFixed(2);
    var refFmt =
      fmtLetra && fmtLetra !== sumTxt
        ? " (Letra en formato de aceptación: $" + fmtLetra + " — el monto aplicado sigue el calendario.)"
        : "";
    aplic.innerHTML =
      "Liquidará <strong>" +
      k +
      "</strong> cuota(s) consecutiva(s) en orden de vencimiento: n.º <strong>" +
      n0 +
      "</strong>" +
      (k > 1 ? " al <strong>" + n1 + "</strong>" : "") +
      ". Monto sugerido: <strong>$" +
      sumTxt +
      "</strong>. La fecha del pago se rellenó con el vencimiento de la primera de ese grupo (cámbiela si el ingreso fue otro día)." +
      refFmt;
    aplic.style.color = "#0f766e";

    var puedeAutollenar = !isEdit || !primeraEjecucion;
    if (puedeAutollenar) {
      if (elFecha && slice[0].v) {
        elFecha.value = slice[0].v;
      }
      if (elMonto) {
        elMonto.value = sumTxt;
      }
    }
    primeraEjecucion = false;
  }

  sel.addEventListener("change", update);
  if (selFmt) selFmt.addEventListener("change", update);
  if (conceptoSel) conceptoSel.addEventListener("change", update);
  if (cuotasN) cuotasN.addEventListener("input", update);
  if (cuotasN) cuotasN.addEventListener("change", update);
  update();
})();
