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

  function classify(w, ua, fine, coarse) {
    var mobileUA = UA_MOBILE.test(ua);
    var tabletUA = UA_TABLET.test(ua);
    var tvUA = UA_TV.test(ua);

    var view;
    var device;

    if (tvUA || w >= 3840 || (w >= 2560 && !fine && !mobileUA && !tabletUA)) {
      view = "tv";
      device = "tv";
    } else if (w < 640 || (mobileUA && !tabletUA && w < 900)) {
      view = "phone";
      device = "phone";
    } else if (w < 1024 || tabletUA || (coarse && w < 1100 && !fine)) {
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

  function detect() {
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

    var result = classify(w, ua, fine, coarse);
    var view = result.view;
    var device = result.device;
    var deviceClass = result.deviceClass;
    var orientation = w >= h ? "landscape" : "portrait";
    var touch = coarse || !hover;

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
      var w = window.innerWidth || document.documentElement.clientWidth || 0;
      var ae = document.activeElement;
      var typing =
        ae &&
        /^(INPUT|TEXTAREA|SELECT)$/i.test(ae.tagName) &&
        ae.type !== "checkbox" &&
        ae.type !== "radio" &&
        ae.type !== "button" &&
        ae.type !== "submit";
      // Teclado móvil cambia la altura (visualViewport) pero no el ancho:
      // no reclasificar layout ni disparar pbr:viewport (evita que la página “salte”).
      if (lastWidth && Math.abs(w - lastWidth) < 2 && typing) {
        return;
      }
      lastWidth = w;
      detect();
    }, 120);
  }

  detect();
  lastWidth = window.innerWidth || document.documentElement.clientWidth || 0;
  window.addEventListener("resize", schedule);
  window.addEventListener("orientationchange", schedule);
  // No escuchar visualViewport.resize: en iOS/Android solo refleja el teclado.

  try {
    window.matchMedia("(pointer: coarse)").addEventListener("change", detect);
    window.matchMedia("(hover: hover)").addEventListener("change", detect);
    window.matchMedia("(prefers-reduced-motion: reduce)").addEventListener("change", detect);
  } catch (e) {
    /* older browsers */
  }

  global.pbrApplyViewport = detect;
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
