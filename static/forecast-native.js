/* V34: chart-native hollow OHLC candles and a pane-clipped probability guide. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GFINativeForecast = api;
})(typeof window === "object" ? window : this, function () {
  "use strict";
  const COLORS = { up: "#70e0bf", down: "#f07e91", entry: "#e3e8e5" };

  function median(values) {
    const sorted = [...values].sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    return sorted.length ? (sorted[middle] + sorted[Math.ceil(sorted.length / 2) - 1]) / 2 : 0;
  }

  function trueRanges(rows) {
    return rows.map((bar, index) => {
      const previous = index ? rows[index - 1].close : bar.open;
      return Math.max(bar.high - bar.low, Math.abs(bar.high - previous), Math.abs(bar.low - previous));
    });
  }

  function volatilityCalibration(rows, marketBars, entry, startTime) {
    // Use only completed market bars BEFORE Entry. Never use the real
    // candles under the preview, which are future information at Entry.
    const recent = (marketBars || []).filter(bar => bar.time < startTime &&
      [bar.time, bar.open, bar.high, bar.low, bar.close].every(Number.isFinite))
      .sort((a, b) => a.time - b.time).slice(-33);
    const ranges = trueRanges(recent).slice(1);
    const result = { scale:1, basis:'unscaled', referenceBars:ranges.length };
    if (ranges.length < 14 || !rows?.length || !(entry > 0)) return result;
    const marketRange = median(ranges);
    const sourceRange = median(trueRanges(rows));
    if (!(marketRange > 0) || !(sourceRange > 0)) return result;
    // One positive affine scale for the WHOLE path. Body/wick proportions,
    // relative candle sizes, gaps, and pullbacks remain those of the actual
    // representative case. No per-candle clamps or stretching to TP/SL.
    return { scale:marketRange / (entry * sourceRange), basis:'pre_entry_median_true_range',
      referenceBars:ranges.length, marketRange, sourceRange:entry * sourceRange };
  }

  function projectOHLC(rows, entry, startTime, step, horizon = 10, entryAligned = false, scale = 1, target = undefined) {
    if (![entry, startTime, step].every(Number.isFinite) || entry <= 0 || step <= 0 || !Array.isArray(rows)) return [];
    if (!Number.isFinite(scale) || scale <= 0) return [];
    const sample = rows.slice(0, horizon);
    if (!sample.length || sample.some(row => !row || ![row.open, row.high, row.low, row.close].every(Number.isFinite))) return [];
    // New API paths include the entry bar (normalized Open = 1). Older API
    // paths skipped that bar: translate the entire path once to anchor its
    // first open, preserving its relative bodies and wicks. Volatility
    // calibration applies one shared scale to every price offset. Never stretch
    // the last close to TP/SL or add an invented pullback. V40 opts into one
    // additional affine normalization below so the terminal close lands on
    // the statistical TP/SL level without changing the candle sequence.
    const base = entryAligned ? 1 : sample[0].open;
    const price = value => entry * (1 + (value - base) * scale);
    let projected = sample.map((row, index) => {
      const open = index === 0 ? entry : price(row.open);
      const close = price(row.close);
      return {
        // Keep the Entry candle untouched; preview slots begin
        // exactly one real bar to its right.
        time: startTime + (index + 1) * step,
        open,
        high: Math.max(open, close, price(row.high)),
        low: Math.min(open, close, price(row.low)),
        close,
      };
    });
    if (!Number.isFinite(target) || projected.length < 2) return projected;

    const lastClose = projected.at(-1).close;
    const wantedOffset = target - entry;
    const currentOffset = lastClose - entry;
    const sameDirection = wantedOffset === 0 || currentOffset === 0 ||
      Math.sign(wantedOffset) === Math.sign(currentOffset);
    // Prefer a shared multiplicative stretch: this preserves the relative
    // candle bodies, wick sizes, pullbacks, and gaps exactly. If the selected
    // historical path ends on the wrong side, use a linear endpoint bridge
    // instead of mirroring the whole path into a fabricated opposite branch.
    if (Math.abs(currentOffset) > 1e-12 && sameDirection) {
      const factor = wantedOffset / currentOffset;
      projected = projected.map((bar, index) => {
        const scaleValue = value => entry + (value - entry) * factor;
        const open = index === 0 ? entry : scaleValue(bar.open);
        const close = scaleValue(bar.close);
        const high = scaleValue(bar.high);
        const low = scaleValue(bar.low);
        return { ...bar, open, high:Math.max(open, close, high), low:Math.min(open, close, low), close };
      });
    } else {
      const correction = target - lastClose;
      const lastIndex = projected.length - 1;
      projected = projected.map((bar, index) => {
        const shift = correction * (index / lastIndex);
        const open = index === 0 ? entry : bar.open + shift;
        const close = bar.close + shift;
        return { ...bar, open, high:Math.max(open, close, bar.high + shift), low:Math.min(open, close, bar.low + shift), close };
      });
    }
    // Guard against floating-point drift at the contract point.
    const endpoint = projected.at(-1);
    const finalShift = target - endpoint.close;
    if (Math.abs(finalShift) > 1e-9) {
      const last = projected.length - 1;
      projected = projected.map((bar, index) => {
        const shift = finalShift * (index / last);
        const open = index === 0 ? entry : bar.open + shift;
        const close = bar.close + shift;
        return { ...bar, open, high:Math.max(open, close, bar.high + shift), low:Math.min(open, close, bar.low + shift), close };
      });
    }
    return projected;
  }

  function candleOptions(side = 'up') {
    const color = COLORS[side];
    return {
      priceScaleId: "right", upColor: "transparent", downColor: "transparent",
      // Forecast color identifies the scenario, including its pullbacks.
      borderVisible: true, borderUpColor: color, borderDownColor: color,
      wickVisible: true, wickUpColor: color, wickDownColor: color,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      // Same built-in candlestick renderer, bar spacing, device-pixel
      // rounding and price transform as the real market series.
    };
  }

  function intersectionMasks(up, down) {
    const body = [], wickA = [], wickB = [];
    const downByTime = new Map(down.map(bar => [bar.time, bar]));
    const bounds = bar => [Math.min(bar.open, bar.close), Math.max(bar.open, bar.close)];
    const wicks = bar => {
      const [bottom, top] = bounds(bar);
      return [[bar.low, bottom], [top, bar.high]].filter(([lo, hi]) => hi > lo);
    };
    for (const a of up) {
      const b = downByTime.get(a.time);
      if (!b) continue;
      const [aLo, aHi] = bounds(a), [bLo, bHi] = bounds(b);
      const low = Math.max(aLo, bLo), high = Math.min(aHi, bHi);
      if (high >= low) body.push({ time:a.time, open:low, close:high, low, high });
      const shared = [];
      for (const [aLow, aHigh] of wicks(a)) for (const [bLow, bHigh] of wicks(b)) {
        const lo = Math.max(aLow, bLow), hi = Math.min(aHigh, bHigh);
        if (hi > lo) shared.push({ time:a.time, open:lo, close:lo, low:lo, high:hi });
      }
      if (shared[0]) wickA.push(shared[0]);
      if (shared[1]) wickB.push(shared[1]);
    }
    return { body, wickA, wickB };
  }

  class AxisLabel {
    constructor(owner, key, color) { this.owner = owner; this.key = key; this.color = color; }
    coordinate() { return this.owner.series?.priceToCoordinate(this.owner.data?.[this.key]) ?? -1; }
    text() { return this.owner.format(this.owner.data?.[this.key]); }
    textColor() { return "#0b1915"; }
    backColor() { return this.color; }
    tickVisible() { return false; }
    visible() {
      const owner = this.owner;
      if (!owner.originVisible() || (this.key !== "entry" && !owner.lineVisible)) return false;
      const y = this.coordinate();
      return Number.isFinite(y) && y >= 0 && y <= owner.paneHeight();
    }
  }

  class ProbabilityGuide {
    constructor(chart, series, format) {
      this.chart = chart;
      this.series = series;
      this.format = format;
      this.data = null;
      this.lineVisible = true;
      this.axes = [new AxisLabel(this, "up", COLORS.up), new AxisLabel(this, "down", COLORS.down), new AxisLabel(this, "entry", COLORS.entry)];
      this.view = { zOrder: () => "top", renderer: () => ({ draw: target => this.draw(target) }) };
    }
    attached({ requestUpdate }) { this.requestUpdate = requestUpdate; }
    detached() { this.requestUpdate = null; }
    paneViews() { return [this.view]; }
    priceAxisViews() { return this.axes; }
    paneHeight() { return this.chart.panes()[0].getHeight(); }
    originVisible() {
      if (!this.data) return false;
      const x = this.chart.timeScale().timeToCoordinate(this.data.time);
      const width = this.chart.timeScale().width();
      return x != null && x >= 0 && x <= width;
    }
    autoscaleInfo() {
      if (!this.data || !this.lineVisible || !this.originVisible()) return null;
      return { priceRange: { minValue: Math.min(this.data.entry, this.data.down), maxValue: Math.max(this.data.entry, this.data.up) } };
    }
    set(data, lineVisible) { this.data = data; this.lineVisible = lineVisible; this.requestUpdate?.(); }
    draw(target) {
      if (!this.originVisible()) return;
      const data = this.data;
      const x = this.chart.timeScale().timeToCoordinate(data.time);
      const y = this.series.priceToCoordinate(data.entry);
      if (![x, y].every(Number.isFinite)) return;
      target.useMediaCoordinateSpace(({ context: ctx, mediaSize: size }) => {
        ctx.save();
        ctx.beginPath(); ctx.rect(0, 0, size.width, size.height); ctx.clip();
        // Entry only extends right from the white origin; no vertical line.
        ctx.lineWidth = 1; ctx.strokeStyle = "rgba(227,232,229,.65)"; ctx.setLineDash([2, 3]);
        ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(size.width, y); ctx.stroke();
        if (this.lineVisible) {
          const available = size.width - x;
          const length = Math.min(230, Math.max(80, available * .68));
          const endX = Math.min(size.width - 28, x + length);
          const branches = [
            { key: "up", color: COLORS.up, probability: data.upProbability },
            { key: "down", color: COLORS.down, probability: data.downProbability },
          ];
          for (const branch of branches) {
            const endY = this.series.priceToCoordinate(data[branch.key]);
            if (!Number.isFinite(endY) || endX <= x + 5) continue;
            const dx = endX - x, dy = endY - y;
            ctx.strokeStyle = branch.color; ctx.lineWidth = 1.7; ctx.setLineDash([5, 5]);
            ctx.beginPath(); ctx.moveTo(x, y);
            // A restrained, nearly straight curve ending horizontally, as
            // in the supplied reference. This guide has no OHLC semantics.
            ctx.bezierCurveTo(x + dx * .34, y + dy * .38, x + dx * .74, endY, endX, endY);
            ctx.lineTo(size.width - 3, endY); ctx.stroke();
            if (endY >= 0 && endY <= size.height) {
              ctx.setLineDash([]); ctx.fillStyle = branch.color;
              ctx.beginPath(); ctx.arc(size.width - 3, endY, 3.3, 0, Math.PI * 2); ctx.fill();
            }
            const labelY = Math.max(13, Math.min(size.height - 9, endY + (branch.key === "up" ? -10 : 14)));
            ctx.setLineDash([]); ctx.font = "600 11px Consolas, monospace";
            ctx.textAlign = "right"; ctx.textBaseline = "middle";
            ctx.lineWidth = 4; ctx.strokeStyle = "#171714";
            const text = `${Math.round(branch.probability * 100)}%`;
            ctx.strokeText(text, endX + 18, labelY);
            ctx.fillStyle = branch.color; ctx.fillText(text, endX + 18, labelY);
          }
        }
        ctx.setLineDash([]); ctx.fillStyle = "#171714"; ctx.strokeStyle = COLORS.entry; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.arc(x, y, 4.2, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
        ctx.fillStyle = COLORS.entry; ctx.beginPath(); ctx.arc(x, y, 1.8, 0, Math.PI * 2); ctx.fill();
        ctx.restore();
      });
    }
  }

  class Controller {
    constructor(chart, realSeries, LC, format, marketView = {}) {
      this.chart = chart;
      this.realSeries = realSeries;
      this.marketView = marketView;
      this.focusKey = null;
      this.upSeries = chart.addSeries(LC.CandlestickSeries, candleOptions('up'));
      this.downSeries = chart.addSeries(LC.CandlestickSeries, candleOptions('down'));
      // Decoration-only masks use the same native candle geometry. Their
      // ranges are intersections of the two existing forecasts, not a third
      // scenario or new market data.
      const white = { ...candleOptions(), borderUpColor:'#f0f4f3', borderDownColor:'#f0f4f3', wickUpColor:'#f0f4f3', wickDownColor:'#f0f4f3' };
      this.overlapBody = chart.addSeries(LC.CandlestickSeries, { ...white, wickVisible:false });
      this.overlapWickA = chart.addSeries(LC.CandlestickSeries, { ...white, borderVisible:false });
      this.overlapWickB = chart.addSeries(LC.CandlestickSeries, { ...white, borderVisible:false });
      this.guide = new ProbabilityGuide(chart, realSeries, format);
      realSeries.attachPrimitive(this.guide);
      this.lineVisible = true;
      this.candleVisible = true;
      this.longVisible = true;
      this.shortVisible = true;
      this.summary = null;
      this.previewRange = null;
      this.minHorizon = Math.max(1, Number(marketView.minHorizon) || 10);
      this.forceEndpointToTarget = Boolean(marketView.forceEndpointToTarget);
    }
    clear() {
      this.upSeries.setData([]); this.downSeries.setData([]);
      this.overlapBody.setData([]); this.overlapWickA.setData([]); this.overlapWickB.setData([]);
      this.guide.set(null, this.lineVisible); this.summary = null;
      this.previewRange = null;
      this.focusMarket();
    }
    show(signal, step) {
      const prediction = signal?.prediction, entry = Number(signal?.entry);
      if (!prediction || !Number.isFinite(entry) || entry <= 0 || !Number.isFinite(signal.available_at)) { this.clear(); return; }
      const clamp = value => Math.max(this.minHorizon, Math.min(96, Number(value) || this.minHorizon));
      const upHorizon = clamp(prediction.up_horizon_bars || prediction.candle_horizon_bars);
      const downHorizon = clamp(prediction.down_horizon_bars || prediction.candle_horizon_bars);
      const horizon = Math.max(upHorizon, downHorizon);
      const aligned = prediction.path_start === "entry_bar";
      const upSource = prediction.up_representative;
      const downSource = prediction.down_representative;
      // Each branch retains the shape of one real sequence near its group
      // mean, with its amplitude calibrated to pre-Entry market volatility.
      const marketBars = this.marketView.getBars?.() || [];
      const upRows = upSource?.candles?.length >= upHorizon ? upSource.candles.slice(0, upHorizon) : [];
      const downRows = downSource?.candles?.length >= downHorizon ? downSource.candles.slice(0, downHorizon) : [];
      // Extending the tail must not rescale/rewrite the first ten candles.
      const upCalibration = volatilityCalibration(upRows.slice(0, 10), marketBars, entry, signal.available_at);
      const downCalibration = volatilityCalibration(downRows.slice(0, 10), marketBars, entry, signal.available_at);
      const upper = Math.max(Number(signal.tp), Number(signal.sl));
      const lower = Math.min(Number(signal.tp), Number(signal.sl));
      if (![upper, lower].every(Number.isFinite)) { this.clear(); return; }
      const up = projectOHLC(upRows, entry, signal.available_at, step, upHorizon, aligned, upCalibration.scale,
        this.forceEndpointToTarget ? upper : undefined);
      const down = projectOHLC(downRows, entry, signal.available_at, step, downHorizon, aligned, downCalibration.scale,
        this.forceEndpointToTarget ? lower : undefined);
      const realPriceFormat = { type: "custom", formatter: value => this.guide.format(value) };
      this.upSeries.applyOptions({ priceFormat: realPriceFormat });
      this.downSeries.applyOptions({ priceFormat: realPriceFormat });
      this.upSeries.setData(up); this.downSeries.setData(down);
      const shared = intersectionMasks(up, down);
      this.overlapBody.setData(shared.body);
      this.overlapWickA.setData(shared.wickA); this.overlapWickB.setData(shared.wickB);
      this.guide.set({ time: signal.available_at, entry, up: upper, down: lower,
        upProbability: Number(prediction.up_probability) || 0,
        downProbability: Number(prediction.down_probability) || 0 }, this.lineVisible);
      this.summary = { up, down, upSource, downSource, upCalibration, downCalibration,
        basis: 'closest_real_path_to_group_mean', samples: prediction.path_sample_count || 0, horizon, upHorizon, downHorizon, entry, time: signal.available_at };
      const times = [...up, ...down].map(bar => bar.time);
      this.previewRange = times.length ? {from:Math.min(...times),to:Math.max(...times)} : null;
      this.focusKey = null;
      this.visibility(this.lineVisible, this.candleVisible);
    }
    hasVisibleCandles() {
      return Boolean(this.candleVisible && ((this.longVisible && this.summary?.up.length) ||
        (this.shortVisible && this.summary?.down.length)));
    }
    inPreview(time) {
      return Boolean(this.hasVisibleCandles() && this.previewRange && time >= this.previewRange.from && time <= this.previewRange.to);
    }
    marketBar(bar) {
      const {time, open, high, low, close} = bar;
      const plain = {time, open, high, low, close};
      return this.inPreview(time) ? { ...plain, color:'rgba(146,161,166,.40)', wickColor:'rgba(146,161,166,.30)', borderColor:'rgba(146,161,166,.40)' } : plain;
    }
    emaPoint(point) {
      return this.inPreview(point.time) ? { ...point, color:'rgba(49,150,218,.26)' } : {time:point.time,value:point.value};
    }
    focusMarket() {
      const bars = this.marketView.getBars?.();
      if (!bars?.length) return;
      const key = this.hasVisibleCandles() && this.previewRange ? `${this.previewRange.from}:${this.previewRange.to}` : 'normal';
      if (key === this.focusKey) return;
      this.focusKey = key;
      this.realSeries.setData(bars.map(bar => this.marketBar(bar)));
      const ema = this.marketView.getEMA?.();
      if (ema?.length) this.marketView.emaSeries?.setData(ema.map(point => this.emaPoint(point)));
    }
    visibility(line, candle, long = this.longVisible, short = this.shortVisible) {
      this.lineVisible = line; this.candleVisible = candle;
      this.longVisible = long; this.shortVisible = short;
      const visibleTimes = [...(candle && long ? this.summary?.up || [] : []), ...(candle && short ? this.summary?.down || [] : [])].map(bar => bar.time);
      this.previewRange = visibleTimes.length ? {from:Math.min(...visibleTimes),to:Math.max(...visibleTimes)} : null;
      this.upSeries.applyOptions({ visible: candle && long });
      this.downSeries.applyOptions({ visible: candle && short });
      const overlap = candle && long && short;
      this.overlapBody.applyOptions({ visible:overlap });
      this.overlapWickA.applyOptions({ visible:overlap }); this.overlapWickB.applyOptions({ visible:overlap });
      this.guide.set(this.guide.data, line);
      this.focusMarket();
    }
    dispose() {
      this.clear();
      this.realSeries.detachPrimitive?.(this.guide);
      for (const series of [this.upSeries,this.downSeries,this.overlapBody,this.overlapWickA,this.overlapWickB]) this.chart.removeSeries(series);
    }
  }
  return { Controller, projectOHLC, projectMeanOHLC: projectOHLC, candleOptions, intersectionMasks, ProbabilityGuide, volatilityCalibration };
});
