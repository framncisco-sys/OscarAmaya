/**
 * Lienzos de firma para formato de aceptación: rellena campos ocultos con PNG en data URL al enviar.
 */
(function () {
  function canvasIsBlank(canvas) {
    var ctx = canvas.getContext("2d");
    var data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    for (var i = 3; i < data.length; i += 4) {
      if (data[i] !== 0) return false;
    }
    return true;
  }

  function bindCanvas(canvas) {
    var form = canvas.closest("form");
    if (!form) return;
    var inputName = canvas.getAttribute("data-input-name");
    if (!inputName) return;
    var input = form.querySelector('[name="' + inputName + '"]');
    if (!input) return;

    var ctx = canvas.getContext("2d");
    var drawing = false;
    var last = null;

    function pos(ev) {
      var rect = canvas.getBoundingClientRect();
      var scaleX = canvas.width / rect.width;
      var scaleY = canvas.height / rect.height;
      var clientX = ev.clientX;
      var clientY = ev.clientY;
      if (ev.touches && ev.touches[0]) {
        clientX = ev.touches[0].clientX;
        clientY = ev.touches[0].clientY;
      }
      return {
        x: (clientX - rect.left) * scaleX,
        y: (clientY - rect.top) * scaleY,
      };
    }

    function start(ev) {
      ev.preventDefault();
      drawing = true;
      last = pos(ev);
    }

    function move(ev) {
      if (!drawing) return;
      ev.preventDefault();
      var p = pos(ev);
      ctx.strokeStyle = "#0f172a";
      ctx.lineWidth = 2;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.beginPath();
      ctx.moveTo(last.x, last.y);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
      last = p;
    }

    function end(ev) {
      if (ev) ev.preventDefault();
      drawing = false;
      last = null;
    }

    canvas.addEventListener("mousedown", start);
    canvas.addEventListener("mousemove", move);
    canvas.addEventListener("mouseup", end);
    canvas.addEventListener("mouseleave", end);
    canvas.addEventListener("touchstart", start, { passive: false });
    canvas.addEventListener("touchmove", move, { passive: false });
    canvas.addEventListener("touchend", end);
    canvas.addEventListener("touchcancel", end);

    var wrap = canvas.closest(".formato-firma-block");
    if (wrap) {
      var clearBtn = wrap.querySelector(".formato-firma-clear");
      if (clearBtn) {
        clearBtn.addEventListener("click", function () {
          ctx.clearRect(0, 0, canvas.width, canvas.height);
          input.value = "";
        });
      }
    }
  }

  function onSubmit(form) {
    form.querySelectorAll(".formato-firma-canvas").forEach(function (canvas) {
      var inputName = canvas.getAttribute("data-input-name");
      if (!inputName) return;
      var input = form.querySelector('[name="' + inputName + '"]');
      if (!input) return;
      if (!canvasIsBlank(canvas)) {
        input.value = canvas.toDataURL("image/png");
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".formato-firma-canvas").forEach(bindCanvas);
    var form = document.getElementById("formato-aceptacion-form");
    if (form) {
      /* capture: true — rellenar ocultos antes que otros listeners del submit */
      form.addEventListener(
        "submit",
        function () {
          onSubmit(form);
        },
        true
      );
    }
  });
})();
