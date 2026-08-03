/**
 * Tras emitir/validar un recibo: descarga el PDF e intenta abrir WhatsApp
 * (wa.me) para que el vendedor envíe con su WhatsApp personal / Web.
 */
(function () {
  function openWhatsAppAndPdf() {
    var root = document.querySelector(".alert-recibo[data-pbr-wa-open], .alert-recibo[data-pbr-pdf-href]");
    if (!root) return;

    var wa = (root.getAttribute("data-pbr-wa-open") || "").trim();
    var pdf = (root.getAttribute("data-pbr-pdf-href") || "").trim();

    if (pdf) {
      try {
        var iframe = document.createElement("iframe");
        iframe.style.display = "none";
        iframe.setAttribute("aria-hidden", "true");
        iframe.src = pdf;
        document.body.appendChild(iframe);
        window.setTimeout(function () {
          try {
            iframe.remove();
          } catch (e) {}
        }, 60000);
      } catch (e) {}
    }

    if (wa) {
      // Nueva pestaña/ventana: WhatsApp Desktop, Web o app según el equipo del vendedor.
      window.setTimeout(function () {
        window.open(wa, "_blank", "noopener,noreferrer");
      }, 350);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", openWhatsAppAndPdf);
  } else {
    openWhatsAppAndPdf();
  }
})();
