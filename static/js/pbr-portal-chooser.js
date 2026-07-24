/**
 * Portal de elección de empresa: brillo, atenuar hermana, teclas 1/2.
 */
(function () {
  var root = document.querySelector("[data-pbr-portal-chooser]");
  if (!root) return;

  var doors = Array.prototype.slice.call(root.querySelectorAll("[data-pbr-brand-card]"));
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function clearFocus() {
    root.classList.remove("is-choosing");
    doors.forEach(function (d) {
      d.classList.remove("is-hot", "is-dim");
    });
  }

  doors.forEach(function (door) {
    if (!reduceMotion) {
      door.addEventListener("pointermove", function (e) {
        var rect = door.getBoundingClientRect();
        var x = ((e.clientX - rect.left) / rect.width) * 100;
        var y = ((e.clientY - rect.top) / rect.height) * 100;
        door.style.setProperty("--portal-mx", x + "%");
        door.style.setProperty("--portal-my", y + "%");
      });
    }

    door.addEventListener("pointerenter", function () {
      root.classList.add("is-choosing");
      doors.forEach(function (d) {
        d.classList.toggle("is-hot", d === door);
        d.classList.toggle("is-dim", d !== door);
      });
    });

    door.addEventListener("pointerleave", function () {
      clearFocus();
    });

    door.addEventListener("focus", function () {
      root.classList.add("is-choosing");
      doors.forEach(function (d) {
        d.classList.toggle("is-hot", d === door);
        d.classList.toggle("is-dim", d !== door);
      });
    });

    door.addEventListener("blur", function () {
      if (!root.querySelector("[data-pbr-brand-card]:hover, [data-pbr-brand-card]:focus-visible")) {
        clearFocus();
      }
    });

    door.addEventListener("pointerdown", function () {
      door.classList.add("is-pressing");
    });
    ["pointerup", "pointerleave", "pointercancel"].forEach(function (ev) {
      door.addEventListener(ev, function () {
        door.classList.remove("is-pressing");
      });
    });
  });

  document.addEventListener("keydown", function (e) {
    if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA")) return;
    var key = e.key;
    if (key !== "1" && key !== "2") return;
    var target = doors.find(function (d) {
      return d.getAttribute("data-portal-key") === key;
    });
    if (!target) return;
    e.preventDefault();
    target.classList.add("is-pressing");
    window.setTimeout(function () {
      window.location.href = target.href;
    }, 120);
  });
})();
