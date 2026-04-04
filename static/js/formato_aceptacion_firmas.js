/**
 * Lienzos de firma para Formato de aceptación: trazo, limpiar y volcar PNG en inputs ocultos al enviar.
 */
(function () {
  "use strict";

  function getPos(canvas, e) {
    var r = canvas.getBoundingClientRect();
    var clientX = e.clientX;
    var clientY = e.clientY;
    if (e.touches && e.touches[0]) {
      clientX = e.touches[0].clientX;
      clientY = e.touches[0].clientY;
    }
    var scaleX = canvas.width / r.width;
    var scaleY = canvas.height / r.height;
    return {
      x: (clientX - r.left) * scaleX,
      y: (clientY - r.top) * scaleY,
    };
  }

  function initPad(canvas, hiddenInput, clearBtn, existingUrl) {
    var ctx = canvas.getContext("2d");
    var w = canvas.width;
    var h = canvas.height;
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = "#0f172a";
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    var drawing = false;
    var dirty = false;

    function drawStart(e) {
      drawing = true;
      var p = getPos(canvas, e);
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
      dirty = true;
    }

    function drawMove(e) {
      if (!drawing) return;
      var p = getPos(canvas, e);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
    }

    function drawEnd() {
      drawing = false;
    }

    canvas.addEventListener("mousedown", drawStart);
    canvas.addEventListener("mousemove", drawMove);
    window.addEventListener("mouseup", drawEnd);

    canvas.addEventListener(
      "touchstart",
      function (e) {
        e.preventDefault();
        drawStart(e);
      },
      { passive: false }
    );
    canvas.addEventListener(
      "touchmove",
      function (e) {
        e.preventDefault();
        drawMove(e);
      },
      { passive: false }
    );
    canvas.addEventListener("touchend", drawEnd);
    canvas.addEventListener("touchcancel", drawEnd);

    if (existingUrl) {
      var img = new Image();
      img.onload = function () {
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, w, h);
        ctx.drawImage(img, 0, 0, w, h);
        dirty = false;
      };
      img.onerror = function () {};
      img.src = existingUrl;
    }

    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, w, h);
        dirty = false;
        hiddenInput.value = "";
      });
    }

    return {
      commit: function () {
        if (dirty) {
          hiddenInput.value = canvas.toDataURL("image/png");
        }
      },
    };
  }

  function boot() {
    var form = document.querySelector("form.js-formato-aceptacion-form");
    if (!form) return;

    var pads = [];
    var nodes = form.querySelectorAll("[data-sig-canvas]");
    for (var i = 0; i < nodes.length; i++) {
      var wrap = nodes[i];
      var canvas = wrap.querySelector("canvas");
      var hidden = wrap.querySelector('input[type="hidden"]');
      var clearBtn = wrap.querySelector("[data-sig-clear]");
      if (!canvas || !hidden) continue;
      var url = (wrap.getAttribute("data-existing-url") || "").trim();
      pads.push(initPad(canvas, hidden, clearBtn, url || null));
    }

    form.addEventListener("submit", function () {
      for (var j = 0; j < pads.length; j++) {
        pads[j].commit();
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
