/**
 * Detecta dispositivo y aplica data-* / clases en <html> para CSS adaptable.
 *
 * Vista fina (data-pbr-view): phone | tablet | laptop | desktop | large | tv
 * Clase simple (data-pbr-class): mobile | computer | tv
 * Dispositivo (data-pbr-device): phone | tablet | laptop | desktop | tv
 */
(function (global) {
  "use strict";

  var UA_MOBILE = /Android|webOS|iPhone|iPod|BlackBerry|IEMobile|Opera Mini/i;
  var UA_TABLET = /iPad|Tablet|PlayBook|Silk|Android(?!.*Mobile)/i;
  var UA_TV =
    /SmartTV|SMART-TV|GoogleTV|AppleTV|HbbTV|NetCast|Tizen|Web0S|webOS(?!.*Mobile)|BRAVIA|Viera|AFT[A-Z]|FireTV|Roku|CrKey|TV Safari/i;

  var VIEW_CLASSES = [
    "pbr-view-phone",
    "pbr-view-tablet",
    "pbr-view-laptop",
    "pbr-view-desktop",
    "pbr-view-large",
    "pbr-view-tv",
  ];
  var CLASS_CLASSES = ["pbr-class-mobile", "pbr-class-computer", "pbr-class-tv"];

  function classify(w, h, ua, fine, coarse) {
    var mobileUA = UA_MOBILE.test(ua);
    var tabletUA = UA_TABLET.test(ua);
    var tvUA = UA_TV.test(ua);
    var touchNarrow = coarse && !fine && Math.min(w, h || w) < 920;

    var view;
    var device;

    if (tvUA || w >= 3840 || (w >= 2560 && !fine && !mobileUA && !tabletUA)) {
      view = "tv";
      device = "tv";
    } else if (w < 640 || (mobileUA && !tabletUA && w < 900) || (touchNarrow && w < 700)) {
      view = "phone";
      device = "phone";
    } else if (w < 1024 || tabletUA || touchNarrow || (coarse && w < 1100 && !fine)) {
      view = "tablet";
      device = "tablet";
    } else if (w < 1440) {
      view = "laptop";
      device = "laptop";
    } else if (w < 1920) {
      view = "desktop";
      device = "desktop";
    } else if (w < 2560) {
      view = "large";
      device = "desktop";
    } else {
      view = "tv";
      device = "tv";
    }

    var deviceClass = "computer";
    if (device === "phone" || device === "tablet") {
      deviceClass = "mobile";
    } else if (device === "tv") {
      deviceClass = "tv";
    }

    return { view: view, device: device, deviceClass: deviceClass };
  }

  function isTyping() {
    var ae = document.activeElement;
    if (!ae) return false;
    if (!/^(INPUT|TEXTAREA|SELECT)$/i.test(ae.tagName)) return false;
    var t = ae.type || "";
    return t !== "checkbox" && t !== "radio" && t !== "button" && t !== "submit" && t !== "file" && t !== "hidden";
  }

  function detect(force) {
    if (!force && isTyping()) return;

    var html = document.documentElement;
    var w = window.innerWidth || html.clientWidth || 1024;
    var h = window.innerHeight || html.clientHeight || 768;
    var ua = navigator.userAgent || "";
    var coarse = false;
    var fine = true;
    var hover = true;
    var reduce = false;

    try {
      coarse = window.matchMedia("(pointer: coarse)").matches;
      fine = window.matchMedia("(pointer: fine)").matches;
      hover = window.matchMedia("(hover: hover)").matches;
      reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (e) {
      /* ignore */
    }

    var result = classify(w, h, ua, fine, coarse);
    var view = result.view;
    var device = result.device;
    var deviceClass = result.deviceClass;
    var orientation = w >= h ? "landscape" : "portrait";
    var touch = coarse || !hover;

    var prevKey =
      (html.dataset.pbrView || "") +
      "|" +
      (html.dataset.pbrClass || "") +
      "|" +
      (html.dataset.pbrOrientation || "");
    var nextKey = view + "|" + deviceClass + "|" + orientation;

    html.dataset.pbrView = view;
    html.dataset.pbrDevice = device;
    html.dataset.pbrClass = deviceClass;
    html.dataset.pbrOrientation = orientation;
    html.dataset.pbrPointer = coarse ? "coarse" : "fine";
    html.dataset.pbrHover = hover ? "yes" : "no";
    html.dataset.pbrTouch = touch ? "yes" : "no";
    html.dataset.pbrWidth = String(w);

    if (reduce) {
      html.dataset.pbrReducedMotion = "1";
    } else {
      delete html.dataset.pbrReducedMotion;
    }

    VIEW_CLASSES.forEach(function (c) {
      html.classList.remove(c);
    });
    CLASS_CLASSES.forEach(function (c) {
      html.classList.remove(c);
    });
    html.classList.add("pbr-view-" + view);
    html.classList.add("pbr-class-" + deviceClass);

    try {
      global.sessionStorage.setItem(
        "pbr_viewport",
        JSON.stringify({
          view: view,
          device: device,
          deviceClass: deviceClass,
          width: w,
          height: h,
          orientation: orientation,
        })
      );
    } catch (e) {
      /* private mode */
    }

    // No re-disparar layout si no cambió la clasificación (evita saltos con teclado).
    if (!force && prevKey === nextKey) return;

    global.dispatchEvent(
      new CustomEvent("pbr:viewport", {
        detail: {
          view: view,
          device: device,
          deviceClass: deviceClass,
          width: w,
          height: h,
          orientation: orientation,
          touch: touch,
        },
      })
    );
  }

  var resizeTimer;
  var lastWidth = 0;

  function schedule() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      if (isTyping()) return;
      var w = window.innerWidth || document.documentElement.clientWidth || 0;
      // Solo reclasificar si el ANCHO cambió de verdad (rotar / partir pantalla).
      // El teclado cambia la altura y a veces 1–2 px el ancho → ignora.
      if (lastWidth && Math.abs(w - lastWidth) < 48) return;
      lastWidth = w;
      detect(false);
    }, 180);
  }

  detect(true);
  lastWidth = window.innerWidth || document.documentElement.clientWidth || 0;
  window.addEventListener("resize", schedule);
  window.addEventListener("orientationchange", function () {
    window.setTimeout(function () {
      lastWidth = 0;
      detect(true);
    }, 250);
  });

  try {
    window.matchMedia("(pointer: coarse)").addEventListener("change", function () {
      detect(true);
    });
    window.matchMedia("(hover: hover)").addEventListener("change", function () {
      detect(true);
    });
  } catch (e) {
    /* older browsers */
  }

  function isTextField(el) {
    if (!el || !/^(INPUT|TEXTAREA|SELECT)$/i.test(el.tagName)) return false;
    var t = (el.type || "").toLowerCase();
    return (
      t !== "checkbox" &&
      t !== "radio" &&
      t !== "button" &&
      t !== "submit" &&
      t !== "file" &&
      t !== "hidden"
    );
  }

  function syncVisualViewport() {
    var html = document.documentElement;
    if (html.dataset.pbrClass !== "mobile") return;
    var vv = global.visualViewport;
    if (!vv) return;
    html.style.setProperty("--pbr-vvh", vv.height + "px");
    html.style.setProperty("--pbr-vv-offset", vv.offsetTop + "px");
  }

  function setKeyboardOpen(open) {
    var html = document.documentElement;
    if (html.dataset.pbrClass !== "mobile") return;
    if (open) {
      html.classList.add("pbr-kbd-open");
      syncVisualViewport();
    } else {
      html.classList.remove("pbr-kbd-open");
      html.style.removeProperty("--pbr-vvh");
      html.style.removeProperty("--pbr-vv-offset");
    }
  }

  function scrollFieldIntoView(el) {
    if (!el || !el.scrollIntoView) return;
    window.setTimeout(function () {
      try {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
      } catch (e) {
        el.scrollIntoView(true);
      }
      syncVisualViewport();
    }, 320);
  }

  document.addEventListener(
    "focusin",
    function (ev) {
      if (!isTextField(ev.target)) return;
      setKeyboardOpen(true);
      scrollFieldIntoView(ev.target);
    },
    true
  );

  document.addEventListener(
    "focusout",
    function () {
      window.setTimeout(function () {
        if (isTextField(document.activeElement)) return;
        setKeyboardOpen(false);
      }, 120);
    },
    true
  );

  if (global.visualViewport) {
    global.visualViewport.addEventListener("resize", function () {
      if (document.documentElement.classList.contains("pbr-kbd-open")) {
        syncVisualViewport();
      }
    });
    global.visualViewport.addEventListener("scroll", syncVisualViewport);
  }

  global.pbrApplyViewport = function () {
    detect(true);
  };
  global.pbrGetViewport = function () {
    return {
      view: document.documentElement.dataset.pbrView,
      device: document.documentElement.dataset.pbrDevice,
      deviceClass: document.documentElement.dataset.pbrClass,
      orientation: document.documentElement.dataset.pbrOrientation,
      touch: document.documentElement.dataset.pbrTouch === "yes",
    };
  };
})(window);
