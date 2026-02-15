/* Lightweight fallback for Chart.js when external CDNs are blocked by CSP. */
(function (global) {
  'use strict';

  if (typeof global.Chart !== 'undefined') {
    return;
  }

  function toNumber(value) {
    var n = Number(value);
    return Number.isFinite(n) ? n : 0;
  }

  function normalizeValues(values) {
    if (!Array.isArray(values)) return [];
    return values.map(toNumber);
  }

  function defaultColors() {
    return [
      '#1a237e',
      '#303f9f',
      '#3f51b5',
      '#7986cb',
      '#c5cae9',
      '#e8eaf6',
      '#0ea5e9',
      '#10b981',
      '#f59e0b',
      '#ef4444'
    ];
  }

  function resolveColors(count, configured) {
    if (Array.isArray(configured) && configured.length) {
      return configured;
    }
    var palette = defaultColors();
    var out = [];
    for (var i = 0; i < count; i += 1) {
      out.push(palette[i % palette.length]);
    }
    return out;
  }

  function truncateLabel(label, maxLength) {
    var str = String(label || '');
    if (str.length <= maxLength) return str;
    return str.slice(0, Math.max(1, maxLength - 1)) + '…';
  }

  function prepareCanvas(ctx) {
    if (!ctx || !ctx.canvas) return { width: 0, height: 0 };
    var canvas = ctx.canvas;
    var rect = canvas.getBoundingClientRect();
    var ratio = global.devicePixelRatio || 1;
    var cssWidth = Math.max(1, Math.floor(rect.width || canvas.clientWidth || 400));
    var cssHeight = Math.max(1, Math.floor(rect.height || canvas.clientHeight || 220));
    var targetWidth = Math.max(1, Math.floor(cssWidth * ratio));
    var targetHeight = Math.max(1, Math.floor(cssHeight * ratio));

    if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
      canvas.width = targetWidth;
      canvas.height = targetHeight;
    }

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.textBaseline = 'middle';
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';

    return { width: cssWidth, height: cssHeight };
  }

  function drawNoData(ctx, dims, message) {
    if (!ctx || !dims) return;
    ctx.fillStyle = '#64748b';
    ctx.font = '12px Segoe UI, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(message || 'No chart data', dims.width / 2, dims.height / 2);
  }

  function LiteChart(ctx, config) {
    this.ctx = ctx || null;
    this.config = config || {};
    this.destroyed = false;
    this._onResize = this.draw.bind(this);
    if (global.addEventListener) {
      global.addEventListener('resize', this._onResize);
    }
    this.draw();
  }

  LiteChart.prototype.destroy = function () {
    if (this.destroyed) return;
    this.destroyed = true;
    if (global.removeEventListener && this._onResize) {
      global.removeEventListener('resize', this._onResize);
    }
    if (this.ctx && this.ctx.canvas) {
      this.ctx.setTransform(1, 0, 0, 1, 0, 0);
      this.ctx.clearRect(0, 0, this.ctx.canvas.width, this.ctx.canvas.height);
    }
  };

  LiteChart.prototype._getData = function () {
    var data = (this.config && this.config.data) || {};
    var datasets = Array.isArray(data.datasets) ? data.datasets : [];
    var dataset = datasets[0] || {};
    var labels = Array.isArray(data.labels) ? data.labels : [];
    var values = normalizeValues(dataset.data || []);
    var colors = resolveColors(values.length, dataset.backgroundColor);

    return {
      labels: labels,
      values: values,
      colors: colors
    };
  };

  LiteChart.prototype.draw = function () {
    if (this.destroyed || !this.ctx || !this.ctx.canvas) return;
    var type = String((this.config && this.config.type) || 'bar').toLowerCase();
    if (type === 'doughnut') {
      this._drawPie(true);
      return;
    }
    if (type === 'pie') {
      this._drawPie(false);
      return;
    }
    if (type === 'line') {
      this._drawLine();
      return;
    }
    this._drawBar();
  };

  LiteChart.prototype._drawBar = function () {
    var ctx = this.ctx;
    var dims = prepareCanvas(ctx);
    var data = this._getData();
    if (!data.values.length) {
      drawNoData(ctx, dims);
      return;
    }

    var left = 34;
    var right = 14;
    var top = 14;
    var bottom = 28;
    var chartW = Math.max(1, dims.width - left - right);
    var chartH = Math.max(1, dims.height - top - bottom);
    var maxVal = Math.max.apply(null, data.values.concat([0]));
    if (maxVal <= 0) {
      drawNoData(ctx, dims);
      return;
    }

    var count = data.values.length;
    var gap = Math.max(6, chartW / (count * 4));
    var barW = Math.max(6, (chartW - gap * (count + 1)) / count);

    // Axis baseline
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(left, top + chartH);
    ctx.lineTo(left + chartW, top + chartH);
    ctx.stroke();

    ctx.font = '10px Segoe UI, sans-serif';
    ctx.textAlign = 'center';
    for (var i = 0; i < count; i += 1) {
      var value = data.values[i];
      var barH = (value / maxVal) * chartH;
      var x = left + gap + i * (barW + gap);
      var y = top + chartH - barH;

      ctx.fillStyle = data.colors[i % data.colors.length];
      ctx.fillRect(x, y, barW, barH);

      ctx.fillStyle = '#334155';
      ctx.fillText(truncateLabel(data.labels[i], 10), x + (barW / 2), top + chartH + 12);
    }
  };

  LiteChart.prototype._drawLine = function () {
    var ctx = this.ctx;
    var dims = prepareCanvas(ctx);
    var data = this._getData();
    if (!data.values.length) {
      drawNoData(ctx, dims);
      return;
    }

    var left = 30;
    var right = 12;
    var top = 14;
    var bottom = 26;
    var chartW = Math.max(1, dims.width - left - right);
    var chartH = Math.max(1, dims.height - top - bottom);
    var maxVal = Math.max.apply(null, data.values.concat([0]));
    var minVal = Math.min.apply(null, data.values.concat([0]));
    var range = Math.max(1, maxVal - minVal);

    // Axis baseline
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(left, top + chartH);
    ctx.lineTo(left + chartW, top + chartH);
    ctx.stroke();

    var stepX = data.values.length > 1 ? chartW / (data.values.length - 1) : 0;
    ctx.strokeStyle = data.colors[0];
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (var i = 0; i < data.values.length; i += 1) {
      var v = data.values[i];
      var x = left + (stepX * i);
      var y = top + chartH - ((v - minVal) / range) * chartH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // points
    for (var j = 0; j < data.values.length; j += 1) {
      var vv = data.values[j];
      var xx = left + (stepX * j);
      var yy = top + chartH - ((vv - minVal) / range) * chartH;
      ctx.fillStyle = data.colors[j % data.colors.length];
      ctx.beginPath();
      ctx.arc(xx, yy, 3, 0, Math.PI * 2);
      ctx.fill();
    }
  };

  LiteChart.prototype._drawPie = function (isDoughnut) {
    var ctx = this.ctx;
    var dims = prepareCanvas(ctx);
    var data = this._getData();
    if (!data.values.length) {
      drawNoData(ctx, dims);
      return;
    }

    var values = data.values.map(function (v) { return Math.max(0, v); });
    var total = values.reduce(function (sum, v) { return sum + v; }, 0);
    if (total <= 0) {
      drawNoData(ctx, dims);
      return;
    }

    var cx = dims.width / 2;
    var cy = dims.height / 2;
    var radius = Math.max(20, Math.min(dims.width, dims.height) * 0.36);
    var angle = -Math.PI / 2;

    for (var i = 0; i < values.length; i += 1) {
      var slice = (values[i] / total) * (Math.PI * 2);
      ctx.fillStyle = data.colors[i % data.colors.length];
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.arc(cx, cy, radius, angle, angle + slice);
      ctx.closePath();
      ctx.fill();
      angle += slice;
    }

    if (isDoughnut) {
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.arc(cx, cy, radius * 0.55, 0, Math.PI * 2);
      ctx.fill();
    }
  };

  global.Chart = LiteChart;
})(window);
