(function () {
  "use strict";

  var selFmt = document.getElementById("id_formato_aceptacion");
  var selCt = document.getElementById("id_contrato");
  var conceptoSel = document.getElementById("id_concepto");
  var hiddenIds = document.getElementById("id_cuotas_seleccionadas");
  var hiddenN = document.getElementById("id_cuotas_incluidas");
  var wrap = document.getElementById("pago-cuotas-tabla-wrap");
  var tbody = document.getElementById("pago-cuotas-tabla-body");
  var elFecha = document.getElementById("id_fecha");
  var elMonto = document.getElementById("id_monto");

  if (!wrap || !tbody || !selCt || wrap.getAttribute("data-enabled") !== "1") {
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

  function getAllCuotas() {
    var opt = selCt.selectedOptions[0];
    if (!opt || !opt.value) return [];
    return parseJsonAttr(opt, "data-cuotas-todas-json") || [];
  }

  function isCuotaConcept() {
    return conceptoSel && String(conceptoSel.value || "").toUpperCase() === "CUOTA";
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
    if (isCuotaConcept() && elMonto) {
      elMonto.value = openChecksPrefix.length ? sum.toFixed(2) : "";
    }
    if (isCuotaConcept() && openChecksPrefix.length && elFecha) {
      var ix0 = parseInt(openChecksPrefix[0].dataset.idx, 10);
      var r0 = rowsByIdx[ix0];
      if (r0 && r0.v) elFecha.value = r0.v;
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
  }

  function rebuildTable() {
    tbody.innerHTML = "";
    if (!isCuotaConcept()) {
      wrap.style.display = "none";
      if (hiddenIds) hiddenIds.value = "";
      if (hiddenN) hiddenN.value = "1";
      return;
    }

    var rows = getAllCuotas();
    if (!rows.length) {
      wrap.style.display = "none";
      return;
    }

    wrap.style.display = "block";

    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var tr = document.createElement("tr");
      tr.style.borderBottom = "1px solid var(--pbr-border, #f1f5f9)";
      var td0 = document.createElement("td");
      td0.style.padding = "0.35rem 0.5rem 0.35rem 0";
      var td1 = document.createElement("td");
      td1.style.padding = "0.35rem";
      var td2 = document.createElement("td");
      td2.style.padding = "0.35rem";
      var td3 = document.createElement("td");
      td3.style.padding = "0.35rem";
      var td4 = document.createElement("td");
      td4.style.padding = "0.35rem";

      var chk = document.createElement("input");
      chk.type = "checkbox";
      chk.dataset.cuotaId = String(row.id);
      chk.dataset.idx = String(i);
      if (!row.abierta) {
        chk.disabled = true;
        chk.checked = true;
      }
      td0.appendChild(chk);
      td1.textContent = String(row.n);
      td2.textContent = formatDate(row.v);
      td3.textContent = "$" + row.m;
      td4.textContent = estadoLabel(row.e);
      tr.appendChild(td0);
      tr.appendChild(td1);
      tr.appendChild(td2);
      tr.appendChild(td3);
      tr.appendChild(td4);
      tbody.appendChild(tr);
    }

    normalizeSelection();
  }

  function onContratoOrConceptoChange() {
    rebuildTable();
    if (selCt && selCt.selectedOptions[0] && selCt.selectedOptions[0].value) {
      try {
        selCt.dispatchEvent(new Event("change", { bubbles: true }));
      } catch (e) {}
    }
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

  selCt.addEventListener("change", function () {
    rebuildTable();
  });
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

  rebuildTable();
})();

