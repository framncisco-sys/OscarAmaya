(function () {
  "use strict";

  var selFmt = document.getElementById("id_formato_aceptacion");
  var selCt = document.getElementById("id_contrato");
  var conceptoSel = document.getElementById("id_concepto");
  var hiddenIds = document.getElementById("id_cuotas_seleccionadas");
  var hiddenN = document.getElementById("id_cuotas_incluidas");
  var hiddenRecargo = document.getElementById("id_monto_recargo_incluido");
  var wrap = document.getElementById("pago-cuotas-tabla-wrap");
  var tbody = document.getElementById("pago-cuotas-tabla-body");
  var vacio = document.getElementById("pago-cuotas-vacio");
  var elFecha = document.getElementById("id_fecha");
  var elMonto = document.getElementById("id_monto");
  var elRef = document.getElementById("id_referencia");

  if (!wrap || !tbody || wrap.getAttribute("data-enabled") !== "1") {
    return;
  }

  function parseJsonAttr(opt, name) {
    var raw = opt && opt.getAttribute(name);
    if (!raw) return [];
    try {
      var t = document.createElement("textarea");
      t.innerHTML = raw;
      return JSON.parse(t.value);
    } catch (e) {
      return [];
    }
  }

  function formatDate(iso) {
    if (!iso) return "—";
    var p = String(iso).split("-");
    if (p.length === 3) return p[2] + "/" + p[1] + "/" + p[0];
    return iso;
  }

  function estadoLabel(e) {
    if (e === "PAGADA") return "Pagada";
    if (e === "VENCIDA") return "Vencida";
    return "Pendiente";
  }

  function buildReferenciaCuotas(nums) {
    if (!nums.length) return "";
    if (nums.length === 1) return "PAGO DE CUOTA " + nums[0];
    return "PAGO DE CUOTA " + nums[0] + "-" + nums[nums.length - 1];
  }

  function isAutoReferencia(val) {
    var s = String(val || "").trim();
    if (!s) return true;
    return /^PAGO DE CUOTA\s+\d+(-\d+)?$/i.test(s);
  }

  function syncReferencia(openChecksPrefix, rowsByIdx) {
    var ref = elRef || document.getElementById("id_referencia");
    if (!ref || !isCuotaConcept()) return;
    if (!isAutoReferencia(ref.value)) return;
    var nums = [];
    for (var i = 0; i < openChecksPrefix.length; i++) {
      var ix = parseInt(openChecksPrefix[i].dataset.idx, 10);
      var r = rowsByIdx[ix];
      if (r && r.n != null && r.n !== "") nums.push(r.n);
    }
    ref.value = buildReferenciaCuotas(nums);
    elRef = ref;
  }

  function getPanelOpt() {
    if (selFmt && selFmt.value && selFmt.selectedOptions[0]) {
      var fo = selFmt.selectedOptions[0];
      if (fo.getAttribute("data-cuotas-todas-json") != null) {
        return fo;
      }
    }
    if (selCt && selCt.selectedOptions[0] && selCt.value) {
      return selCt.selectedOptions[0];
    }
    return null;
  }

  function getAllCuotas() {
    var opt = getPanelOpt();
    if (!opt) return [];
    return parseJsonAttr(opt, "data-cuotas-todas-json") || [];
  }

  function getRecargoMonto() {
    var opt = getPanelOpt();
    if (!opt) return 0;
    return parseFloat(String(opt.getAttribute("data-recargo-monto") || "0").replace(",", ".")) || 0;
  }

  function getRecargoParams() {
    var opt = getPanelOpt();
    var unit =
      parseFloat(
        String(
          (wrap && wrap.getAttribute("data-recargo-unitario")) ||
            (opt && opt.getAttribute("data-recargo-unitario")) ||
            "0"
        ).replace(",", ".")
      ) || 0;
    var gracia = parseInt(
      String(
        (wrap && wrap.getAttribute("data-dias-gracia")) ||
          (opt && opt.getAttribute("data-dias-gracia")) ||
          "0"
      ),
      10
    );
    if (isNaN(gracia)) gracia = 0;
    return { unit: unit, gracia: gracia };
  }

  function parseISODate(s) {
    var p = String(s || "").split("-");
    if (p.length !== 3) return null;
    var y = parseInt(p[0], 10);
    var m = parseInt(p[1], 10);
    var d = parseInt(p[2], 10);
    if (!y || !m || !d) return null;
    return new Date(y, m - 1, d);
  }

  function calcRecargoSeleccionado(openChecksPrefix, rowsByIdx) {
    var params = getRecargoParams();
    if (!(params.unit > 0)) return getRecargoMonto();
    var fecha = elFecha ? parseISODate(elFecha.value) : null;
    if (!fecha) return getRecargoMonto();
    // Regla: la última cuota marcada (la «actual») no carga recargo aquí;
    // el atraso de esa cuota se cobra en la siguiente. Las anteriores sí.
    var n = 0;
    var last = openChecksPrefix.length - 1;
    for (var i = 0; i < openChecksPrefix.length; i++) {
      if (i === last) continue;
      var ix = parseInt(openChecksPrefix[i].dataset.idx, 10);
      var r = rowsByIdx[ix];
      if (!r || !r.v) continue;
      var vence = parseISODate(r.v);
      if (!vence) continue;
      var limite = new Date(vence.getTime());
      limite.setDate(limite.getDate() + params.gracia);
      if (fecha > limite) n += 1;
    }
    var porSeleccion = Math.round(n * params.unit * 100) / 100;
    // Catálogo: recargos por atrasos ya pagados de meses anteriores.
    var catalogo = getRecargoMonto();
    return Math.max(porSeleccion, catalogo);
  }

  function syncRecargoParamsFromOpt() {
    var opt = getPanelOpt();
    if (!wrap || !opt) return;
    var u = opt.getAttribute("data-recargo-unitario");
    var g = opt.getAttribute("data-dias-gracia");
    if (u != null) wrap.setAttribute("data-recargo-unitario", u);
    if (g != null) wrap.setAttribute("data-dias-gracia", g);
  }

  function isCuotaConcept() {
    if (conceptoSel && String(conceptoSel.value || "").toUpperCase() === "CUOTA") {
      return true;
    }
    // Flujo Paso 6: concepto fijo en URL aunque el select falle.
    try {
      var q = new URLSearchParams(window.location.search);
      return String(q.get("concepto") || "").toUpperCase() === "CUOTA";
    } catch (e) {
      return false;
    }
  }

  function money(n) {
    return (Math.round(n * 100) / 100).toFixed(2);
  }

  function updateHiddens(openChecksPrefix, rowsByIdx) {
    if (!hiddenIds || !hiddenN) return;
    var ids = [];
    for (var i = 0; i < openChecksPrefix.length; i++) {
      ids.push(openChecksPrefix[i].dataset.cuotaId);
    }
    hiddenIds.value = ids.join(",");
    hiddenN.value = ids.length ? String(ids.length) : "1";

    var sum = 0;
    for (var j = 0; j < openChecksPrefix.length; j++) {
      var ix = parseInt(openChecksPrefix[j].dataset.idx, 10);
      var r = rowsByIdx[ix];
      if (r) sum += parseFloat(String(r.m).replace(",", ".")) || 0;
    }
    sum = Math.round(sum * 100) / 100;
    syncRecargoParamsFromOpt();
    var recargo = openChecksPrefix.length
      ? calcRecargoSeleccionado(openChecksPrefix, rowsByIdx)
      : 0;
    recargo = Math.round(recargo * 100) / 100;
    if (hiddenRecargo) {
      hiddenRecargo.value = money(recargo);
    }
    var sugerido = Math.round((sum + recargo) * 100) / 100;
    wrap.setAttribute("data-suma-cuotas", openChecksPrefix.length ? String(sum) : "0");
    wrap.setAttribute("data-recargo", String(recargo));
    wrap.setAttribute("data-sugerido", openChecksPrefix.length ? String(sugerido) : "0");

    if (isCuotaConcept() && elMonto) {
      var actual = parseFloat(String(elMonto.value || "").replace(",", ".")) || 0;
      if (!openChecksPrefix.length) {
        elMonto.value = "";
      } else if (actual > sugerido + 0.0001) {
        elMonto.value = money(actual);
      } else {
        elMonto.value = money(sugerido);
      }
    }
    // Fecha del movimiento = día en que se recibió el dinero (hoy),
    // NUNCA el vencimiento de la cuota (eso es otra columna del calendario).
    if (isCuotaConcept() && openChecksPrefix.length && elFecha) {
      if (!String(elFecha.value || "").trim()) {
        var now = new Date();
        var mm = String(now.getMonth() + 1).padStart(2, "0");
        var dd = String(now.getDate()).padStart(2, "0");
        elFecha.value = now.getFullYear() + "-" + mm + "-" + dd;
      }
    }
    syncReferencia(openChecksPrefix, rowsByIdx);
    actualizarHintExcedente(sum, recargo);
  }

  function actualizarHintExcedente(sumaCuotas, recargoOpt) {
    var el = document.getElementById("pago-hint-excedente-capital");
    if (!el) return;
    if (!isCuotaConcept() || !elMonto) {
      el.style.display = "none";
      el.textContent = "";
      return;
    }
    var suma =
      typeof sumaCuotas === "number"
        ? sumaCuotas
        : parseFloat(wrap.getAttribute("data-suma-cuotas") || "0") || 0;
    var recargo =
      typeof recargoOpt === "number"
        ? recargoOpt
        : parseFloat(wrap.getAttribute("data-recargo") || "0") || 0;
    var base = Math.round((suma + recargo) * 100) / 100;
    var total = parseFloat(String(elMonto.value || "").replace(",", ".")) || 0;
    var exc = Math.round((total - base) * 100) / 100;
    if (suma > 0 && (exc > 0.009 || recargo > 0.009)) {
      el.style.display = "block";
      var partes = ["cuota(s) $" + money(suma)];
      if (recargo > 0.009) {
        partes.push("recargo $" + money(recargo) + " (no capital)");
      }
      if (exc > 0.009) {
        partes.push("capital $" + money(exc));
      }
      el.innerHTML =
        "Desglose del recibo: <strong>" +
        partes.join(" + ") +
        "</strong> = <strong>$" +
        money(total) +
        "</strong>. Solo cuota(s) y capital reducen el saldo.";
    } else {
      el.style.display = "none";
      el.textContent = "";
    }
  }

  function normalizeSelection() {
    var rows = getAllCuotas();
    var checks = tbody.querySelectorAll('input[type="checkbox"][data-cuota-id]');
    var openChecks = [];
    for (var i = 0; i < checks.length; i++) {
      if (!checks[i].disabled) openChecks.push(checks[i]);
    }

    var rowsByIdx = {};
    for (var r = 0; r < rows.length; r++) rowsByIdx[r] = rows[r];

    if (!openChecks.length) {
      updateHiddens([], rowsByIdx);
      actualizarColumnasSeleccion();
      return;
    }

    var k = 0;
    for (var j = 0; j < openChecks.length; j++) {
      if (openChecks[j].checked) k = j + 1;
      else break;
    }
    for (var j2 = k; j2 < openChecks.length; j2++) {
      openChecks[j2].checked = false;
    }

    var prefix = openChecks.slice(0, k);
    updateHiddens(prefix, rowsByIdx);
    actualizarColumnasSeleccion();
  }

  function rebuildTable() {
    tbody.innerHTML = "";
    var rows = getAllCuotas();
    var thAcc = document.getElementById("pago-cuotas-th-accion");
    var esCuota = isCuotaConcept();
    var opt = getPanelOpt();

    if (vacio) {
      if (!opt || !opt.value) {
        vacio.style.display = "block";
        vacio.textContent =
          "Elija un formato de aceptación guardado para ver las cuotas pendientes y generar el recibo.";
      } else if (!rows.length) {
        vacio.style.display = "block";
        vacio.textContent =
          "Este contrato aún no tiene cuotas en el calendario. Cree el plan de pagos (paso 4) o cargue cuotas programadas en el contrato.";
      } else {
        vacio.style.display = "none";
        vacio.textContent = "";
      }
    }

    if (!rows.length) {
      if (hiddenIds) hiddenIds.value = "";
      if (hiddenN) hiddenN.value = "1";
      if (hiddenRecargo) hiddenRecargo.value = "0.00";
      actualizarHintExcedente(0, 0);
      return;
    }

    if (thAcc) thAcc.textContent = esCuota ? "Pagar" : "—";

    if (!esCuota) {
      if (hiddenIds) hiddenIds.value = "";
      if (hiddenN) hiddenN.value = "1";
      if (hiddenRecargo) hiddenRecargo.value = "0.00";
    }

    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var tr = document.createElement("tr");
      tr.style.borderBottom = "1px solid var(--pbr-border, #f1f5f9)";
      if (row.rg) {
        tr.style.background = "#fff7ed";
      }
      var td0 = document.createElement("td");
      td0.style.padding = "0.35rem 0.5rem 0.35rem 0";
      var td1 = document.createElement("td");
      td1.style.padding = "0.35rem";
      var td2 = document.createElement("td");
      td2.style.padding = "0.35rem";
      var tdFp = document.createElement("td");
      tdFp.style.padding = "0.35rem";
      tdFp.dataset.col = "fecha-pago";
      var td3 = document.createElement("td");
      td3.style.padding = "0.35rem";
      var td4 = document.createElement("td");
      td4.style.padding = "0.35rem";
      td4.dataset.col = "recargo";
      var td5 = document.createElement("td");
      td5.style.padding = "0.35rem";
      td5.dataset.col = "capital";
      var td6 = document.createElement("td");
      td6.style.padding = "0.35rem";
      td6.dataset.col = "total";
      td6.style.fontWeight = "600";
      var td7 = document.createElement("td");
      td7.style.padding = "0.35rem";

      if (esCuota) {
        var chk = document.createElement("input");
        chk.type = "checkbox";
        chk.dataset.cuotaId = String(row.id);
        chk.dataset.idx = String(i);
        if (!row.abierta) {
          chk.disabled = true;
          chk.checked = true;
        }
        td0.appendChild(chk);
      } else {
        td0.textContent = "—";
      }
      td1.textContent = String(row.n);
      td2.textContent = formatDate(row.v);
      tdFp.textContent = row.fp ? formatDate(row.fp) : "—";
      td3.textContent = "$" + row.m;

      var rec = parseFloat(String(row.rec || "0").replace(",", ".")) || 0;
      var cap = parseFloat(String(row.cap || "0").replace(",", ".")) || 0;
      var tot = String(row.tot || "");
      if (!row.abierta) {
        td4.textContent = rec > 0.009 ? "$" + money(rec) : "—";
        td5.textContent = cap > 0.009 ? "$" + money(cap) : "—";
        td6.textContent = tot ? "$" + tot : "$" + row.m;
        if (rec > 0.009) td4.style.color = "#c2410c";
        if (cap > 0.009) td5.style.color = "#047857";
      } else {
        td4.textContent = row.rg ? "Pendiente" : "—";
        if (row.rg) td4.style.color = "#c2410c";
        td5.textContent = "—";
        td6.textContent = "$" + row.m;
      }
      td7.textContent = estadoLabel(row.e);
      tr.appendChild(td0);
      tr.appendChild(td1);
      tr.appendChild(td2);
      tr.appendChild(tdFp);
      tr.appendChild(td3);
      tr.appendChild(td4);
      tr.appendChild(td5);
      tr.appendChild(td6);
      tr.appendChild(td7);
      tbody.appendChild(tr);
    }

    if (esCuota) {
      // Preseleccionar la primera pendiente si no hay ninguna marcada.
      var openChecks = tbody.querySelectorAll(
        'input[type="checkbox"][data-cuota-id]:not(:disabled)'
      );
      var alguna = false;
      for (var c = 0; c < openChecks.length; c++) {
        if (openChecks[c].checked) {
          alguna = true;
          break;
        }
      }
      if (!alguna && openChecks.length) {
        openChecks[0].checked = true;
      }
      normalizeSelection();
      actualizarColumnasSeleccion();
    }
  }

  function actualizarColumnasSeleccion() {
    if (!isCuotaConcept()) return;
    var rows = getAllCuotas();
    var checks = tbody.querySelectorAll('input[type="checkbox"][data-cuota-id]:not(:disabled)');
    var openChecks = [];
    for (var i = 0; i < checks.length; i++) openChecks.push(checks[i]);
    var k = 0;
    for (var j = 0; j < openChecks.length; j++) {
      if (openChecks[j].checked) k = j + 1;
      else break;
    }
    var prefix = openChecks.slice(0, k);
    var rowsByIdx = {};
    for (var r = 0; r < rows.length; r++) rowsByIdx[r] = rows[r];
    var recargo = prefix.length ? calcRecargoSeleccionado(prefix, rowsByIdx) : 0;
    var lastIdx = prefix.length ? parseInt(prefix[prefix.length - 1].dataset.idx, 10) : -1;

    for (var i2 = 0; i2 < openChecks.length; i2++) {
      var tr = openChecks[i2].closest("tr");
      if (!tr) continue;
      var ix = parseInt(openChecks[i2].dataset.idx, 10);
      var row = rowsByIdx[ix];
      if (!row) continue;
      var tdRec = tr.querySelector('[data-col="recargo"]');
      var tdCap = tr.querySelector('[data-col="capital"]');
      var tdTot = tr.querySelector('[data-col="total"]');
      if (!tdRec || !tdCap || !tdTot) continue;
      var marcada = i2 < k;
      if (!marcada) {
        tdRec.textContent = row.rg ? "Pendiente" : "—";
        tdRec.style.color = row.rg ? "#c2410c" : "";
        tdCap.textContent = "—";
        tdCap.style.color = "";
        tdTot.textContent = "$" + row.m;
        continue;
      }
      var esUltima = ix === lastIdx;
      var mCuota = parseFloat(String(row.m).replace(",", ".")) || 0;
      if (esUltima && recargo > 0.009) {
        tdRec.textContent = "$" + money(recargo);
        tdRec.style.color = "#c2410c";
        tdTot.textContent = "$" + money(mCuota + recargo);
      } else {
        tdRec.textContent = "—";
        tdRec.style.color = "";
        tdTot.textContent = "$" + money(mCuota);
      }
      tdCap.textContent = "—";
      tdCap.style.color = "";
    }
    // Excedente a capital (si monto > sugerido) en la última marcada
    if (prefix.length && elMonto && lastIdx >= 0) {
      var sum = 0;
      for (var j2 = 0; j2 < prefix.length; j2++) {
        var ix2 = parseInt(prefix[j2].dataset.idx, 10);
        var r2 = rowsByIdx[ix2];
        if (r2) sum += parseFloat(String(r2.m).replace(",", ".")) || 0;
      }
      sum = Math.round(sum * 100) / 100;
      var sugerido = Math.round((sum + recargo) * 100) / 100;
      var total = parseFloat(String(elMonto.value || "").replace(",", ".")) || 0;
      var exc = Math.round((total - sugerido) * 100) / 100;
      var trLast = prefix[prefix.length - 1].closest("tr");
      if (trLast && exc > 0.009) {
        var tdC = trLast.querySelector('[data-col="capital"]');
        var tdT = trLast.querySelector('[data-col="total"]');
        if (tdC) {
          tdC.textContent = "$" + money(exc);
          tdC.style.color = "#047857";
        }
        if (tdT) tdT.textContent = "$" + money(total);
      }
    }
  }

  function onContratoOrConceptoChange() {
    rebuildTable();
  }

  if (selFmt) {
    selFmt.addEventListener("change", function () {
      var opt = selFmt.selectedOptions[0];
      var cid = opt && opt.getAttribute("data-contrato-id");
      if (cid && selCt) {
        selCt.value = cid;
      }
      onContratoOrConceptoChange();
    });
  }

  if (selCt) {
    selCt.addEventListener("change", function () {
      rebuildTable();
    });
  }
  if (conceptoSel) conceptoSel.addEventListener("change", onContratoOrConceptoChange);

  if (selFmt && selFmt.value && selCt) {
    var o = selFmt.selectedOptions[0];
    var cid = o && o.getAttribute("data-contrato-id");
    if (cid) selCt.value = cid;
  }

  wrap.addEventListener("change", function (ev) {
    var t = ev.target;
    if (t && t.matches && t.matches('input[type="checkbox"][data-cuota-id]') && !t.disabled) {
      normalizeSelection();
    }
  });

  if (elMonto) {
    elMonto.addEventListener("input", function () {
      actualizarHintExcedente();
      actualizarColumnasSeleccion();
    });
    elMonto.addEventListener("change", function () {
      actualizarHintExcedente();
      actualizarColumnasSeleccion();
    });
  }

  if (elFecha) {
    elFecha.addEventListener("change", function () {
      normalizeSelection();
    });
  }

  rebuildTable();
})();
