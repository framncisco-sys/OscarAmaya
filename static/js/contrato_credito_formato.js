/**
 * Plan de pagos: al elegir cliente carga TODO del formato + pagos
 * (lote, valor, reserva, prima, cuotas) sin capturar datos a mano.
 */
(function () {
  "use strict";

  var cargando = false;
  var ultimoCliente = "";
  var autofilled = false;

  function money(n) {
    var x = parseFloat(n);
    if (!isFinite(x)) return "—";
    return (
      "$" +
      x.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    );
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
    panel.style.display = show ? "block" : "none";
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
    var opts = loteSel.options || [];
    for (var i = 0; i < opts.length; i++) {
      var txt = String(opts[i].text || "").toLowerCase();
      var val = String(opts[i].value || "");
      if (txt.indexOf(needle) !== -1 || txt.indexOf("lote " + needle) !== -1) {
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
    if (!motivo) {
      box.style.display = "none";
      box.textContent = "";
      return;
    }
    box.style.display = "block";
    box.style.padding = "0.55rem 0.7rem";
    box.style.borderRadius = "8px";
    box.style.border = puede ? "1px solid #a7f3d0" : "1px solid #fecaca";
    box.style.background = puede ? "#ecfdf5" : "#fef2f2";
    box.style.color = puede ? "#14532d" : "#991b1b";
    box.style.fontWeight = "600";
    box.textContent = motivo;
    if (data && data.plan_mes13_id) {
      box.innerHTML =
        motivo +
        ' <a class="link-action" href="/app/contratos/' +
        data.plan_mes13_id +
        '/editar/">Abrir plan existente</a>';
    } else if (data && data.contrato_base_numero && !puede) {
      box.textContent = motivo;
    }
  }

  function fillDetalle(data) {
    var det = document.getElementById("contrato-credito-detalle");
    var msg = document.getElementById("contrato-credito-msg");
    if (!det || !msg) return;
    if (!data || !data.ok) {
      det.style.display = "none";
      autofilled = false;
      setSubmitEnabled(false);
      showElegibilidad(data);
      var baseMsg =
        (data && data.mensaje) || "Sin crédito a plazos para este cliente.";
      if (data && data.formato_nuevo_url) {
        msg.innerHTML =
          baseMsg +
          ' <a class="link-action" href="' +
          data.formato_nuevo_url +
          '">Crear formato de aceptación ahora</a>';
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
      "Desglose desde el formato. Este plan solo se guarda si ya pagó las 12 cuotas sin interés y aún no tiene un plan mes 13.";
    det.style.display = "block";
    autofilled = true;
    showElegibilidad(data);
    setSubmitEnabled(!!data.puede_crear_plan_mes13);

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
        (data.interes_anual_pct != null ? " · interés " + data.interes_anual_pct + "%" : "")
    );
    t(
      "cc-reserva",
      data.reserva_tiene_pago
        ? money(data.reserva_pagada) + " (pago registrado)"
        : money(data.reserva_pagada || data.reserva_formato) + " (del formato)"
    );
    t(
      "cc-prima",
      data.prima_tiene_pago
        ? money(data.primas) + " (pago registrado)"
        : money(data.primas) + " (del formato)"
    );
    t("cc-abonado-cuotas", money(data.abono_cuotas_1_a_12));

    var ini = data.monto_inicial != null ? Number(data.monto_inicial) : 0;
    var res =
      data.reserva_pagada != null
        ? Number(data.reserva_pagada)
        : Number(data.reserva_formato || 0);
    var pri = data.primas != null ? Number(data.primas) : 0;
    var c12 = data.abono_cuotas_1_a_12 != null ? Number(data.abono_cuotas_1_a_12) : 0;
    var desc = data.descuento != null ? Number(data.descuento) : 0;
    t(
      "cc-formula",
      money(ini) +
        " − " +
        money(res) +
        " − " +
        money(pri) +
        " − " +
        money(c12) +
        (desc > 0.009 ? " − " + money(desc) + " (desc.)" : "")
    );
    t("cc-deuda", money(data.nueva_deuda));
    t(
      "cc-cuota13",
      data.cuota_mensual_con_interes
        ? money(data.cuota_mensual_con_interes) +
            (data.n_cuotas_restantes
              ? " × " + data.n_cuotas_restantes + " meses"
              : "")
        : "—"
    );

    var detMontos = document.getElementById("cc-detalle-montos");
    if (detMontos) {
      detMontos.textContent =
        "Monto inicial: " +
        money(ini) +
        " · Cuota meses 1–12 (sin interés): " +
        (data.cuota_sin_interes ? money(data.cuota_sin_interes) : "—") +
        " c/u.";
    }
    t("cc-resumen", data.resumen || "");

    var tbody = document.getElementById("cc-listado-cuotas-body");
    if (tbody) {
      tbody.innerHTML = "";
      var rows = data.listado_cuotas || [];
      if (!rows.length) {
        tbody.innerHTML =
          '<tr><td colspan="3" class="muted" style="padding:0.5rem;">No hay cuotas para mostrar.</td></tr>';
      } else {
        rows.forEach(function (r) {
          var tr = document.createElement("tr");
          var bg = r.fase === "con_interes" ? "background:#fff7ed;" : "";
          tr.innerHTML =
            '<td style="padding:0.35rem 0.55rem;border-bottom:1px solid #f1f5f9;' +
            bg +
            '">' +
            r.numero +
            "</td>" +
            '<td style="padding:0.35rem 0.55rem;border-bottom:1px solid #f1f5f9;' +
            bg +
            '">' +
            (r.concepto || "") +
            "</td>" +
            '<td style="padding:0.35rem 0.55rem;border-bottom:1px solid #f1f5f9;text-align:right;font-weight:700;' +
            bg +
            '">' +
            money(r.monto) +
            "</td>";
          tbody.appendChild(tr);
        });
      }
    }

    // Autollenar campos ocultos del formulario
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
    // Primera carga: sin overrides para que el servidor mande todo del formato/pagos
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
    if (msg) msg.textContent = "Cargando lote, valor, reserva, prima y cuotas…";
    var det = document.getElementById("contrato-credito-detalle");
    if (det) det.style.display = "none";

    cargando = true;
    fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        fillDetalle(data);
        if (!data.ok) showPanel(true);
      })
      .catch(function () {
        if (msg) msg.textContent = "No se pudo cargar la información del cliente.";
      })
      .finally(function () {
        cargando = false;
      });
  }

  function bind() {
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
