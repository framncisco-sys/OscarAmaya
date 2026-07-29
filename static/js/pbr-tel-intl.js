/**
 * Teléfonos en toda la app.
 * Al escribir: permite dígitos, «+», espacios y guiones (sin cortar a 8).
 * Al salir del campo (blur):
 *   - 8 dígitos o menos sin «+» → El Salvador (0000-0000)
 *   - con «+» o más de 8 dígitos → formato internacional
 */
(function () {
  "use strict";

  var REGION_LABEL = {
    SV: "El Salvador (+503)",
    GT: "Guatemala (+502)",
    HN: "Honduras (+504)",
    NI: "Nicaragua (+505)",
    CR: "Costa Rica (+506)",
    PA: "Panamá (+507)",
    MX: "México (+52)",
    US: "Estados Unidos (+1)",
    CA: "Canadá (+1)",
    ES: "España (+34)",
    CO: "Colombia (+57)",
    VE: "Venezuela (+58)",
    EC: "Ecuador (+593)",
    PE: "Perú (+51)",
    CL: "Chile (+56)",
    AR: "Argentina (+54)",
    BR: "Brasil (+55)",
    DO: "Rep. Dominicana (+1)",
  };

  var DIAL_TO_REGION = [
    ["593", "EC"],
    ["502", "GT"],
    ["503", "SV"],
    ["504", "HN"],
    ["505", "NI"],
    ["506", "CR"],
    ["507", "PA"],
    ["51", "PE"],
    ["52", "MX"],
    ["54", "AR"],
    ["55", "BR"],
    ["56", "CL"],
    ["57", "CO"],
    ["58", "VE"],
    ["34", "ES"],
    ["1", "US"],
  ];

  function digitsOnly(s) {
    return String(s || "").replace(/\D/g, "");
  }

  function setHint(el, region) {
    var wrap = el.closest(".field") || el.parentElement;
    if (!wrap) return;
    var hint = wrap.querySelector(".tel-intl-hint");
    if (!region) {
      if (hint) hint.textContent = "";
      return;
    }
    if (!hint) {
      hint = document.createElement("div");
      hint.className = "field__help muted tel-intl-hint";
      wrap.appendChild(hint);
    }
    hint.textContent = "País: " + (REGION_LABEL[region] || region);
  }

  function detectDial(digits) {
    var d = digits;
    if (d.slice(0, 2) === "00") d = d.slice(2);
    for (var i = 0; i < DIAL_TO_REGION.length; i++) {
      var dial = DIAL_TO_REGION[i][0];
      var region = DIAL_TO_REGION[i][1];
      if (d.indexOf(dial) === 0 && d.length >= dial.length + 4) {
        return { dial: dial, region: region, national: d.slice(dial.length), digits: d };
      }
    }
    return { dial: null, region: null, national: d, digits: d };
  }

  /** Solo limpia caracteres raros; NO limita a 8 dígitos. */
  function sanitizeTyping(el) {
    var raw = String(el.value || "");
    var caret = el.selectionStart;
    var before = raw.length;
    var cleaned = raw.replace(/[^\d+\s\-().]/g, "");
    // Un solo «+» y solo al inicio (si lo escribieron, lo respetamos al frente)
    var plusCount = (cleaned.match(/\+/g) || []).length;
    if (plusCount > 1) {
      cleaned = cleaned.replace(/\+/g, "");
      cleaned = "+" + cleaned;
    } else if (plusCount === 1 && cleaned.indexOf("+") > 0) {
      cleaned = "+" + cleaned.replace(/\+/g, "");
    }
    cleaned = cleaned.slice(0, 40);
    el.value = cleaned;
    if (typeof caret === "number") {
      var delta = cleaned.length - before;
      var next = Math.max(0, caret + delta);
      try {
        el.setSelectionRange(next, next);
      } catch (e) {}
    }
    updateHintLive(el);
  }

  function updateHintLive(el) {
    var raw = String(el.value || "").trim();
    var d = digitsOnly(raw);
    if (!d) {
      setHint(el, null);
      return;
    }
    if (raw.indexOf("+") !== -1 || d.length > 8) {
      var info = detectDial(d);
      setHint(el, info.region || null);
      return;
    }
    setHint(el, d.length >= 7 ? "SV" : null);
  }

  function formatSvLocal(el) {
    var d = digitsOnly(el.value).slice(0, 8);
    if (d.length <= 4) {
      el.value = d;
    } else {
      el.value = d.slice(0, 4) + "-" + d.slice(4);
    }
    setHint(el, d.length === 8 ? "SV" : d.length >= 7 ? "SV" : null);
  }

  function formatIntl(el) {
    var d = digitsOnly(el.value);
    if (!d) {
      el.value = "+";
      setHint(el, null);
      return;
    }
    if (d.slice(0, 2) === "00") d = d.slice(2);
    var info = detectDial(d);
    var dial = info.dial;
    var region = info.region;
    var national = digitsOnly(info.national);

    if (dial && region === "SV") {
      national = national.slice(0, 8);
      el.value =
        national.length > 4
          ? "+503 " + national.slice(0, 4) + " " + national.slice(4)
          : "+503 " + national;
      setHint(el, "SV");
      return;
    }

    if (dial) {
      national = national.slice(0, 14);
      var natFmt = national;
      if (region === "MX" && national.length > 2) {
        natFmt =
          national.length <= 6
            ? national.slice(0, 2) + " " + national.slice(2)
            : national.slice(0, 2) + " " + national.slice(2, 6) + " " + national.slice(6);
      } else if ((region === "US" || region === "CA" || region === "DO") && national.length > 3) {
        natFmt =
          national.length <= 6
            ? "(" + national.slice(0, 3) + ") " + national.slice(3)
            : "(" + national.slice(0, 3) + ") " + national.slice(3, 6) + "-" + national.slice(6);
      } else if (national.length > 4) {
        natFmt = national.replace(/(\d{3,4})(?=\d)/g, "$1 ").trim();
      }
      el.value = ("+" + dial + " " + natFmt).trim().slice(0, 40);
      setHint(el, region);
      return;
    }

    el.value = ("+" + d).slice(0, 40);
    setHint(el, null);
  }

  function formatOnBlur(el) {
    var raw = String(el.value || "").trim();
    if (!raw) {
      setHint(el, null);
      return;
    }
    var d = digitsOnly(raw);
    var wantsIntl = raw.indexOf("+") !== -1 || d.length > 8;
    if (wantsIntl) {
      formatIntl(el);
    } else {
      formatSvLocal(el);
    }
  }

  function isTelField(el) {
    if (!el || el.disabled || el.readOnly) return false;
    if (el.getAttribute("data-tel-intl") === "1") return true;
    if ((el.getAttribute("inputmode") || "") === "tel") return true;
    var name = (el.name || el.id || "").toLowerCase();
    return /telefono|tel_|phone|celular|whatsapp/.test(name);
  }

  function bind(el) {
    if (!el || el.dataset.pbrTelBound === "1") return;
    el.dataset.pbrTelBound = "1";
    el.addEventListener("input", function () {
      sanitizeTyping(el);
    });
    el.addEventListener("blur", function () {
      formatOnBlur(el);
    });
    if (el.value) formatOnBlur(el);
  }

  function scan(root) {
    var scope = root || document;
    var nodes = scope.querySelectorAll(
      'input[data-tel-intl="1"], input[inputmode="tel"], input[type="tel"], input[name*="telefono"], input[id*="telefono"]'
    );
    for (var i = 0; i < nodes.length; i++) {
      if (isTelField(nodes[i])) bind(nodes[i]);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    scan(document);
  });

  window.PbrTelIntl = { scan: scan, format: formatOnBlur };
})();
