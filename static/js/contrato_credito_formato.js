/**
 * Plan de pagos (paso 5): carga del formato + misma lógica de cuotas que formato_aceptacion_credito.js
 */
(function () {
  "use strict";

  var cargando = false;
  var ultimoCliente = "";
  var autofilled = false;
  var datosActuales = null;
  var filtroActivo = "todas";

  function money(n) {
    var x = parseFloat(n);
    if (!isFinite(x)) return "—";
    return (
      "$" +
      x.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    );
  }

  function fmtFecha(iso) {
    if (!iso) return "—";
    var m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return iso;
    return m[3] + "/" + m[2] + "/" + m[1];
  }

  function num(el) {
    if (!el) return null;
    var v = String(el.value || "")
      .replace(/\$/g, "")
      .replace(/,/g, "")
      .trim();
    if (v === "") return null;
    var n = parseFloat(v);
    return isFinite(n) ? n : null;
  }

  function setVal(id, value) {
    var el = document.getElementById(id);
    if (!el) return;
    el.value = value == null || value === "" ? "" : String(value);
  }

  function showPanel(show) {
    var panel = document.getElementById("contrato-credito-plazos-panel");
    if (!panel) return;
    panel.hidden = !show;
  }

  function selectLote(data) {
    var loteSel = document.getElementById("id_inmueble");
    if (!loteSel) return;
    if (data.inmueble_id) {
      loteSel.value = String(data.inmueble_id);
      if (loteSel.value === String(data.inmueble_id)) return;
    }
    var needle = String(data.num_lote || "")
      .trim()
      .toLowerCase();
    if (!needle) return;
    var needleAlt = needle;
    var m = needle.match(/^([a-z])-?0*(\d+)$/i);
    if (m) {
      needleAlt = String(parseInt(m[2], 10));
    } else if (/^\d+$/.test(needle)) {
      needleAlt = needle.replace(/^0+/, "") || "0";
    }
    var opts = loteSel.options || [];
    for (var i = 0; i < opts.length; i++) {
      var txt = String(opts[i].text || "").toLowerCase();
      var val = String(opts[i].value || "");
      if (!val) continue;
      if (
        txt.indexOf("lote " + needle) !== -1 ||
        txt.indexOf("lote " + needleAlt) !== -1 ||
        (m && txt.indexOf("lote " + m[1] + m[2].padStart(2, "0")) !== -1)
      ) {
        loteSel.value = val;
        break;
      }
    }
  }

  function setSubmitEnabled(enabled) {
    var form = document.querySelector("form");
    if (!form) return;
    var buttons = form.querySelectorAll('button[type="submit"], input[type="submit"]');
    buttons.forEach(function (btn) {
      btn.disabled = !enabled;
      if (!enabled) {
        btn.setAttribute("title", "No se puede guardar aún: revise los requisitos del plan mes 13.");
      } else {
        btn.removeAttribute("title");
      }
    });
  }

  function showElegibilidad(data) {
    var box = document.getElementById("contrato-credito-elegibilidad");
    if (!box) return;
    var puede = !!(data && data.puede_crear_plan_mes13);
    var motivo = (data && data.motivo_plan_mes13) || "";
    box.className = "plan-mes13__alert" + (puede ? " plan-mes13__alert--ok" : " plan-mes13__alert--warn");
    if (!motivo) {
      box.hidden = true;
      box.textContent = "";
      return;
    }
    box.hidden = false;
    if (data && data.plan_mes13_id) {
      box.innerHTML =
        motivo +
        ' <a class="link-action" href="/app/contratos/' +
        data.plan_mes13_id +
        '/editar/">Abrir plan existente</a>';
    } else {
      box.textContent = motivo;
    }
  }

  function updateProgreso(data) {
    var pagadas = data && data.cuotas_1_12_pagadas != null ? Number(data.cuotas_1_12_pagadas) : 0;
    var req = data && data.cuotas_1_12_requeridas != null ? Number(data.cuotas_1_12_requeridas) : 12;
    if (!isFinite(pagadas) || pagadas < 0) pagadas = 0;
    if (!isFinite(req) || req < 1) req = 12;
    var pct = Math.min(100, Math.round((pagadas / req) * 100));
    var txt = document.getElementById("cc-progreso-texto");
    var bar = document.getElementById("cc-progreso-bar");
    var wrap = document.querySelector(".plan-mes13__progress");
    if (txt) txt.textContent = pagadas + " / " + req + " pagadas";
    if (bar) bar.style.width = pct + "%";
    if (wrap) {
      wrap.setAttribute("aria-valuenow", String(pagadas));
      wrap.setAttribute("aria-valuemax", String(req));
    }
  }

  function estadoBadge(estado, label) {
    var key = String(estado || "PENDIENTE").toLowerCase();
    return (
      '<span class="ec-bank-badge ec-bank-badge--' +
      key +
      ' plan-mes13__estado plan-mes13__estado--' +
      key +
      '">' +
      (label || estado || "—") +
      "</span>"
    );
  }

  function celRecargo(r) {
    var rec = parseFloat(r.recargo || "0");
    var pend = parseFloat(r.recargo_pendiente || "0");
    if (rec > 0.009) {
      return (
        '<td class="ec-bank-table__num plan-mes13__td-num plan-mes13__td-recargo plan-mes13__td-recargo--cobrado" title="Recargo administrativo cobrado en este recibo">' +
        money(r.recargo) +
        "</td>"
      );
    }
    if (r.genera_recargo && pend > 0.009) {
      return (
        '<td class="ec-bank-table__num plan-mes13__td-num plan-mes13__td-recargo plan-mes13__td-recargo--pendiente" title="Genera recargo: se cobrará en la cuota siguiente">' +
        "+" +
        money(r.recargo_pendiente) +
        "</td>"
      );
    }
    return '<td class="ec-bank-table__num plan-mes13__td-num plan-mes13__td-recargo muted">—</td>';
  }

  function celDias(r) {
    var d = r.dias_atraso;
    if (d == null || d === "" || Number(d) <= 0) {
      return '<td class="plan-mes13__td-num muted">—</td>';
    }
    var n = Number(d);
    var cls =
      r.estado === "PAGADA"
        ? "plan-mes13__dias plan-mes13__dias--pagado"
        : "plan-mes13__dias plan-mes13__dias--atraso";
    var title =
      r.estado === "PAGADA"
        ? "Días de atraso al pagar"
        : "Días de atraso respecto al vencimiento";
    return (
      '<td class="ec-bank-table__num plan-mes13__td-num"><span class="' +
      cls +
      ' ec-bank-tag" title="' +
      title +
      '">' +
      n +
      "</span></td>"
    );
  }

  function celFechaPago(r) {
    var fp = r.fecha_pago || (r.estado === "PAGADA" ? r.pagado_en : "");
    if (!fp) {
      return '<td class="muted">—</td>';
    }
    var ref = r.pago_referencia ? ' title="Recibo: ' + r.pago_referencia + '"' : "";
    var extra =
      r.monto_pagado && parseFloat(r.monto_pagado) > parseFloat(r.monto || 0) + 0.009
        ? '<span class="plan-mes13__monto-pago ec-bank-sub">Total recibo ' +
          money(r.monto_pagado) +
          "</span>"
        : "";
    return "<td" + ref + '><span class="ec-bank-fecha-pago">' + fmtFecha(fp) + "</span>" + extra + "</td>";
  }

  function renderTabla(rows, totales) {
    var tbody = document.getElementById("cc-listado-cuotas-body");
    var tfoot = document.getElementById("cc-listado-cuotas-foot");
    if (!tbody) return;
    tbody.innerHTML = "";
    var filtradas = rows.filter(function (r) {
      if (filtroActivo === "todas") return true;
      return r.fase === filtroActivo;
    });
    if (!filtradas.length) {
      tbody.innerHTML =
        '<tr><td colspan="11" class="muted plan-mes13__empty">No hay cuotas en este filtro.</td></tr>';
      if (tfoot) tfoot.hidden = true;
      return;
    }
    filtradas.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.className =
        "plan-mes13__row" +
        (r.fase === "con_interes" ? " plan-mes13__row--interes" : " plan-mes13__row--sin-int") +
        (r.estado === "PAGADA" ? " plan-mes13__row--pagada is-pagada" : "") +
        (r.estado === "VENCIDA" ? " plan-mes13__row--vencida is-vencida" : "") +
        (r.genera_recargo ? " plan-mes13__row--recargo" : "");
      tr.dataset.fase = r.fase || "";
      tr.innerHTML =
        "<td><strong>" +
        r.numero +
        "</strong></td>" +
        "<td>" +
        fmtFecha(r.fecha) +
        "</td>" +
        celFechaPago(r) +
        celDias(r) +
        '<td class="ec-bank-table__num plan-mes13__td-num">' +
        money(r.saldo_inicial) +
        "</td>" +
        '<td class="ec-bank-table__num plan-mes13__td-num plan-mes13__td-cuota ec-bank-table__cuota">' +
        money(r.monto) +
        "</td>" +
        '<td class="ec-bank-table__num plan-mes13__td-num">' +
        money(r.capital) +
        "</td>" +
        '<td class="ec-bank-table__num plan-mes13__td-num">' +
        money(r.interes) +
        "</td>" +
        celRecargo(r) +
        '<td class="ec-bank-table__num plan-mes13__td-num">' +
        money(r.saldo) +
        "</td>" +
        "<td>" +
        estadoBadge(r.estado, r.estado_label) +
        "</td>";
      tbody.appendChild(tr);
    });

    if (tfoot && totales && filtroActivo === "todas") {
      tfoot.hidden = false;
      var fc = document.getElementById("cc-foot-cuota");
      var fcap = document.getElementById("cc-foot-capital");
      var fint = document.getElementById("cc-foot-interes");
      var frec = document.getElementById("cc-foot-recargo");
      if (fc) fc.textContent = money(totales.total_cuotas);
      if (fcap) fcap.textContent = money(totales.total_capital);
      if (fint) fint.textContent = money(totales.total_interes);
      if (frec) frec.textContent = money(totales.total_recargo || "0");
    } else if (tfoot) {
      tfoot.hidden = true;
    }

    if (filtroActivo === "con_interes" && filtradas.length) {
      var scroll = document.querySelector(".plan-mes13__table-scroll");
      if (scroll) scroll.scrollTop = 0;
    }
  }

  function bindFiltros() {
    document.querySelectorAll("[data-plan-filter]").forEach(function (btn) {
      if (btn.__planFilterBound) return;
      btn.__planFilterBound = true;
      btn.addEventListener("click", function () {
        filtroActivo = btn.getAttribute("data-plan-filter") || "todas";
        document.querySelectorAll("[data-plan-filter]").forEach(function (b) {
          var on = b === btn;
          b.classList.toggle("is-active", on);
          b.setAttribute("aria-selected", on ? "true" : "false");
        });
        if (datosActuales && datosActuales.listado_cuotas) {
          renderTabla(datosActuales.listado_cuotas, datosActuales.listado_totales);
        }
      });
    });
  }

  function fillDetalle(data) {
    datosActuales = data;
    var det = document.getElementById("contrato-credito-detalle");
    var msg = document.getElementById("contrato-credito-msg");
    var linkFmt = document.getElementById("plan-mes13-link-formato");
    if (!det || !msg) return;

    if (linkFmt) {
      if (data && data.formato_edit_url) {
        linkFmt.href = data.formato_edit_url;
        linkFmt.hidden = false;
      } else {
        linkFmt.hidden = true;
      }
    }

    if (!data || !data.ok) {
      det.hidden = true;
      autofilled = false;
      setSubmitEnabled(false);
      showElegibilidad(data);
      updateProgreso(data);
      var baseMsg =
        (data && data.mensaje) || "Sin crédito a plazos para este cliente.";
      if (data && data.formato_nuevo_url) {
        msg.innerHTML =
          baseMsg +
          ' <a class="link-action" href="' +
          data.formato_nuevo_url +
          '">Crear formato de aceptación</a>';
      } else if (data && data.formato_edit_url) {
        msg.innerHTML =
          baseMsg +
          ' <a class="link-action" href="' +
          data.formato_edit_url +
          '">Completar formato</a>';
      } else {
        msg.textContent = baseMsg;
      }
      return;
    }

    msg.textContent =
      "Misma lógica que el formato: valor a financiar − 12 cuotas sin interés = saldo; desde el mes 13 se reparte con interés (PMT).";
    det.hidden = false;
    autofilled = true;
    showElegibilidad(data);
    updateProgreso(data);
    setSubmitEnabled(!!data.puede_crear_plan_mes13);

    if (data.puede_crear_plan_mes13) {
      filtroActivo = "con_interes";
    } else {
      filtroActivo = "todas";
    }
    document.querySelectorAll("[data-plan-filter]").forEach(function (b) {
      var f = b.getAttribute("data-plan-filter");
      var on = f === filtroActivo;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });

    function t(id, text) {
      var el = document.getElementById(id);
      if (el) el.textContent = text;
    }

    var loteTxt =
      data.inmueble_label ||
      ([data.nombre_proyecto, data.poligono_txt, data.num_lote]
        .filter(Boolean)
        .join(" — ") ||
        "—");
    t("cc-formato", data.formato_numero != null ? String(data.formato_numero).padStart(4, "0") : "—");
    t("cc-lote", loteTxt);
    t("cc-proyecto", data.nombre_proyecto || "—");
    t(
      "cc-plazo",
      (data.plazo_anos != null ? data.plazo_anos + " año(s)" : "—") +
        (data.n_cuotas_total != null ? " · " + data.n_cuotas_total + " cuotas" : "") +
        (data.interes_anual_pct != null ? " · " + data.interes_anual_pct + "% anual" : "")
    );
    t(
      "cc-reserva",
      data.reserva_tiene_pago
        ? money(data.reserva_pagada) + " · pagado"
        : money(data.reserva_pagada || data.reserva_formato) + " · formato"
    );
    t(
      "cc-prima",
      data.prima_tiene_pago
        ? money(data.primas) + " · pagado"
        : money(data.primas) + " · formato"
    );
    t("cc-abonado-cuotas", money(data.abono_cuotas_1_a_12));
    t("cc-valor-fin", money(data.valor_financiamiento));

    var principal = data.valor_financiamiento != null ? Number(data.valor_financiamiento) : 0;
    var c12 = data.abono_cuotas_1_a_12 != null ? Number(data.abono_cuotas_1_a_12) : 0;
    t("cc-formula", money(principal) + " − " + money(c12) + " (cuotas 1–12)");
    t("cc-deuda", money(data.nueva_deuda));
    t(
      "cc-cuota13",
      data.cuota_mensual_con_interes
        ? money(data.cuota_mensual_con_interes) +
            (data.n_cuotas_restantes ? " × " + data.n_cuotas_restantes : "")
        : "—"
    );

    t(
      "cc-detalle-montos",
      "Cuota meses 1–12 (sin interés): " +
        (data.cuota_sin_interes ? money(data.cuota_sin_interes) : "—") +
        " c/u · Valor del lote: " +
        (data.monto_inicial ? money(data.monto_inicial) : "—")
    );
    t("cc-resumen", data.resumen || "");

    var meta = document.getElementById("cc-amort-meta");
    if (meta && data.listado_totales) {
      var lt = data.listado_totales;
      meta.textContent =
        "Saldo a financiar " +
        money(lt.saldo_inicial) +
        " · Tasa " +
        (lt.tasa_anual_pct || data.interes_anual_pct || "0") +
        "% anual (" +
        (lt.tasa_mensual_pct || "0") +
        "% mensual desde mes 13). Recargos cobrados: " +
        money(lt.total_recargo || "0") +
        " · columnas de fecha pago y atraso según recibos.";
    } else if (meta) {
      meta.textContent =
        "Desglose capital + interés + saldo insoluto. Fecha pago y recargo según recibos registrados.";
    }

    var totBox = document.getElementById("cc-amort-totales");
    if (totBox && data.listado_totales) {
      var t = data.listado_totales;
      totBox.hidden = false;
      totBox.innerHTML =
        '<span><strong>' +
        (t.n_cuotas || data.n_cuotas_total || "—") +
        "</strong> cuotas</span>" +
        "<span>Capital <strong>" +
        money(t.total_capital) +
        "</strong></span>" +
        "<span>Intereses <strong>" +
        money(t.total_interes) +
        "</strong></span>" +
        "<span>Recargos <strong>" +
        money(t.total_recargo || "0") +
        "</strong></span>" +
        "<span>Total cuotas <strong>" +
        money(t.total_cuotas) +
        "</strong></span>";
    } else if (totBox) {
      totBox.hidden = true;
    }

    renderTabla(data.listado_cuotas || [], data.listado_totales);

    selectLote(data);
    setVal("id_prima_monto", data.primas || "0");
    if (data.descuento != null) setVal("id_descuento_efectivo_monto", data.descuento);
    if (data.plazo_anos != null) setVal("id_plan_anos", data.plazo_anos);
    if (data.interes_anual_pct != null && data.interes_anual_pct !== "") {
      setVal("id_tasa_interes_anual", data.interes_anual_pct);
    }
    setVal("id_meses_sin_interes", data.meses_sin_interes || 12);
    setVal("id_modalidad_financiamiento", "PRIMER_ANO_SIN_INTERESES");
    if (data.monto_inicial) setVal("id_precio_lista_referencia", data.monto_inicial);
    if (data.nueva_deuda != null) setVal("id_precio_final", data.nueva_deuda);
    if (data.cuota_mensual_con_interes) {
      setVal("id_cuota_mensual_estimada", data.cuota_mensual_con_interes);
    }
    var notas = document.getElementById("id_notas");
    if (notas && data.resumen) {
      var marker = "Crédito a plazos (formato";
      var prev = String(notas.value || "");
      if (!prev || prev.indexOf(marker) === 0) {
        notas.value =
          marker +
          " Nº " +
          String(data.formato_numero).padStart(4, "0") +
          "): " +
          data.resumen;
      } else if (prev.indexOf(marker) === -1) {
        notas.value =
          marker +
          " Nº " +
          String(data.formato_numero).padStart(4, "0") +
          "): " +
          data.resumen +
          "\n" +
          prev;
      }
    }
  }

  function urlForCliente(clienteId) {
    var tpl = window.PBR_CONTRATO_CREDITO_URL || "";
    return tpl.replace("__ID__", String(clienteId));
  }

  function cargarCredito(forzarSinOverrides) {
    if (cargando) return;
    var sel = document.getElementById("id_cliente");
    if (!sel || !sel.value) {
      showPanel(false);
      setSubmitEnabled(false);
      showElegibilidad(null);
      return;
    }
    if (sel.value !== ultimoCliente) {
      ultimoCliente = sel.value;
      autofilled = false;
      var primaReset = document.getElementById("id_prima_monto");
      var descReset = document.getElementById("id_descuento_efectivo_monto");
      if (primaReset) primaReset.value = "";
      if (descReset) descReset.value = "";
    }

    var url = urlForCliente(sel.value);
    if (!forzarSinOverrides && autofilled) {
      var descuento = num(document.getElementById("id_descuento_efectivo_monto"));
      var prima = num(document.getElementById("id_prima_monto"));
      var qs = [];
      if (descuento != null) qs.push("descuento=" + encodeURIComponent(String(descuento)));
      if (prima != null) qs.push("prima=" + encodeURIComponent(String(prima)));
      if (qs.length) url += (url.indexOf("?") >= 0 ? "&" : "?") + qs.join("&");
    }

    showPanel(true);
    var msg = document.getElementById("contrato-credito-msg");
    if (msg) msg.textContent = "Cargando datos del formato y pagos…";
    var det = document.getElementById("contrato-credito-detalle");
    if (det) det.hidden = true;

    cargando = true;
    fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        fillDetalle(data);
      })
      .catch(function () {
        if (msg) msg.textContent = "No se pudo cargar la información del cliente.";
      })
      .finally(function () {
        cargando = false;
      });
  }

  function bind() {
    bindFiltros();
    var sel = document.getElementById("id_cliente");
    if (sel) {
      sel.addEventListener("change", function () {
        cargarCredito(true);
      });
      if (sel.value) cargarCredito(true);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
