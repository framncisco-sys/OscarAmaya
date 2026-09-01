(function () {
  "use strict";

  var ESTADO_COLORS = {
    DISPONIBLE: { bg: "#22c55e", border: "#15803d" },
    RESERVADO: { bg: "#fbbf24", border: "#b45309" },
    VENDIDO: { bg: "#60a5fa", border: "#1d4ed8" },
    BLOQUEADO: { bg: "#94a3b8", border: "#64748b" },
  };

  var STACK_COLORS = {
    vendidos: { bg: "#3b82f6", border: "#1d4ed8" },
    reservados: { bg: "#f59e0b", border: "#b45309" },
    disponibles: { bg: "#22c55e", border: "#15803d" },
  };

  function readChartsData() {
    var el = document.getElementById("pbr-dash-charts");
    if (!el || !el.textContent) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return null;
    }
  }

  function prefersReducedMotion() {
    return (
      document.documentElement.getAttribute("data-pbr-reduced-motion") === "1" ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  }

  function formatMoney(n) {
    if (typeof n !== "number" || isNaN(n)) return "0";
    return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
  }

  function animateCount(el, target, duration) {
    if (!el) return;
    var reduced = prefersReducedMotion();
    var end = Number(target);
    if (isNaN(end)) return;
    if (reduced || duration <= 0) {
      el.textContent = String(end);
      return;
    }
    var start = 0;
    var startTime = null;
    function step(ts) {
      if (!startTime) startTime = ts;
      var p = Math.min((ts - startTime) / duration, 1);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = String(Math.round(start + (end - start) * eased));
      if (p < 1) window.requestAnimationFrame(step);
    }
    window.requestAnimationFrame(step);
  }

  function setupKpiCounters() {
    document.querySelectorAll("[data-dash-count]").forEach(function (el) {
      animateCount(el, el.getAttribute("data-dash-count"), 720);
    });
    document.querySelectorAll("[data-dash-money]").forEach(function (el) {
      var val = Number(el.getAttribute("data-dash-money"));
      if (prefersReducedMotion()) {
        el.textContent = formatMoney(val);
        return;
      }
      var start = 0;
      var startTime = null;
      var duration = 900;
      function step(ts) {
        if (!startTime) startTime = ts;
        var p = Math.min((ts - startTime) / duration, 1);
        var eased = 1 - Math.pow(1 - p, 3);
        el.textContent = formatMoney(start + (val - start) * eased);
        if (p < 1) window.requestAnimationFrame(step);
      }
      window.requestAnimationFrame(step);
    });
  }

  function estadoColor(key) {
    return ESTADO_COLORS[key] || { bg: "#cbd5e1", border: "#64748b" };
  }

  function buildEstadoChart(canvas, data) {
    if (!canvas || !data || !data.estado || !data.estado.length) return null;
    var labels = data.estado.map(function (e) {
      return e.label;
    });
    var counts = data.estado.map(function (e) {
      return e.count;
    });
    var colors = data.estado.map(function (e) {
      return estadoColor(e.key).bg;
    });
    var borders = data.estado.map(function (e) {
      return estadoColor(e.key).border;
    });

    return new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: labels,
        datasets: [
          {
            data: counts,
            backgroundColor: colors,
            borderColor: borders,
            borderWidth: 2,
            hoverOffset: 6,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "62%",
        plugins: {
          legend: {
            position: "bottom",
            labels: {
              boxWidth: 12,
              boxHeight: 12,
              padding: 14,
              font: { size: 12, weight: "600" },
              color: "#475569",
            },
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var total = data.totales.inventario || 0;
                var val = ctx.raw || 0;
                var pct = total ? ((val * 100) / total).toFixed(1) : "0";
                return " " + ctx.label + ": " + val + " (" + pct + "%)";
              },
            },
          },
        },
        animation: prefersReducedMotion() ? false : { duration: 800 },
      },
    });
  }

  function buildPoligonoChart(canvas, data) {
    if (!canvas || !data || !data.poligonos || !data.poligonos.length) return null;
    var rows = data.poligonos.slice(0, 10);
    var labels = rows.map(function (r) {
      return r.nombre;
    });

    return new Chart(canvas, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Pagado totalmente",
            data: rows.map(function (r) {
              return r.vendidos;
            }),
            backgroundColor: STACK_COLORS.vendidos.bg,
            borderColor: STACK_COLORS.vendidos.border,
            borderWidth: 1,
            borderRadius: 4,
            stack: "inv",
          },
          {
            label: "Reservado",
            data: rows.map(function (r) {
              return r.reservados;
            }),
            backgroundColor: STACK_COLORS.reservados.bg,
            borderColor: STACK_COLORS.reservados.border,
            borderWidth: 1,
            borderRadius: 4,
            stack: "inv",
          },
          {
            label: "Disponible",
            data: rows.map(function (r) {
              return r.disponibles;
            }),
            backgroundColor: STACK_COLORS.disponibles.bg,
            borderColor: STACK_COLORS.disponibles.border,
            borderWidth: 1,
            borderRadius: 4,
            stack: "inv",
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            stacked: true,
            grid: { color: "rgba(148,163,184,0.15)" },
            ticks: { precision: 0, color: "#64748b" },
          },
          y: {
            stacked: true,
            grid: { display: false },
            ticks: { color: "#334155", font: { size: 11, weight: "600" } },
          },
        },
        plugins: {
          legend: {
            position: "bottom",
            labels: {
              boxWidth: 12,
              boxHeight: 12,
              padding: 12,
              font: { size: 11, weight: "600" },
              color: "#475569",
            },
          },
          tooltip: {
            callbacks: {
              afterTitle: function (items) {
                if (!items.length) return "";
                var idx = items[0].dataIndex;
                var row = rows[idx];
                if (!row) return "";
                return row.proyecto + " · " + row.ocupacion_pct + "% ocupado";
              },
            },
          },
        },
        animation: prefersReducedMotion() ? false : { duration: 700 },
      },
    });
  }

  function setupStatChartHover(chart, data) {
    if (!chart || !data || !data.estado) return;
    var keyByClass = {
      "dash-stat--ok": "DISPONIBLE",
      "dash-stat--warn": "RESERVADO",
      "dash-stat--sold": "VENDIDO",
    };
    var stats = document.querySelectorAll(".dash-stat");
    if (!stats.length) return;

    function indexForStat(el) {
      var key = null;
      Object.keys(keyByClass).forEach(function (cls) {
        if (el.classList.contains(cls)) key = keyByClass[cls];
      });
      if (!key) return -1;
      for (var i = 0; i < data.estado.length; i++) {
        if (data.estado[i].key === key) return i;
      }
      return -1;
    }

    function clearActive() {
      chart.setActiveElements([]);
      chart.update();
      stats.forEach(function (s) {
        s.classList.remove("is-chart-active");
      });
    }

    stats.forEach(function (stat) {
      stat.addEventListener("mouseenter", function () {
        var idx = indexForStat(stat);
        if (idx < 0) return;
        chart.setActiveElements([{ datasetIndex: 0, index: idx }]);
        chart.update();
        stats.forEach(function (s) {
          s.classList.toggle("is-chart-active", s === stat);
        });
      });
      stat.addEventListener("focus", function () {
        stat.dispatchEvent(new Event("mouseenter"));
      });
    });

    document.querySelector(".dash-stats")?.addEventListener("mouseleave", clearActive);
  }

  function init() {
    if (!document.querySelector(".dash--v2")) return;
    setupKpiCounters();

    var data = readChartsData();
    if (!data || typeof Chart === "undefined") return;

    var estadoCanvas = document.getElementById("pbr-dash-chart-estado");
    var poligonoCanvas = document.getElementById("pbr-dash-chart-poligono");
    var estadoChart = buildEstadoChart(estadoCanvas, data);
    buildPoligonoChart(poligonoCanvas, data);
    setupStatChartHover(estadoChart, data);

    var centerTotal = document.getElementById("pbr-dash-chart-center");
    if (centerTotal && data.totales) {
      animateCount(centerTotal, data.totales.inventario, 800);
    }
    var centerValor = document.getElementById("pbr-dash-chart-valor");
    if (centerValor && data.totales) {
      centerValor.textContent = "$" + formatMoney(data.totales.valor_disponible);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
