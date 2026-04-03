/**
 * Recorte visual del plano: usa archivo del polígono, o plano maestro del proyecto.
 */
(function () {
  const cfg = document.getElementById("plano-crop-config");
  const planoInput = document.getElementById("id_plano");
  const proyectoSelect = document.getElementById("id_proyecto");
  if (!cfg || !planoInput) return;

  const mapEl = document.getElementById("proyecto-plano-map");
  let proyectoMap = {};
  if (mapEl) {
    try {
      proyectoMap = JSON.parse(mapEl.textContent);
    } catch (e) {
      proyectoMap = {};
    }
  }

  const fieldPlano = planoInput.closest(".field");
  if (!fieldPlano) return;

  const inputs = {
    izq: document.getElementById("id_recorte_izq_pct"),
    sup: document.getElementById("id_recorte_sup_pct"),
    ancho: document.getElementById("id_recorte_ancho_pct"),
    alto: document.getElementById("id_recorte_alto_pct"),
  };
  if (!inputs.izq || !inputs.sup || !inputs.ancho || !inputs.alto) return;

  const app = document.createElement("div");
  app.className = "field plano-crop-app";
  app.innerHTML = `
    <p class="field__label">Área a mostrar de este polígono</p>
    <p class="field__help muted">Si el plano está en el <strong>proyecto</strong>, elija el proyecto y arrastre aquí. Si sube un archivo en “Plano propio”, ese archivo tiene prioridad.</p>
    <div class="plano-crop-shell" id="plano-crop-shell" hidden>
      <img class="plano-crop-img" id="plano-crop-img" alt="Plano para recortar" draggable="false" />
      <div class="plano-crop-marquee" id="plano-crop-marquee" hidden></div>
    </div>
    <p class="plano-crop-wait muted" id="plano-crop-wait">Elija un proyecto con plano maestro o suba una imagen en “Plano propio”.</p>
    <div class="plano-crop-actions" id="plano-crop-actions" hidden>
      <button type="button" class="btn-secondary btn-sm" id="plano-crop-clear">Quitar selección</button>
      <a class="btn-secondary btn-sm" id="plano-crop-open-full" href="#" target="_blank" rel="noopener" hidden>Ver imagen completa</a>
    </div>
  `;
  fieldPlano.insertAdjacentElement("afterend", app);

  const shell = app.querySelector("#plano-crop-shell");
  const img = app.querySelector("#plano-crop-img");
  const marquee = app.querySelector("#plano-crop-marquee");
  const wait = app.querySelector("#plano-crop-wait");
  const actions = app.querySelector("#plano-crop-actions");
  const btnClear = app.querySelector("#plano-crop-clear");
  const openFull = app.querySelector("#plano-crop-open-full");
  let objectUrl = null;
  let dragging = false;
  let startPct = null;

  function clamp(n, a, b) {
    return Math.min(b, Math.max(a, n));
  }

  function evToPct(ev, rect) {
    const x = ((ev.clientX - rect.left) / rect.width) * 100;
    const y = ((ev.clientY - rect.top) / rect.height) * 100;
    return { x: clamp(x, 0, 100), y: clamp(y, 0, 100) };
  }

  function touchToPct(ev, rect) {
    const t = (ev.touches && ev.touches[0]) || (ev.changedTouches && ev.changedTouches[0]);
    if (!t) return { x: 0, y: 0 };
    const x = ((t.clientX - rect.left) / rect.width) * 100;
    const y = ((t.clientY - rect.top) / rect.height) * 100;
    return { x: clamp(x, 0, 100), y: clamp(y, 0, 100) };
  }

  function setMarqueeFromPct(L, T, W, H) {
    marquee.style.left = L + "%";
    marquee.style.top = T + "%";
    marquee.style.width = W + "%";
    marquee.style.height = H + "%";
    marquee.hidden = false;
  }

  function fillInputs(L, T, W, H) {
    inputs.izq.value = L.toFixed(2);
    inputs.sup.value = T.toFixed(2);
    inputs.ancho.value = W.toFixed(2);
    inputs.alto.value = H.toFixed(2);
  }

  function clearAll() {
    marquee.hidden = true;
    inputs.izq.value = "";
    inputs.sup.value = "";
    inputs.ancho.value = "";
    inputs.alto.value = "";
  }

  function applySavedRect() {
    if (objectUrl) return;
    const izq = parseFloat(cfg.dataset.izq || "");
    const sup = parseFloat(cfg.dataset.sup || "");
    const ancho = parseFloat(cfg.dataset.ancho || "");
    const alto = parseFloat(cfg.dataset.alto || "");
    if (
      !Number.isNaN(izq) &&
      !Number.isNaN(sup) &&
      !Number.isNaN(ancho) &&
      !Number.isNaN(alto) &&
      ancho > 0 &&
      alto > 0
    ) {
      setMarqueeFromPct(izq, sup, ancho, alto);
    }
  }

  function revokeBlob() {
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl);
      objectUrl = null;
    }
  }

  function getSourceInfo() {
    const f = planoInput.files && planoInput.files[0];
    if (f) {
      if (f.type === "application/pdf") {
        return { kind: "pdf_local" };
      }
      if (f.type.startsWith("image/")) {
        return { kind: "image_local", file: f };
      }
      return { kind: "unknown" };
    }
    const u = cfg.dataset.planoUrl && cfg.dataset.planoUrl.trim();
    if (u) {
      return {
        kind: cfg.dataset.isPdf === "1" ? "pdf_url" : "image_url",
        url: u,
      };
    }
    const pid = proyectoSelect && proyectoSelect.value;
    const entry = pid && proyectoMap[pid];
    if (entry && entry.url) {
      return {
        kind: entry.pdf ? "pdf_url" : "image_url",
        url: entry.url,
      };
    }
    return null;
  }

  function showPdfMessage(msg) {
    wait.hidden = false;
    wait.textContent = msg;
    shell.hidden = true;
    actions.hidden = true;
  }

  function showImageUi(url, showOpen) {
    wait.hidden = true;
    shell.hidden = false;
    actions.hidden = false;
    img.src = url;
    if (showOpen && openFull) {
      openFull.href = url;
      openFull.hidden = false;
    } else if (openFull) {
      openFull.hidden = true;
    }
    if (img.complete) {
      applySavedRect();
    } else {
      img.onload = function () {
        img.onload = null;
        applySavedRect();
      };
    }
  }

  function refresh() {
    revokeBlob();
    clearAll();
    const src = getSourceInfo();
    if (!src) {
      wait.hidden = false;
      wait.textContent =
        "Elija un proyecto que tenga plano maestro (edite el proyecto y suba el archivo) o suba una imagen en “Plano propio”.";
      shell.hidden = true;
      actions.hidden = true;
      return;
    }
    if (src.kind === "pdf_local" || src.kind === "pdf_url") {
      showPdfMessage(
        "El recorte con el ratón solo aplica a imágenes. Use JPG/PNG en el proyecto o en “Plano propio”, o rellene los porcentajes a mano."
      );
      return;
    }
    if (src.kind === "image_local") {
      objectUrl = URL.createObjectURL(src.file);
      showImageUi(objectUrl, false);
      return;
    }
    if (src.kind === "image_url" && src.url) {
      showImageUi(src.url, true);
    }
  }

  planoInput.addEventListener("change", refresh);
  if (proyectoSelect) {
    proyectoSelect.addEventListener("change", refresh);
  }

  refresh();

  btnClear.addEventListener("click", function () {
    clearAll();
  });

  function startDrag(ev) {
    if (shell.hidden) return;
    const t = ev.target;
    if (t === marquee) return;
    if (!shell.contains(t)) return;
    const src = getSourceInfo();
    if (!src || src.kind === "pdf_local" || src.kind === "pdf_url") return;
    dragging = true;
    const rect = shell.getBoundingClientRect();
    startPct = ev.type.indexOf("touch") === 0 ? touchToPct(ev, rect) : evToPct(ev, rect);
    ev.preventDefault();
  }

  function moveDrag(ev) {
    if (!dragging || !startPct) return;
    const src = getSourceInfo();
    if (!src || src.kind === "pdf_local" || src.kind === "pdf_url") return;
    const rect = shell.getBoundingClientRect();
    const cur = ev.type.indexOf("touch") === 0 ? touchToPct(ev, rect) : evToPct(ev, rect);
    const L = Math.min(startPct.x, cur.x);
    const T = Math.min(startPct.y, cur.y);
    const W = Math.abs(cur.x - startPct.x);
    const H = Math.abs(cur.y - startPct.y);
    if (W < 0.3 || H < 0.3) return;
    setMarqueeFromPct(L, T, W, H);
    fillInputs(L, T, W, H);
    ev.preventDefault();
  }

  function endDrag(ev) {
    if (dragging) {
      dragging = false;
      startPct = null;
      if (ev.type === "touchend") ev.preventDefault();
    }
  }

  shell.addEventListener("mousedown", startDrag);
  document.addEventListener("mousemove", moveDrag);
  document.addEventListener("mouseup", endDrag);
  shell.addEventListener("touchstart", startDrag, { passive: false });
  document.addEventListener("touchmove", moveDrag, { passive: false });
  document.addEventListener("touchend", endDrag);
})();
