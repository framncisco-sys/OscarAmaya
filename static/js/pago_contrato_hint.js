(function () {
  "use strict";

  var sel = document.getElementById("id_contrato");
  var panel = document.getElementById("pago-contrato-resumen");
  var conceptoSel = document.getElementById("id_concepto");
  var cuotasN = document.getElementById("id_cuotas_incluidas");
  var wrapCuotasN = document.getElementById("pago-field-cuotas-n");
  var elFecha = document.getElementById("id_fecha");
  var elMonto = document.getElementById("id_monto");

  if (!sel || !panel) return;

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

  function update() {
    var opt = sel.selectedOptions[0];
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
    var elCuota = document.getElementById("pago-hint-cuota");
    if (elCuota) {
      elCuota.textContent = cm ? "$" + cm : "No definida / sin financiamiento";
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

    var aplic = document.getElementById("pago-hint-aplicacion-cuota");
    if (!aplic) return;

    if (!esCuota) {
      aplic.textContent =
        "Concepto distinto de «Cuota de financiamiento»: este movimiento no liquida automáticamente una fila del calendario de cuotas.";
      aplic.style.color = "#475569";
      return;
    }

    if (nTotal === 0) {
      aplic.textContent =
        "Concepto «Cuota»: aún no hay filas en el calendario de este contrato. Cárguelas en «Contratos» → «Editar» ese contrato → sección «Cuotas programadas (calendario)» al final del formulario, luego vuelva a registrar el pago.";
      aplic.style.color = "#b45309";
      return;
    }

    var pend = parsePendientes(opt);
    var kMax = pend.length > 0 ? Math.min(60, pend.length) : 1;
    var k = cuotasN ? Math.max(1, Math.min(parseInt10(cuotasN.value) || 1, kMax)) : 1;
    if (cuotasN) {
      cuotasN.value = String(k);
      cuotasN.setAttribute("max", String(Math.max(1, pend.length)));
    }

    if (pend.length === 0) {
      aplic.textContent =
        "No hay cuotas pendientes de cobro en orden para este contrato (o ya están pagadas).";
      aplic.style.color = "#b91c1c";
      return;
    }

    var slice = pend.slice(0, k);
    var n0 = slice[0].n;
    var n1 = slice[slice.length - 1].n;
    var sumTxt = sumDecimalStrings(slice).toFixed(2);
    aplic.innerHTML =
      "Liquidará <strong>" +
      k +
      "</strong> cuota(s) consecutiva(s) en orden de vencimiento: n.º <strong>" +
      n0 +
      "</strong>" +
      (k > 1 ? " al <strong>" + n1 + "</strong>" : "") +
      ". Monto sugerido: <strong>$" +
      sumTxt +
      "</strong>. La fecha del pago se rellenó con el vencimiento de la primera de ese grupo (cámbiela si el ingreso fue otro día).";
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
  if (conceptoSel) conceptoSel.addEventListener("change", update);
  if (cuotasN) cuotasN.addEventListener("input", update);
  if (cuotasN) cuotasN.addEventListener("change", update);
  update();
})();
