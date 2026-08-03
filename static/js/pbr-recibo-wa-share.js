/**
 * Un solo paso: PDF adjunto + mensaje de recibo vía Web Share (WhatsApp personal).
 * En PC sin Share API: abre wa.me con el mensaje y descarga el PDF.
 */
(function () {
  var dataEl = document.getElementById("pbr-wa-share-data");
  var btn = document.getElementById("pbr-wa-share");
  var statusEl = document.getElementById("pbr-wa-status");
  if (!dataEl || !btn) return;

  var data;
  try {
    data = JSON.parse(dataEl.textContent);
  } catch (e) {
    return;
  }

  function setStatus(text, isError) {
    if (!statusEl) return;
    statusEl.hidden = !text;
    statusEl.textContent = text || "";
    statusEl.style.color = isError ? "#92400e" : "var(--pbr-muted)";
  }

  function canShareFiles(file) {
    try {
      if (!navigator.share || !navigator.canShare) return false;
      return navigator.canShare({ files: [file] });
    } catch (e) {
      return false;
    }
  }

  async function fetchPdfFile() {
    var res = await fetch(data.pdf_url, {
      credentials: "same-origin",
      headers: { Accept: "application/pdf" },
    });
    if (!res.ok) throw new Error("No se pudo descargar el PDF (" + res.status + ")");
    var blob = await res.blob();
    var name = data.pdf_nombre || "recibo.pdf";
    return new File([blob], name, { type: "application/pdf" });
  }

  async function sharePdfAndMessage() {
    setStatus("Preparando PDF y mensaje…");
    btn.disabled = true;
    try {
      var file = await fetchPdfFile();
      var mensaje = data.mensaje || data.mensaje_con_enlace || "";

      if (canShareFiles(file)) {
        await navigator.share({
          files: [file],
          title: "Recibo " + (data.doc_numero || ""),
          text: mensaje,
        });
        setStatus("Listo. Elija WhatsApp, confirme el chat y pulse Enviar (PDF + mensaje van juntos).");
        return;
      }

      // Escritorio / navegador sin adjunto: mensaje al número + PDF descargado.
      setStatus(
        "Este navegador no adjunta PDF al compartir. Se abre el chat con el mensaje; use el PDF descargado si hace falta.",
        true
      );
      try {
        var a = document.createElement("a");
        a.href = data.pdf_url;
        a.download = data.pdf_nombre || "recibo.pdf";
        a.rel = "noopener";
        document.body.appendChild(a);
        a.click();
        a.remove();
      } catch (e) {}
      if (data.wa_url) {
        window.location.href = data.wa_url;
      }
    } catch (err) {
      if (err && err.name === "AbortError") {
        setStatus("Envío cancelado.");
        return;
      }
      setStatus(
        (err && err.message) || "No se pudo preparar el envío. Intente de nuevo.",
        true
      );
      if (data.wa_url) {
        window.setTimeout(function () {
          window.location.href = data.wa_url;
        }, 900);
      }
    } finally {
      btn.disabled = false;
    }
  }

  btn.addEventListener("click", function (ev) {
    ev.preventDefault();
    sharePdfAndMessage();
  });

  // En móvil, un toque automático suele bloquearse; dejamos el botón listo y
  // si el gesto de la navegación POST aún cuenta, intentamos una vez.
  var nav = performance.getEntriesByType && performance.getEntriesByType("navigation")[0];
  var fromForm = nav && nav.type === "navigate";
  if (fromForm && /Android|iPhone|iPad|iPod/i.test(navigator.userAgent || "")) {
    window.setTimeout(function () {
      if (!btn.disabled) btn.click();
    }, 400);
  }
})();
