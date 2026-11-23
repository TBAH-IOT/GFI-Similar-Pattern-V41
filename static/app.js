"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const initialQuery = new URLSearchParams(window.location.search);
  const apiBase = (window.GFI_API_BASE || initialQuery.get('apiBase') || window.location.pathname.replace(/\/[^/]*$/, '')).replace(/\/$/, '');
  window.GFI_API_BASE = apiBase;
  if (initialQuery.get('embed') === '1') document.documentElement.dataset.embed = 'true';
  const state = { symbol:"BTCUSDT", tf: "1h", data: null, selected: null, followedPatternId: null, selectionPinned: false, visibleRange: null, patternView: {}, notifications: {}, filter: "all", historyMode: "engine", limit: 4, patterns: true, ema: true, request: 0 };
  const patternPresentation = window.GFIPatternPresentation;
  const notificationSession = patternPresentation.createNotificationSession();
  const forecastVersion = initialQuery.get("v") || "41";
  const spotlightForecastMode = forecastVersion === "41";
  const meanForecastMode = forecastVersion === "40" && initialQuery.get('style') === 'mean';
  const guidedForecastMode = forecastVersion === "40" && initialQuery.get('style') === 'guided';
  const arrowForecastMode = forecastVersion === "40" && initialQuery.get('style') === 'arrows';
  const nativeV40Mode = forecastVersion === "40" && !meanForecastMode && !arrowForecastMode && !guidedForecastMode;
  // V40 is a focused V39 variant: keep the native hollow-candle/guide
  // renderer, with the same 10-bar floor. The older arrow experiment remains
  // available only through explicit style=arrows/guided URLs.
  const zigzagForecastMode = arrowForecastMode || guidedForecastMode || spotlightForecastMode;
  const occurrenceHorizonMode = forecastVersion === "39" || forecastVersion === "40" || spotlightForecastMode;
  const adaptiveHorizonMode = forecastVersion === "38" || occurrenceHorizonMode;
  const forecastCandleMode = forecastVersion === "34" || adaptiveHorizonMode;
  const forecastHybridMode = forecastVersion === "35";
  const forecastNativeCandleMode = forecastCandleMode || forecastHybridMode;
  const forecastApiView = meanForecastMode ? 'v40-mean' : spotlightForecastMode || guidedForecastMode ? 'v40' : arrowForecastMode ? 'v40-arrows' : nativeV40Mode ? 'v40' : occurrenceHorizonMode ? 'v39' : adaptiveHorizonMode ? 'v38' : forecastNativeCandleMode ? 'v34' : 'v33';
  document.documentElement.dataset.forecastView = forecastVersion;
  const period = { "15m": 900, "1h": 3600, "4h": 14400, "1d":86400 };
  const patternTimeframes = new Set(["15m","1h","4h"]);
  let fmt = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const marketKey = () => `${state.symbol}:${state.tf}`;
  const ticker = () => state.symbol.replace("USDT","");
  const money = (n, coin=ticker()) => n == null ? "—" : "$" + new Intl.NumberFormat("en-US",{minimumFractionDigits:coin==="NEAR"?3:2,maximumFractionDigits:coin==="NEAR"?3:2}).format(n);
  const pct = (n) => n == null ? "—" : (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
  const dateTime = (n, short = false) => new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", day: "2-digit", month: "2-digit", ...(short ? {} : { year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }) }).format(new Date(n * 1000));
  const historyDate = n => new Intl.DateTimeFormat('en-GB',{timeZone:'UTC',day:'2-digit',month:'2-digit',year:'numeric'}).format(new Date(n*1000));
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const statusName = { PENDING:"Chờ giá mở nến", OPEN: "Đang mở", TP: "Đã chạm TP", SL: "Đã chạm SL", EXPIRED: "Hết hạn 48 nến", AMBIGUOUS: "Cùng nến TP / SL · tính không thắng", REFERENCE:"Chỉ tham khảo" };
  const patternNames = {
    Triangle_Ascending: "Ascending Triangle", Triangle_Descending: "Descending Triangle",
    Triangle_Symmetrical: "Symmetrical Triangle", Diamond_Top: "Diamond Top",
    Diamond_Bottom: "Diamond Bottom", Broadening_Bottom: "Broadening Bottom",
    Broadening_Top: "Broadening Top", Triple_Top_Wide: "Triple Top (Wide)",
    Triple_Bottom_Wide: "Triple Bottom (Wide)", Wedge_Falling: "Falling Wedge",
    Wedge_Rising: "Rising Wedge", Cup_and_Handle: "Cup and Handle",
    Double_Bottom: "Double Bottom", Double_Top: "Double Top", Triple_Top: "Triple Top",
    Triple_Bottom: "Triple Bottom", Head_and_Shoulders_Top: "Head and Shoulders",
    Head_and_Shoulders_Bottom: "Inverse Head and Shoulders",
    Pennant_Bearish: "Bearish Pennant", Pennant_Bullish: "Bullish Pennant",
    Flag_Bullish: "Bullish Flag", Flag_Bearish: "Bearish Flag",
    Rectangle_Range: "Rectangle", Rounding_Bottom: "Rounding Bottom", Rounding_Top: "Rounding Top",
  };
  const patternName = (signal) => (signal?.display_name || patternNames[signal?.name] || String(signal?.name || "Pattern").replaceAll("_", " ")).replace(/\s*[·•]\s*Inverse$/i, "");
  const coins = {
    BTC: { name: "Bitcoin", glyph: "₿", className: "coin-btc" },
    NEAR: { name: "NEAR Protocol", glyph: "N", className: "coin-near" },
    ETH: { name: "Ethereum", glyph: "◆", className: "coin-eth" },
    SOL: { name: "Solana", glyph: "◎", className: "coin-sol" },
    BNB: { name: "BNB", glyph: "◇", className: "coin-bnb" },
  };
  let supportedTickers = ['BTC','NEAR','SOL'];
  const coinMark = (ticker) => {
    const coin = coins[ticker] || { name: ticker, glyph: ticker[0], className: "" };
    return `<span class="coin-mark ${coin.className}" aria-hidden="true">${ticker === "SOL" ? "<i></i><i></i><i></i>" : coin.glyph}</span>`;
  };
  // Curated, explicitly labelled UI fixtures. These are not scanner outputs or
  // actual whale/macro trades. The real BTC engine remains available via the
  // small source switch next to the history title.
  const demoSignals = [
    { id: "demo-btc-whales", ticker: "BTC", type: "Whales copy", typeClass: "whales", horizon: "Trung hạn", direction: "LONG", entry: 77150, close: null, pnl: null, status: "OPEN", detected_at: Date.parse("2026-10-27T08:00:00Z") / 1000, is_demo: true },
    { id: "demo-eth-whales", ticker: "ETH", type: "Whales copy", typeClass: "whales", horizon: "Trung hạn", direction: "LONG", entry: 2810, close: 3029.18, pnl: 7.8, status: "TP", detected_at: Date.parse("2026-10-20T07:00:00Z") / 1000, is_demo: true },
    { id: "demo-sol-quant", ticker: "SOL", type: "Quant", typeClass: "quant", horizon: "Ngắn hạn", direction: "LONG", entry: 173.21, close: 175.46, pnl: 1.3, status: "TP", detected_at: Date.parse("2026-10-14T03:30:00Z") / 1000, is_demo: true },
    { id: "demo-bnb-macro", ticker: "BNB", type: "Macro", typeClass: "macro", horizon: "Dài hạn", direction: "LONG", entry: 624, close: 575.33, pnl: -7.8, status: "SL", detected_at: Date.parse("2026-09-28T00:00:00Z") / 1000, is_demo: true },
  ];
  const historySignals = () => state.historyMode === "demo" ? demoSignals : (state.data?.signals || []);
  const isLiveSignal = s => s.status==="OPEN" && (s.is_demo || s.actionable);
  // Never replace a missing historical win rate with the shape-match score.
  // The label explicitly attributes this upstream metric; it is not a new
  // calibrated probability of this individual prediction being correct.
  const historicalAccuracy = (signal) => {
    if (signal?.accuracy_source!=="frozen_btc" && !(["out_of_sample","expanding_oos"].includes(signal?.accuracy_source) && signal.validation_samples>=(signal.minimum_samples??100))) return null;
    const value = signal?.configured_win_rate;
    return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1 ? (value * 100).toFixed(1) + "%" : null;
  };
  let chart, candles, emaSeries, patternSeries, forecastUpSeries, forecastDownSeries, forecastUpCandleSeries, forecastDownCandleSeries, nativeForecast, feed;
  let emaValues = [], lastCandleEvent = 0, lastTickerEvent = 0, resyncInFlight = false, patternRefreshTimer;
  let toastTimer, patternPollTimer, patternPollRequest = null;
  let patternRenderFrame = 0, patternRenderKey = "", forecastLayout = null;
  let forecastLineVisible = !arrowForecastMode, forecastCandleVisible = !guidedForecastMode && !spotlightForecastMode;
  let forecastLongVisible = true, forecastShortVisible = true;
  let spotlightSavedView = null;

  function updateSpotlightFocusButton() {
    const button = $("spotlight-focus");
    button.hidden = !spotlightForecastMode || !state.patterns || !state.selected || !state.data;
    button.setAttribute("aria-pressed", Boolean(spotlightSavedView));
    button.textContent = spotlightSavedView ? "↩ Tỉ lệ cũ" : "⊕ Phóng to";
  }

  function exitSpotlightFocus(restore = true) {
    const saved = spotlightSavedView;
    spotlightSavedView = null;
    if (saved && restore && chart && candles) {
      if (saved.logical) chart.timeScale().setVisibleLogicalRange(saved.logical);
      if (saved.prices) candles.priceScale().setVisibleRange(saved.prices);
      if (saved.autoScale) candles.priceScale().setAutoScale(true);
    }
    updateSpotlightFocusButton();
  }

  function toggleSpotlightFocus() {
    if (!spotlightForecastMode || !state.selected || !state.data) return;
    if (spotlightSavedView) { exitSpotlightFocus(); return; }
    const signal = state.selected;
    const entry = Number(signal.entry), tp = Number(signal.tp), sl = Number(signal.sl);
    const index = state.data.candles.findIndex(bar => bar.time >= signal.available_at);
    if (index < 0 || ![entry,tp,sl].every(Number.isFinite) || Math.min(entry,tp,sl) <= 0) return;
    const timeScale = chart.timeScale(), priceScale = candles.priceScale();
    spotlightSavedView = {
      logical: timeScale.getVisibleLogicalRange(),
      prices: priceScale.getVisibleRange(),
      autoScale: priceScale.options().autoScale,
    };
    // The original R:R 1:1 levels are untouched. This only changes the
    // viewport so a small target distance remains legible on a volatile chart.
    const distance = Math.max(Math.abs(tp - entry), Math.abs(sl - entry));
    const half = Math.max(distance * 2.1, entry * 0.003);
    const bars = Math.max(34, Math.min(54, Math.round(timeScale.width() / 15)));
    const from = Math.max(0, index - Math.round(bars * 0.3));
    timeScale.setVisibleLogicalRange({from, to:from + bars});
    priceScale.setAutoScale(false);
    priceScale.setVisibleRange({from:entry - half, to:entry + half});
    updateSpotlightFocusButton();
  }

  function schedulePatternRender() {
    cancelAnimationFrame(patternRenderFrame);
    patternRenderFrame = requestAnimationFrame(() => { if (state.data) renderPattern(); });
  }

  function toast(message) {
    $("toast").textContent = message;
    $("toast").hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { $("toast").hidden = true; }, 3800);
  }

  function setLoading(on, text) {
    if (on && $("forecast-horizon-note")) $("forecast-horizon-note").hidden = true;
    $("chart-state").hidden = !on;
    $("chart-state").classList.toggle("error", Boolean(text));
    if (text) $("chart-state").innerHTML = `<span>${esc(text)}</span><button class="retry-market" id="retry-market">Thử kết nối lại</button>`;
    else $("chart-state").innerHTML = '<span class="spinner"></span> Đang quét cấu trúc giá…';
  }

  function initChart() {
    const LC = window.LightweightCharts;
    if (!LC) throw new Error("Không tải được thư viện biểu đồ. Hãy chạy bằng start-demo.cmd.");
    chart = LC.createChart($("price-chart"), {
      autoSize: true,
      layout: { background: { type: "solid", color: "#171714" }, textColor: "#92978c", fontSize: 10, fontFamily: '"Segoe UI", sans-serif', attributionLogo: true },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      crosshair: { mode: LC.CrosshairMode.Normal, vertLine: { color: "#777b6b", width: 1, style: LC.LineStyle.Dashed }, horzLine: { color: "#777b6b", width: 1, style: LC.LineStyle.Dashed } },
      rightPriceScale: { borderColor: "#292c23", minimumWidth: 67, scaleMargins: { top: 0.14, bottom: 0.17 } },
      timeScale: { borderColor: "#292c23", timeVisible: true, secondsVisible: false, rightOffset: 10, barSpacing: 5.5, minBarSpacing: 0.01, fixLeftEdge: true },
      localization: { locale: "en-GB", priceFormatter: (n) => fmt.format(n) },
      handleScroll: { vertTouchDrag: false },
    });
    candles = chart.addSeries(LC.CandlestickSeries, { upColor: "#23b697", downColor: "#df556c", borderVisible: false, wickUpColor: "#23b697", wickDownColor: "#df556c", priceLineVisible: false, lastValueVisible: false });
    emaSeries = chart.addSeries(LC.LineSeries, { color: "#3196da", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    patternSeries = chart.addSeries(LC.LineSeries, { color: "#e6c364", lineWidth: 2, pointMarkersVisible: true, pointMarkersRadius: 3, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, zOrder: "top" });
    // Keep invisible data series so Lightweight Charts includes TP/SL in the
    // auto-scale. The visible forecast is drawn by the fixed-pixel overlay.
    forecastUpSeries = chart.addSeries(LC.LineSeries, { color: "rgba(0,0,0,0)", lineWidth: 1, lineStyle: LC.LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, zOrder: "bottom" });
    forecastDownSeries = chart.addSeries(LC.LineSeries, { color: "rgba(0,0,0,0)", lineWidth: 1, lineStyle: LC.LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, zOrder: "bottom" });
    const ForecastController = zigzagForecastMode ? window.GFIArrowForecast.Controller : window.GFINativeForecast.Controller;
    if (forecastCandleMode) nativeForecast = new ForecastController(chart, candles, LC, value => fmt.format(value), {
      getBars: () => state.data?.candles || [], getEMA: () => emaValues, emaSeries,
      minHorizon: nativeV40Mode ? 10 : 10,
      guidedMode: guidedForecastMode || spotlightForecastMode,
      spotlightMode: spotlightForecastMode,
      // V40 is V39 with only a longer floor. Keep V39's original
      // volatility-calibrated path; do not force the terminal candle to TP/SL.
      forceEndpointToTarget: false,
    });
    chart.subscribeCrosshairMove((param) => {
      const bar = param.seriesData.get(candles);
      if (bar && bar.open != null) {
        $("ohlc").textContent = `O ${fmt.format(bar.open)}   H ${fmt.format(bar.high)}   L ${fmt.format(bar.low)}   C ${fmt.format(bar.close)}`;
      } else $("ohlc").textContent = "Kéo để di chuyển · Cuộn để thu phóng";
    });
    chart.subscribeClick((param) => {
      if (param.hoveredObjectId) {
        const signal = state.data?.signals.find((s) => s.id === param.hoveredObjectId);
        if (signal) selectSignal(signal, {focus:false});
      }
    });
    chart.timeScale().subscribeVisibleTimeRangeChange((range) => {
      $("visible-range-label").textContent = range && typeof range.from === "number" ? `Đang xem ${dateTime(range.from, true)}–${dateTime(range.to, true)}` : "";
      state.visibleRange = range;
      repositionForecastLabels();
      schedulePatternRender();
    });
    let previousWidth = $("price-chart").clientWidth;
    new ResizeObserver((entries) => {
      const width = entries[0].contentRect.width;
      if (Math.abs(width - previousWidth) > 15) {
        previousWidth = width;
        schedulePatternRender();
      }
    }).observe($("price-chart"));
  }

  async function fetchJSON(path) {
    const response = await fetch(path.startsWith('/api/') ? apiBase + path : path);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Không đọc được dữ liệu local.");
    return data;
  }

  async function loadMarket({ preserve = false, keepViewport = false } = {}) {
    exitSpotlightFocus(false);
    const request = ++state.request;
    const savedRange = keepViewport ? chart.timeScale().getVisibleRange() : null;
    feed?.stop();
    clearInterval(patternPollTimer);
    clearTimeout(patternRefreshTimer);
    setProviderStatus("connecting");
    setLoading(true);
    try {
      const query = new URLSearchParams({ symbol:state.symbol, tf: state.tf, view: forecastApiView });
      const data = await fetchJSON("/api/market?" + query);
      if (request !== state.request) return;
      if (!["live","snapshot"].includes(data.mode) || data.source !== "Binance Spot") throw new Error("Nguồn giá chưa sẵn sàng. Vui lòng khởi động lại demo.");
      if (data.symbol!==state.symbol || data.timeframe!==state.tf) throw new Error("Nguồn trả về sai coin hoặc khung nến.");
      data.signals=patternPresentation.timeline(data.signals).items.reverse();
      if (preserve && state.data?.symbol===data.symbol && state.data?.timeframe === data.timeframe && ["backfilling","catching_up"].includes(data.pipeline?.status) && !data.signals.length) data.signals = state.data.signals;
      state.data = data;
      const precision=data.asset.price_precision;
      fmt=new Intl.NumberFormat("en-US",{minimumFractionDigits:precision,maximumFractionDigits:precision});
      candles.applyOptions({priceFormat:{type:"price",precision,minMove:data.asset.min_move}, lastValueVisible:false, priceLineVisible:false});
      chart.applyOptions({localization:{priceFormatter:n=>fmt.format(n)}});
      state.selected = (preserve ? data.signals.find((s) => s.id === state.selected?.id) : null) || data.signals[0] || null;
      state.followedPatternId = state.selected?.id || null;
      if (!preserve) state.selectionPinned = false;
      patternRenderKey = "";
      observePatternNotifications(data.signals, data.server_time);
      lastCandleEvent = data.server_time;
      lastTickerEvent = data.updated_at;
      renderMarket(savedRange);
      if (request === state.request) {
        setLoading(false);
        if (data.mode === 'snapshot') setProviderStatus('snapshot');
        else {
          feed.start(state.symbol, state.tf, data.server_time);
          patternPollTimer = setInterval(refreshPatterns, 5000);
        }
      }
    } catch (error) {
      if (request === state.request) { setProviderStatus("stale"); setLoading(true, error.message); }
    }
  }

  function renderMarket(savedRange = null) {
    const data = state.data;
    candles.setData(data.candles.map(({time, open, high, low, close}) => ({time, open, high, low, close})));
    let average;
    emaValues = data.candles.map((bar) => {
      average = average == null ? bar.close : average + (2 / 21) * (bar.close - average);
      return { time: bar.time, value: average };
    });
    emaSeries.setData(emaValues);
    emaSeries.applyOptions({ visible: state.ema });
    renderPrices();
    $("chart-title").textContent = `${ticker()} / USDT · ${state.tf} · Binance`;
    $("history-loaded-label").textContent = `Đã tải ${historyDate(data.history_start)}–${historyDate(data.server_time / 1000)} · Kéo trái để xem`;
    const wholeHistory=document.querySelector('[data-range="3m"]');
    wholeHistory.textContent='3M';
    wholeHistory.title='Xem toàn bộ ba tháng đã tải';
    $("market-range-label").textContent = ` · ${ticker()}/USDT · ${dateTime(data.history_start)} — ${dateTime(data.server_time / 1000)} UTC`;
    $("dataset-note").title = `Binance Spot · ${ticker()}/USDT · Giá USDT · Từ ${dateTime(data.history_start)} UTC`;
    document.querySelectorAll("[data-frame]").forEach((button) => {
      button.hidden=false;
      const selected = button.dataset.frame === state.tf;
      button.classList.toggle("selected", selected);
      button.setAttribute("aria-pressed", selected);
    });
    $("pattern-toggle").hidden = !patternTimeframes.has(state.tf);
    renderHistory();
    renderPipeline();
    if (savedRange && typeof savedRange.from === "number") {
      const first = data.candles[0].time, last = data.candles.at(-1).time;
      chart.timeScale().setVisibleRange({ from: Math.max(first, Math.min(savedRange.from, last - period[state.tf])), to: Math.min(last, Math.max(savedRange.to, first + period[state.tf])) });
    } else resetRange();
    state.visibleRange = chart.timeScale().getVisibleRange();
    renderPattern();
    if (spotlightForecastMode && !savedRange && state.selected) {
      const index=data.candles.findIndex(bar=>bar.time>=state.selected.available_at);
      if (index>=0) {
        const bars=Math.max(36,Math.min(62,Math.round(chart.timeScale().width()/12)));
        const from=Math.max(0,index-Math.round(bars*.34));
        chart.timeScale().setVisibleLogicalRange({from,to:from+bars});
      }
    }
  }

  function renderPrices() {
    const data = state.data;
    if (!data) return;
    $("market-price").textContent = fmt.format(data.last);
    $("reference-price").textContent = fmt.format(data.last);
    $("reference-asof").textContent = `${ticker()}/USDT · ${data.mode === 'snapshot' ? 'Snapshot · '+dateTime(data.updated_at/1000) : 'Binance Spot · '+new Date(data.updated_at).toISOString().slice(11,19)} UTC`;
    $("market-overview-heading").textContent = `${data.asset.name} ${data.change_24h >= 0 ? "tăng" : "giảm"} ${Math.abs(data.change_24h).toFixed(2)}% trong 24 giờ.`;
    $("market-overview-price").textContent = `${fmt.format(data.last)} USDT`;
    $("market-overview-range").textContent = `Thấp 24h ${fmt.format(data.low_24h)} · Cao 24h ${fmt.format(data.high_24h)}`;
    $("market-range-label").textContent = ` · ${ticker()}/USDT · ${dateTime(data.history_start)} — ${dateTime(data.updated_at / 1000)} UTC`;
    $("history-loaded-label").textContent = `Đã tải ${historyDate(data.history_start)}–${historyDate(data.updated_at / 1000)} · Kéo trái để xem`;
    [$("market-change")].forEach((el) => {
      el.textContent = pct(data.change_24h);
      el.classList.toggle("positive", data.change_24h >= 0);
      el.classList.toggle("negative", data.change_24h < 0);
    });
    $("market-volume").textContent = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(data.volume_24h) + " " + ticker();
    $("last-update").textContent = `Cập nhật ${new Date(data.updated_at).toISOString().slice(11,19)} UTC`;
  }

  function setProviderStatus(status) {
    const labels = { connecting: "ĐANG KẾT NỐI", live: "TRỰC TIẾP", snapshot:"SNAPSHOT · DEMO", reconnecting: "ĐANG NỐI LẠI", polling: "REST · 5 GIÂY", stale: "GIÁN ĐOẠN" };
    $("connection-label").textContent = labels[status] || status;
    $("dataset-note").dataset.status = status;
    $("connection-light").className = "dot " + (status === "live" ? "green" : status === "stale" ? "red" : "amber");
    $("replay-label").innerHTML = `<span class="dot ${status === "live" ? "green" : status === "stale" ? "red" : "amber"}"></span> BINANCE SPOT · ${labels[status] || status}`;
  }

  function resetRange() {
    exitSpotlightFocus(false);
    if (!state.data) return;
    const length = state.data.candles.length;
    state.selectionPinned = false;
    state.selected = patternPresentation.timeline(state.data.signals).latest;
    const firstTime = state.selected?.points[0].time;
    const firstIndex = firstTime ? state.data.candles.findIndex(bar => bar.time >= firstTime) : -1;
    const visibleBars = forecastCandleMode ? 72 : 180;
    const from = firstIndex >= 0 ? Math.max(0, Math.min(firstIndex - 12, length - visibleBars)) : Math.max(0, length - visibleBars);
    candles.priceScale().setAutoScale(true);
    chart.timeScale().setVisibleLogicalRange({ from, to: length + (forecastCandleMode ? 24 : 8) });
  }

  function clearForecastVisuals() {
    nativeForecast?.clear();
    forecastUpSeries.setData([]);
    forecastDownSeries.setData([]);
    forecastUpCandleSeries?.setData([]);
    forecastDownCandleSeries?.setData([]);
    forecastLayout = null;
    $("forecast-overlay").hidden = true;
    $("forecast-overlay").style.clipPath = "";
    $("forecast-overlay").replaceChildren();
    $("forecast-up-price-tag").hidden = true;
    $("forecast-down-price-tag").hidden = true;
    $("forecast-up-axis-dot").hidden = true;
    $("forecast-down-axis-dot").hidden = true;
    $("forecast-entry-line").hidden = true;
    $("forecast-up-label").hidden = true;
    $("forecast-down-label").hidden = true;
    $("forecast-origin-line").hidden = true;
    $("forecast-origin-dot").hidden = true;
  }

  function updateForecastLayerVisibility() {
    // V41 presents only the directional arrows. Keep the historical source
    // candles for path calculation, but never render their translucent layer.
    if (spotlightForecastMode) forecastCandleVisible = false;
    document.documentElement.dataset.forecastLine = forecastLineVisible ? "on" : "off";
    document.documentElement.dataset.forecastCandles = forecastCandleVisible ? "on" : "off";
    const overlay = $("forecast-overlay");
    const layerToggles = $("forecast-layer-toggles");
    // V34 and V35 both render the two optional forecast layers. Keep the
    // compact controls visible for either version, but remove them together
    // with Similar Pattern so the toolbar never shows inactive controls.
    if (layerToggles) layerToggles.hidden = !forecastNativeCandleMode || !state.patterns || !patternTimeframes.has(state.tf);
    if (overlay) {
      overlay.dataset.forecastLine = forecastLineVisible ? "on" : "off";
      overlay.dataset.forecastCandles = forecastCandleVisible ? "on" : "off";
    }
    $("forecast-line-toggle")?.setAttribute("aria-pressed", String(forecastLineVisible));
    $("forecast-candle-toggle")?.setAttribute("aria-pressed", String(forecastCandleVisible));
    $("forecast-candle-toggle").hidden = spotlightForecastMode;
    $("forecast-scenario-toggles").hidden = !forecastCandleMode || spotlightForecastMode;
    $("forecast-long-toggle").setAttribute("aria-pressed", String(forecastLongVisible));
    $("forecast-short-toggle").setAttribute("aria-pressed", String(forecastShortVisible));
    $("forecast-long-toggle").disabled = !forecastCandleVisible;
    $("forecast-short-toggle").disabled = !forecastCandleVisible;
    forecastUpSeries?.applyOptions({ visible: forecastLineVisible });
    forecastDownSeries?.applyOptions({ visible: forecastLineVisible });
    forecastUpCandleSeries?.applyOptions({ visible: forecastCandleVisible });
    forecastDownCandleSeries?.applyOptions({ visible: forecastCandleVisible });
    nativeForecast?.visibility(forecastLineVisible, forecastCandleVisible, forecastLongVisible, forecastShortVisible);
    const horizonNote = $("forecast-horizon-note");
    if (horizonNote) horizonNote.hidden = !adaptiveHorizonMode || !state.patterns || !forecastCandleVisible || !nativeForecast?.summary || state.data?.symbol !== state.symbol || state.data?.timeframe !== state.tf;
  }

  function historicalProjection(raw, entry, target, startTime, step, horizon) {
    const rows = Array.isArray(raw) ? raw.filter((row) => [row.open, row.high, row.low, row.close].every((value) => Number.isFinite(Number(value)))) : [];
    if (!rows.length) return { candles: [], path: [] };
    const sample = rows.slice(0, horizon);
    if (!sample.length) return { candles: [], path: [] };
    // The API rows are already normalized historical averages: 1.0 means
    // the analogue's Entry. Do not use the first future candle's open as the
    // baseline; that magnifies small first-bar gaps and makes the preview
    // appear to jump far away from Entry.
    const base = 1;
    const end = Number(sample[sample.length - 1].close);
    const rawMove = end - base;
    if (!Number.isFinite(base) || !Number.isFinite(end) || Math.abs(rawMove) < 1e-9) return { candles: [], path: [] };
    const scale = (target - entry) / rawMove;
    const mapPrice = (value) => entry + (Number(value) - base) * scale;
    let previousClose = entry;
    const candles = sample.map((row, index) => {
      // The first displayed candle must start at the live Entry. Subsequent
      // candles open at the previous historical-mean close so the forecast
      // reads as one connected path instead of a row of detached candles.
      const open = index === 0 ? entry : previousClose;
      const close = mapPrice(row.close);
      const mappedHigh = mapPrice(row.high);
      const mappedLow = mapPrice(row.low);
      const candle = {
        time: startTime + (index + 1) * step,
        open,
        high: Math.max(open, close, mappedHigh, mappedLow),
        low: Math.min(open, close, mappedHigh, mappedLow),
        close,
      };
      previousClose = close;
      return candle;
    });
    // The first path point is exactly Entry; the last close lands exactly on
    // TP/SL through the same affine normalization. All intermediate wiggles,
    // pullbacks and wicks remain those of the averaged OHLC path.
    return {
      candles,
      path: [{ time: startTime, value: entry }, ...candles.map((row) => ({ time: row.time, value: row.close }))],
    };
  }

  function repositionForecastLabels() {
    if (!forecastLayout) return;
    requestAnimationFrame(() => {
      positionForecastLabels(...forecastLayout);
      drawForecastOverlay(...forecastLayout);
    });
  }

  function forecastEndX(startX, chartWidth) {
    const preferredWidth = 138;
    const availableWidth = Math.max(62, chartWidth - startX - 18);
    return startX + Math.min(preferredWidth, availableWidth);
  }

  function positionForecastLabels(startTime, lastTime, entry, upTarget, downTarget) {
    const stage = $("chart-stage");
    const chartEl = $("price-chart");
    if (!stage || !chartEl) return;
    const actualX = chart.timeScale().timeToCoordinate(lastTime);
    const startX = chart.timeScale().timeToCoordinate(startTime);
    const originY = candles.priceToCoordinate(entry);
    const upY = candles.priceToCoordinate(upTarget);
    const downY = candles.priceToCoordinate(downTarget);
    const stageRect = stage.getBoundingClientRect();
    const chartRect = chartEl.getBoundingClientRect();
    const chartWidth = chartEl.clientWidth;
    const chartLeft = chartRect.left - stageRect.left;
    const chartTop = chartRect.top - stageRect.top;
    const originDot = $("forecast-origin-dot");
    const originVisible = startX != null && startX >= -2 && startX <= chartWidth + 2 && originY != null;
    if (!originVisible) {
      originDot.hidden = true;
    } else {
      const originLeft = chartLeft + startX;
      originDot.style.left = `${originLeft - 4}px`;
      originDot.style.top = `${chartTop + originY - 4}px`;
      originDot.hidden = false;
    }
    // Labels follow the same fixed visual endpoint as the overlay, so they
    // remain legible when the user zooms far out.
    const x = startX != null ? forecastEndX(startX, chartWidth) : actualX;
    const inView = x != null && x >= -18 && x <= chartWidth + 18;
    if (!inView || upY == null || downY == null) {
      $("forecast-up-label").hidden = true;
      $("forecast-down-label").hidden = true;
      $("forecast-up-price-tag").hidden = true;
      $("forecast-down-price-tag").hidden = true;
      $("forecast-up-axis-dot").hidden = true;
      $("forecast-down-axis-dot").hidden = true;
      $("forecast-entry-line").hidden = true;
      return;
    }
    const upLabel = $("forecast-up-label");
    const downLabel = $("forecast-down-label");
    if (!upLabel || !downLabel) return;
    // Unhide before measuring. Hidden labels report zero dimensions and are
    // the main reason they used to collide after a zoom or range change.
    upLabel.hidden = false;
    downLabel.hidden = false;
    const labelItems = [
      { id:"forecast-up-label", label:upLabel, center:chartTop + upY },
      { id:"forecast-down-label", label:downLabel, center:chartTop + downY },
    ].sort((a, b) => a.center - b.center);
    const gap = Math.max(22, (upLabel.offsetHeight + downLabel.offsetHeight) / 2 + 10);
    if (labelItems[1].center - labelItems[0].center < gap) {
      const middle = (labelItems[0].center + labelItems[1].center) / 2;
      labelItems[0].center = middle - gap / 2;
      labelItems[1].center = middle + gap / 2;
    }
    const topLimit = chartTop + 7;
    const bottomLimit = stageRect.height - 8;
    const topOverflow = topLimit - (labelItems[0].center - labelItems[0].label.offsetHeight / 2);
    const bottomOverflow = (labelItems[1].center + labelItems[1].label.offsetHeight / 2) - bottomLimit;
    const shift = topOverflow > 0 ? topOverflow : bottomOverflow > 0 ? -bottomOverflow : 0;
    const place = (item) => {
      const { id, label } = item;
      const rightSpace = chartWidth - x;
      const leftCandidate = rightSpace > label.offsetWidth + 30 ? chartLeft + x + 9 : chartLeft + x - label.offsetWidth - 9;
      const minLeft = chartLeft + 8;
      const maxLeft = chartLeft + chartWidth - label.offsetWidth - 8;
      const left = Math.max(minLeft, Math.min(leftCandidate, maxLeft));
      const topCandidate = item.center + shift - label.offsetHeight / 2;
      const top = Math.max(chartTop + 7, Math.min(topCandidate, stageRect.height - label.offsetHeight - 8));
      label.style.left = `${left}px`;
      label.style.top = `${top}px`;
      label.hidden = false;
    };
    labelItems.forEach(place);
    const upPriceTag = $("forecast-up-price-tag");
    const downPriceTag = $("forecast-down-price-tag");
    const priceTags = [
      { tag:upPriceTag, dot:$("forecast-up-axis-dot"), center:chartTop + upY },
      { tag:downPriceTag, dot:$("forecast-down-axis-dot"), center:chartTop + downY },
    ].sort((a, b) => a.center - b.center);
    const priceGap = 20;
    if (priceTags[1].center - priceTags[0].center < priceGap) {
      const middle = (priceTags[0].center + priceTags[1].center) / 2;
      priceTags[0].center = middle - priceGap / 2;
      priceTags[1].center = middle + priceGap / 2;
    }
    priceTags.forEach(({tag, dot, center}) => {
      if (!tag) return;
      tag.style.left = `${chartLeft + chartWidth - 63}px`;
      tag.style.top = `${Math.max(chartTop + 10, Math.min(center, stageRect.height - 10))}px`;
      tag.hidden = false;
      if (!dot) return;
      dot.style.left = `${chartLeft + chartWidth - 68}px`;
      dot.style.top = `${Math.max(chartTop + 10, Math.min(center, stageRect.height - 10))}px`;
      dot.hidden = false;
    });
    const entryLine = $("forecast-entry-line");
    if (entryLine && startX != null && originY != null) {
      const originLeft = chartLeft + startX;
      const axisLeft = chartLeft + chartWidth - 68;
      entryLine.style.left = `${originLeft}px`;
      entryLine.style.top = `${chartTop + originY}px`;
      entryLine.style.width = `${Math.max(0, axisLeft - originLeft)}px`;
      entryLine.hidden = axisLeft <= originLeft;
    }
  }

  function drawForecastOverlay(startTime, lastTime, entry, upTarget, downTarget, upCandles = [], downCandles = [], upPath = [], downPath = []) {
    const stage = $("chart-stage");
    const chartEl = $("price-chart");
    const overlay = $("forecast-overlay");
    if (!stage || !chartEl || !overlay) return;
    const startX = chart.timeScale().timeToCoordinate(startTime);
    const originY = candles.priceToCoordinate(entry);
    const upY = candles.priceToCoordinate(upTarget);
    const downY = candles.priceToCoordinate(downTarget);
    if (startX == null || originY == null || upY == null || downY == null) {
      overlay.hidden = true;
      return;
    }
    const stageRect = stage.getBoundingClientRect();
    const chartRect = chartEl.getBoundingClientRect();
    const chartLeft = chartRect.left - stageRect.left;
    const chartTop = chartRect.top - stageRect.top;
    // Forecast geometry is calculated in stage coordinates so it can align
    // with the price axis and labels. Clip the visual layer back to the real
    // plot rectangle, otherwise a target above/below the current scale can
    // leak through the toolbar and pattern navigator.
    const clipRight = Math.max(0, stageRect.width - chartLeft - chartEl.clientWidth);
    const clipBottom = Math.max(0, stageRect.height - chartTop - chartEl.clientHeight);
    overlay.style.clipPath = `inset(${Math.max(0, chartTop)}px ${clipRight}px ${clipBottom}px ${Math.max(0, chartLeft)}px)`;
    const x0 = chartLeft + startX;
    const x1 = chartLeft + forecastEndX(startX, chartEl.clientWidth);
    const y0 = chartTop + originY;
    overlay.replaceChildren();
    if (forecastNativeCandleMode) {
      const addCandleSet = (rows, className, targetY) => {
        if (!Array.isArray(rows) || !rows.length) return;
        const mappedRows = rows.map((row) => ({
          open: candles.priceToCoordinate(row.open),
          high: candles.priceToCoordinate(row.high),
          low: candles.priceToCoordinate(row.low),
          close: candles.priceToCoordinate(row.close),
        }));
        const bodySamples = mappedRows.map((row) => Math.abs(row.open - row.close)).filter(Number.isFinite);
        const wickSamples = mappedRows.flatMap((row) => {
          const bodyTop = Math.min(row.open, row.close);
          const bodyBottom = Math.max(row.open, row.close);
          return [Math.max(0, bodyTop - row.high), Math.max(0, row.low - bodyBottom)];
        }).filter(Number.isFinite);
        const medianPixels = (values) => {
          if (!values.length) return 0;
          const sorted = [...values].sort((a, b) => a - b);
          return sorted[Math.floor(sorted.length / 2)];
        };
        const bodyMedian = medianPixels(bodySamples);
        const wickMedian = medianPixels(wickSamples);
        // Enlarge the averaged OHLC only for legibility. The relative body,
        // wick and pullback differences still come from the historical mean.
        const bodyScale = bodyMedian > 0 ? Math.min(12, Math.max(1, 10 / bodyMedian)) : 1;
        const wickCap = Math.max(10, Math.min(34, wickMedian * 1.8));
        rows.forEach((row, index) => {
          const progress = (index + 1) / rows.length;
          const x = x0 + (x1 - x0) * progress;
          const mapped = mappedRows[index];
          const valid = [mapped.open, mapped.high, mapped.low, mapped.close].every(Number.isFinite);
          const fallbackY = y0 + (chartTop + targetY - y0) * progress;
          const safeOpen = valid ? mapped.open : fallbackY - 2;
          const safeClose = valid ? mapped.close : fallbackY + 2;
          const safeHigh = valid ? mapped.high : Math.min(safeOpen, safeClose) - 7;
          const safeLow = valid ? mapped.low : Math.max(safeOpen, safeClose) + 7;
          const bodyTopCoord = Math.min(safeOpen, safeClose);
          const bodyBottomCoord = Math.max(safeOpen, safeClose);
          const upperWick = Math.min(Math.max(0, bodyTopCoord - safeHigh), wickCap);
          const lowerWick = Math.min(Math.max(0, safeLow - bodyBottomCoord), wickCap);
          const top = bodyTopCoord - upperWick;
          const height = Math.max(2, bodyBottomCoord + lowerWick - top);
          const bodyTop = bodyTopCoord - top;
          const bodyHeight = Math.max(3, Math.min(28, Math.abs(safeOpen - safeClose) * bodyScale));
          if (![x, top, height, bodyTop, bodyHeight].every(Number.isFinite)) return;
          const candle = document.createElement("span");
          candle.className = `forecast-candle ${className}`;
          candle.dataset.forecastCandle = className.endsWith("up") ? "up" : "down";
          candle.setAttribute("aria-label", `Nến dự báo ${className.endsWith("up") ? "tăng" : "giảm"} ${index + 1}`);
          // x is already measured in stage coordinates. Adding chartLeft a
          // second time pushed the forecast candles outside the visible
          // chart on layouts where the chart has a left offset.
          candle.style.left = `${x - 3.5}px`;
          candle.style.top = `${top}px`;
          candle.style.height = `${height}px`;
          const wick = document.createElement("span");
          wick.className = "forecast-candle-wick";
          const body = document.createElement("span");
          body.className = "forecast-candle-body";
          body.style.top = `${bodyTop}px`;
          body.style.height = `${bodyHeight}px`;
          candle.append(wick, body);
          overlay.appendChild(candle);
        });
      };
      // V34 keeps the native Lightweight Charts candles as-is. V35 adds a
      // crisp DOM copy so the hollow forecast candles remain legible above
      // the restrained dashed probability spine at every zoom level.
      if (forecastNativeCandleMode) {
        addCandleSet(upCandles, "forecast-candle-up", upY);
        addCandleSet(downCandles, "forecast-candle-down", downY);
      }
    }
    const addCurve = (targetY, className, path) => {
      if (!Array.isArray(path) || path.length < 2) return;
      const target = chartTop + targetY;
      const fragment = document.createDocumentFragment();
      let previous = { x: x0, y: y0 };
      const steps = path.length - 1;
      for (let i = 1; i <= steps; i += 1) {
        const progress = i / steps;
        const mappedY = candles.priceToCoordinate(Number(path[i]?.value));
        const current = {
          x: x0 + (x1 - x0) * progress,
          y: chartTop + (Number.isFinite(mappedY) ? mappedY : targetY),
        };
        const dx = current.x - previous.x;
        const dy = current.y - previous.y;
        const segment = document.createElement("span");
        segment.className = `forecast-segment ${className}`;
        segment.style.left = `${previous.x}px`;
        segment.style.top = `${previous.y - 1}px`;
        segment.style.width = `${Math.max(1, Math.hypot(dx, dy))}px`;
        segment.style.transform = `rotate(${Math.atan2(dy, dx)}rad)`;
        fragment.appendChild(segment);
        previous = current;
      }
      overlay.appendChild(fragment);
      const connector = document.createElement("span");
      connector.className = `forecast-segment ${className}`;
      connector.style.left = `${x1}px`;
      connector.style.top = `${target - 1}px`;
      connector.style.width = `${Math.max(0, chartLeft + chartEl.clientWidth - 68 - x1)}px`;
      connector.style.transform = "none";
      overlay.appendChild(connector);
    };
    addCurve(upY, "forecast-segment-up", upPath);
    addCurve(downY, "forecast-segment-down", downPath);
    overlay.hidden = false;
  }

  function renderForecast(signal) {
    const horizonNote = $("forecast-horizon-note");
    if (horizonNote) horizonNote.hidden = true;
    if (nativeForecast) {
      if (!patternTimeframes.has(state.tf) || !state.patterns || !signal) clearForecastVisuals();
      else {
        nativeForecast.show(signal, period[state.tf]);
        const preview = signal.prediction;
        const sourceLabel = (source) => source?.basis === 'arithmetic_mean_historical_ohlc'
          ? `Trung bình ${source.sample_count} mẫu lịch sử${source.peer_coin_samples ? ` · ${source.peer_coin_samples} mẫu coin tương đồng` : ''}`
          : source ? `${source.source_symbol?.replace('USDT','') || ticker()} ${dateTime(source.source_time)} UTC · ${source.sample_count} mẫu` : 'đang tổng hợp lịch sử';
        const calibration = nativeForecast.summary;
        const amplitudeNote = calibration?.upCalibration.basis === 'pre_entry_median_true_range' || calibration?.downCalibration.basis === 'pre_entry_median_true_range'
          ? `Biên độ cân theo ${Math.max(calibration.upCalibration.referenceBars, calibration.downCalibration.referenceBars)} nến trước Entry; giữ nguyên hình dạng mẫu lịch sử`
          : 'Chưa đủ nến trước Entry để cân biên độ';
        const count = nativeForecast.summary?.horizon || 10;
        $("forecast-candle-toggle").title = `${count} nến từ sau Entry · Xanh: tăng (${sourceLabel(preview?.up_representative)}) · Đỏ: giảm (${sourceLabel(preview?.down_representative)}) · ${amplitudeNote} · Viền trắng: hai nhánh trùng nhau · Nến thật màu xám trong vùng dự báo; tắt CANDLE để khôi phục màu`;
        if (adaptiveHorizonMode && horizonNote) {
          const lastRealTime = state.data?.candles?.at(-1)?.time || 0;
          const remaining = Math.max(0, Math.min(count, Math.ceil((signal.available_at + count*period[state.tf] - lastRealTime)/period[state.tf])));
          const hours = count*period[state.tf]/3600;
          horizonNote.textContent = `${count} NẾN · ${Number.isInteger(hours) ? hours : hours.toFixed(1)} GIỜ · ${remaining ? `CÒN ${remaining} NẾN PHÍA TRƯỚC` : 'ĐÃ DIỄN RA · ĐỐI CHIẾU LỊCH SỬ'}`;
          const policy = preview?.horizon_policy;
          horizonNote.title = `Tính từ Entry gốc, không dời theo hiện tại. Min 10 nến. V39 dùng delta = 1σ của 32 giá đóng cửa trước Entry; mỗi nhánh xanh/đỏ cắt độc lập. N tương lai được ước lượng trước Entry rồi khóa cho occurrence. Giữ nguyên 10 nến đầu và % TP/SL. ${count === 10 ? 'Chưa có bằng chứng đủ để kéo dài thêm trong delta.' : ''}`;
          if (occurrenceHorizonMode && policy) {
            const floor = policy.floor || 10;
            const up = preview.up_horizon_bars ?? floor, down = preview.down_horizon_bars ?? floor;
            const remain = n => Math.max(0, Math.min(n, Math.ceil((signal.available_at+n*period[state.tf]-lastRealTime)/period[state.tf])));
            horizonNote.textContent = policy.hindsight
              ? `XANH ${up} / ĐỎ ${down} NẾN`
              : `XANH ${up} / ĐỎ ${down} NẾN · ĐÃ KHÓA · CÒN ${remain(up)} / ${remain(down)} PHÍA TRƯỚC`;
            const info = side => { const b=policy.branches?.[side]; return b?.first_breach_bar ? `vượt δ ở nến ${b.first_breach_bar}${b.floor_overrides_breach ? `; vẫn giữ sàn ${floor} theo cấu hình` : ''}` : policy.hindsight ? `chưa vượt δ đến nến ${b?.bars ?? floor} trong cửa sổ nguồn` : `${b?.sample_count || 0} trường hợp tương tự trước Entry${b?.reason==='insufficient_similar_past_cases' ? `; chưa đủ mẫu nên giữ ${floor}` : ''}`; };
            $("forecast-candle-toggle").title = `Xanh ${up} / đỏ ${down} nến · ${policy.hindsight ? 'Hồi cứu theo giá thật, không phải N dự đoán từ đầu' : 'N riêng đã lưu cho Entry này'} · Hai nhánh dừng độc lập · ${amplitudeNote}`;
            horizonNote.title = `${policy.hindsight ? 'Hồi cứu: đã dùng giá thật sau Entry để tìm điểm cắt; KHÔNG phải N dự đoán từ đầu.' : 'N ước lượng riêng và lưu một lần cho Entry này; giá mới hoặc tải lại không đổi N.'} Delta = 1 × độ lệch chuẩn 32 Close trước Entry (${money(policy.delta_price)}). Xanh: ${info('up')}. Đỏ: ${info('down')}. Cắt riêng, dừng trước nến vượt δ; sàn ${floor}. TP/SL và % line giữ nguyên.`;
          }
          horizonNote.hidden = !forecastCandleVisible;
        }
        $("forecast-line-toggle").title = 'Bật/tắt nét đứt dự báo';
        if (nativeV40Mode) {
          const up = calibration?.up.length || 0, down = calibration?.down.length || 0;
          horizonNote.textContent = `V40 · XANH ${up} / ĐỎ ${down} NẾN · GIỮ NGUYÊN V39`;
          horizonNote.title = 'V40 giữ nguyên toàn bộ logic và hình dạng V39, với sàn 10 nến tính từ Entry. Không ép nến cuối chạm TP/SL.';
          horizonNote.hidden = !forecastCandleVisible;
          $("forecast-candle-toggle").title = `V40 · Nến hollow lịch sử · Xanh ${up} nến (${sourceLabel(preview?.up_representative)}) · Đỏ ${down} nến (${sourceLabel(preview?.down_representative)}) · Giữ nguyên scale V39`;
          $("forecast-line-toggle").title = 'Bật/tắt đường TP/SL và vùng nến dự báo V40';
        }
        if (zigzagForecastMode) {
          const up = calibration?.up.length || 0, down = calibration?.down.length || 0;
          horizonNote.textContent = `ZIGZAG · TĂNG ${up} / GIẢM ${down} NẾN`;
          horizonNote.title = 'Mũi tên gồm các đoạn thẳng nối pivot ZigZag trên chuỗi 20+ nến lịch sử đại diện; mũi tên kết thúc đúng TP/SL. Đoạn ngang sang trục giá chỉ là đường tham chiếu.';
          horizonNote.hidden = !forecastCandleVisible;
          $("forecast-candle-toggle").title = `Nến hollow lịch sử · Tăng ${up} nến (${sourceLabel(preview?.up_representative)}) · Giảm ${down} nến (${sourceLabel(preview?.down_representative)}) · ${amplitudeNote}`;
          $("forecast-line-toggle").title = 'Bật/tắt mũi tên ZigZag và đoạn ngang nối TP/SL';
          if (guidedForecastMode || spotlightForecastMode) {
            horizonNote.textContent = spotlightForecastMode ? 'KỊCH BẢN TẠI ENTRY · MÔ PHỎNG LỊCH SỬ' : `GUIDED PATH · ${up}–${down} NẾN · PIVOT LỊCH SỬ`;
            horizonNote.title = 'Đường gấp khúc nối các điểm ngoặt từ chuỗi lịch sử đại diện và dừng ở nhịp thuận chiều. TP/SL là mốc tham chiếu riêng.';
            horizonNote.hidden = !forecastLineVisible;
            $("forecast-candle-toggle").title = `Bật candle hollow để xem chuỗi nguồn · ${up} nến xanh / ${down} nến đỏ · Đường chính nối các pivot lịch sử`;
            $("forecast-line-toggle").title = 'Bật/tắt đường Guided Path, pivot và mốc TP/SL';
          }
        }
        if (meanForecastMode) {
          const up=calibration?.up.length||0,down=calibration?.down.length||0;
          horizonNote.textContent=`TRUNG BÌNH LỊCH SỬ · XANH ${up} / ĐỎ ${down} NẾN`;
          horizonNote.title='Trung bình Open/High/Low/Close theo từng vị trí nến, chuẩn hóa tại Entry. Dùng các chuỗi lịch sử đã có đủ dữ liệu trước Entry.';
          horizonNote.hidden=!forecastCandleVisible;
          $("forecast-candle-toggle").title=`Trung bình OHLC lịch sử · Xanh ${up} nến / ${preview.up_path_count||0} mẫu · Đỏ ${down} nến / ${preview.down_path_count||0} mẫu · Tối thiểu 20 nến khi đủ dữ liệu nguồn`;
        }
        updateForecastLayerVisibility();
      }
      return;
    }
    clearForecastVisuals();
    const prediction = signal?.prediction;
    const entry = Number(signal?.entry);
    if (!patternTimeframes.has(state.tf) || !prediction || !Number.isFinite(entry) || entry <= 0) return;
    const horizon = Math.max(3, Math.min(Number(prediction.horizon_bars) || 7, 12));
    const step = period[state.tf];
    const tp = Number(signal?.tp);
    const sl = Number(signal?.sl);
    const hasLiveLevels = Number.isFinite(tp) && Number.isFinite(sl) && tp > 0 && sl > 0;
    const upTarget = hasLiveLevels ? (signal.direction === "LONG" ? tp : sl) : entry * (1 + Math.max(0, Number(prediction.up_median_move) || 0));
    const downTarget = hasLiveLevels ? (signal.direction === "LONG" ? sl : tp) : entry * (1 - Math.max(0, Number(prediction.down_median_move) || 0));
    const upRows = Array.isArray(prediction.up_candles) ? prediction.up_candles.filter((row) => [row.open, row.high, row.low, row.close].every((value) => Number.isFinite(Number(value)))) : [];
    const downRows = Array.isArray(prediction.down_candles) ? prediction.down_candles.filter((row) => [row.open, row.high, row.low, row.close].every((value) => Number.isFinite(Number(value)))) : [];
    // Use the engine's averaged historical OHLC path directly. The affine
    // normalization anchors its first open at Entry and its last close at
    // TP/SL, while preserving every intermediate wiggle and wick. There is
    // deliberately no synthetic pullback or linear fallback.
    // V34 uses the same historical-mean OHLC preview as the reference image:
    // no fabricated pullback, no mirrored candles and no nearest-candle
    // fallback. The only normalization is Entry at the first path point and
    // TP/SL at the terminal point.
    const upProjection = historicalProjection(upRows, entry, upTarget, signal.available_at, step, horizon);
    const downProjection = historicalProjection(downRows, entry, downTarget, signal.available_at, step, horizon);
    const upCandles = forecastNativeCandleMode ? upProjection.candles : [];
    const downCandles = forecastNativeCandleMode ? downProjection.candles : [];
    const upPath = upProjection.path;
    const downPath = downProjection.path;
    forecastUpSeries.setData(upPath);
    forecastDownSeries.setData(downPath);
    if (forecastCandleMode) {
      forecastUpCandleSeries?.setData(upCandles);
      forecastDownCandleSeries?.setData(downCandles);
    }
    forecastLayout = [signal.available_at, signal.available_at + horizon * step, entry, upTarget, downTarget, upCandles, downCandles, upPath, downPath];
    $("forecast-up-label-prob").textContent = `${(Number(prediction.up_probability || 0) * 100).toFixed(0)}%`;
    $("forecast-down-label-prob").textContent = `${(Number(prediction.down_probability || 0) * 100).toFixed(0)}%`;
    $("forecast-up-label-target").textContent = fmt.format(upTarget);
    $("forecast-down-label-target").textContent = fmt.format(downTarget);
    $("forecast-up-price-tag").textContent = fmt.format(upTarget);
    $("forecast-down-price-tag").textContent = fmt.format(downTarget);
    $("forecast-up-label").title = `${signal.direction === "LONG" ? "TP" : "SL"} · mức 1:1`;
    $("forecast-down-label").title = `${signal.direction === "LONG" ? "SL" : "TP"} · mức 1:1`;
    if (forecastNativeCandleMode) {
      const count = Number(prediction.path_sample_count || 0);
      const peerCount = Number(prediction.path_cross_asset_count || 0);
      const basis = count ? ` · trung bình ${count} mẫu tương tự${peerCount ? ` · ${peerCount} mẫu từ coin tương đồng` : ""}` : " · chưa đủ mẫu đường nến tương tự";
      $("forecast-up-label").title += basis;
      $("forecast-down-label").title += basis;
    }
    repositionForecastLabels();
  }

  function renderPattern() {
    if (!patternTimeframes.has(state.tf)) {
      patternSeries.setData([]); clearForecastVisuals();
      updateForecastLayerVisibility();
      $("pattern-explorer").hidden = true;
      state.selected = null; state.patternView = {};
      updateSpotlightFocusButton();
      updateNotification();
      return;
    }
    const view = patternPresentation.timeline(state.data?.signals || [], state.selectionPinned ? state.selected?.id : null);
    state.selected = view.main;
    state.patternView = view;
    updateSpotlightFocusButton();
    const signal = state.patterns ? view.main : null;
    const visible = Boolean(signal);
    const signature = [state.patterns, signal?.id, signal?.status, signal?.validation_samples,signal?.configured_win_rate,
      signal?.prediction?.path_sample_count, signal?.prediction?.up_path_count, signal?.prediction?.down_path_count, signal?.prediction?.path_start,
      signal?.prediction?.up_representative?.source_time, signal?.prediction?.down_representative?.source_time,
      forecastVersion, view.index, view.total].join("|");
    if (signature === patternRenderKey) return;
    patternRenderKey = signature;
    const firstTime = state.data?.candles[0]?.time || 0;
    const points = visible ? signal.points.filter((p) => p.time >= firstTime) : [];
    // EMA peaks can have duplicate pivot timestamps; chart data must be unique.
    const structuralPoints=points.filter((point, i) => i === points.length - 1 || point.time !== points[i + 1].time);
    patternSeries.setData(structuralPoints);
    renderForecast(signal);
    $("pattern-explorer").hidden = !visible;
    $("pattern-previous").disabled = !view.older;
    $("pattern-next").disabled = !view.newer;
    $("pattern-latest").disabled = view.main?.id === view.latest?.id;
    if (!signal) return;
    $("pattern-current-name").textContent = patternName(signal);
    $("pattern-current-status").textContent = isLiveSignal(signal) ? "Đang mở" : "Lịch sử";
    $("pattern-current-status").classList.toggle("is-open", isLiveSignal(signal));
    $("pattern-current-time").textContent = dateTime(signal.available_at) + " UTC";
    $("pattern-current-time").dateTime = new Date(signal.available_at * 1000).toISOString();
    $("pattern-focus-button").title = `${patternName(signal)} · ${signal.method} · ${signal.direction} · ${statusName[signal.status]} · Bấm để định vị`;
    $("pattern-previous").title = view.older ? `Cũ hơn: ${patternName(view.older)} · ${dateTime(view.older.available_at)} UTC` : "Đã đến pattern đầu tiên";
    $("pattern-next").title = view.newer ? `Mới hơn: ${patternName(view.newer)} · ${dateTime(view.newer.available_at)} UTC` : "Đã đến pattern mới nhất";
    updateNotification();
  }

  function renderPipeline() {
    const meta = state.data?.pipeline;
    if (!meta) return;
    const ready = meta.status === "live";
    const labels = {snapshot:"Dữ liệu pattern đã quét · Demo snapshot",awaiting_validation:"Đang chờ kiểm định mô hình",no_qualified_patterns:`Chưa có pattern đạt >55% và đủ ${meta.minimum_samples??100} mẫu kiểm định`,backfilling:"Đang quét 2 tháng",catching_up:"Đang xét nến mới",error:"Quét bị gián đoạn",stale:"Đang nối lại bộ quét",live:"Đã quét đủ 2 tháng",disabled:"Pattern search 1D đang tạm dừng"};
    $("pipeline-status").dataset.status = meta.status;
    const cachedNote = state.data.signals.some(signal=>signal.bootstrap_snapshot) ? ' · Hiển thị lịch sử đã quét trong lúc đồng bộ thống kê' : '';
    $("pipeline-status").textContent = `${state.symbol==="BTCUSDT" && state.tf!=="1d"?"BTC baseline cố định · ":""}${labels[meta.status] || meta.status}${["awaiting_validation","no_qualified_patterns","disabled"].includes(meta.status)?"":` · ${meta.evaluated_bars.toLocaleString("en-US")} / ${meta.expected_bars.toLocaleString("en-US")} nến${ready ? " · Theo nến đóng" : ""}`}${meta.accuracy_anchor?" · Từ "+dateTime(meta.accuracy_anchor,true):""}${cachedNote}`;
    $("pipeline-status").title = meta.error || `${meta.scan_from ? dateTime(meta.scan_from) : ""} — ${meta.scan_to ? dateTime(meta.scan_to) : ""} UTC · ${state.data.signals.length} cấu trúc · ${meta.winner_observations || 0} lần khớp · Kiểm tra nguồn mỗi 3 giây`;
  }

  function renderHistory() {
    if (!$("signal-history")) return;
    const all = historySignals();
    const open = all.filter(isLiveSignal);
    const rows = state.filter === "open" ? open : all;
    $("all-count").textContent = all.length;
    $("open-count").textContent = open.length;
    $("more-signals").hidden = rows.length <= state.limit;
    $("history-source-toggle").textContent = state.historyMode === "demo" ? "DEMO" : `ENGINE ${ticker()}`;
    $("history-source-toggle").setAttribute("aria-pressed", state.historyMode === "demo");
    $("history-summary").textContent = state.historyMode === "demo" ? "Dữ liệu minh họa đa coin · Whales copy / Quant / Macro" : `${Math.min(state.limit, rows.length)} / ${rows.length} · Engine ${ticker()} · PNL nghiên cứu, chưa trừ phí`;
    $("signal-rows").innerHTML = rows.slice(0, state.limit).map((signal) => `
      <tr class="${signal.id === state.selected?.id ? "is-selected" : ""}">
        <td><span class="row-asset" title="${esc(coins[signal.ticker || ticker()].name)}">${coinMark(signal.ticker || ticker())} ${esc(signal.ticker || ticker())}</span></td>
        <td><span class="signal-type type-${signal.typeClass || "quant"}" title="${signal.is_demo ? "Dữ liệu minh họa · " + esc(signal.type) : esc(patternName(signal)) + " · " + esc(signal.method)}">${esc(signal.type || "Pattern")}</span></td>
        <td><span title="${esc(signal.tf || signal.horizon)}">${esc(signal.horizon || signal.tf)}</span></td><td class="numeric">${money(signal.entry,signal.ticker)}</td><td class="numeric">${money(signal.close,signal.ticker)}</td>
        <td class="numeric ${signal.pnl == null ? "" : signal.pnl >= 0 ? "positive" : "negative"}">${pct(signal.pnl)}</td>
        <td><span class="row-time">${isLiveSignal(signal) ? '<span class="live-tag">• LIVE</span>' : ""}${dateTime(signal.is_demo?signal.detected_at:signal.available_at)} UTC</span><span class="row-status" title="${signal.is_demo ? "Trạng thái mẫu, không phải giao dịch thực" : signal.reference_only ? "Độ tương đồng vượt 90% nhưng chưa qua bộ lọc accuracy/sample" : signal.backfilled?"Dựng lại bằng mô hình được chọn sau thời điểm dữ liệu":"Trạng thái tín hiệu sau khi mô hình kích hoạt"}">${signal.is_demo ? (signal.status === "OPEN" ? "Đang mở · mẫu" : "Đã đóng · mẫu") : signal.reference_only ? "Tham khảo · Similarity >90%" : (signal.backfilled?"LS nghiên cứu · ":"")+statusName[signal.status]}</span></td>
        <td><button class="detail-button" data-signal="${esc(signal.id)}" aria-label="Chi tiết ${signal.is_demo ? esc(signal.ticker) + " " + esc(signal.type) : esc(patternName(signal))} ${dateTime(signal.is_demo?signal.detected_at:signal.available_at)}">Chi tiết ↗</button></td>
      </tr>`).join("") || `<tr><td colspan="8" class="empty-state">${state.filter==="open"?"Chưa có tín hiệu đang mở.":"Chưa có pattern được kích hoạt theo tiêu chí kiểm định."}</td></tr>`;
  }

  function selectSignal(signal, {focus = true, scroll = true} = {}) {
    // Capture before updating the pattern series: a different structure must
    // not change the user's horizontal zoom or vertical units per pixel.
    const timeScale = chart.timeScale();
    const priceScale = candles.priceScale();
    const logical = focus ? timeScale.getVisibleLogicalRange() : null;
    const prices = focus ? priceScale.getVisibleRange() : null;
    const barSpacing = timeScale.options().barSpacing;
    state.selected = signal;
    state.followedPatternId = signal?.id || null;
    state.selectionPinned = true;
    patternRenderKey = "";
    renderPattern();
    if (focus && logical) {
      const first = state.data.candles.findIndex(bar => bar.time >= signal.points[0].time);
      const last = state.data.candles.findIndex(bar => bar.time >= signal.points.at(-1).time);
      if (first >= 0 && last >= 0) {
        const span = logical.to - logical.from;
        const center = (first + last) / 2;
        const from = Math.max(0, center - span / 2);
        timeScale.setVisibleLogicalRange({from, to:from + span});
        timeScale.applyOptions({barSpacing});
        if (spotlightSavedView?.logical) {
          const originalSpan = spotlightSavedView.logical.to - spotlightSavedView.logical.from;
          const originalFrom = Math.max(0, center - originalSpan / 2);
          spotlightSavedView.logical = {from:originalFrom, to:originalFrom + originalSpan};
        }
        if (prices && Number.isFinite(prices.from) && Number.isFinite(prices.to) && prices.to > prices.from) {
          const values = signal.points.map(p => p.value);
          const priceCenter = (Math.min(...values) + Math.max(...values)) / 2;
          const priceSpan = prices.to - prices.from;
          priceScale.setVisibleRange({from:priceCenter - priceSpan / 2, to:priceCenter + priceSpan / 2});
          if (spotlightSavedView?.prices) {
            const originalSpan = spotlightSavedView.prices.to - spotlightSavedView.prices.from;
            spotlightSavedView.prices = {from:priceCenter - originalSpan / 2, to:priceCenter + originalSpan / 2};
          }
        }
      }
    }
    renderHistory();
    updateNotification();
    if (focus && scroll) $("chart-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function applyCandle(bar, eventTime) {
    if (bar.symbol!==state.symbol || bar.timeframe!==state.tf || state.data?.symbol!==state.symbol) return;
    if (!state.data || ![bar.time,bar.open,bar.high,bar.low,bar.close,bar.volume].every(Number.isFinite)) return;
    if (bar.low > Math.min(bar.open,bar.close) || bar.high < Math.max(bar.open,bar.close) || bar.volume < 0) return;
    const values = state.data.candles;
    const last = values.at(-1);
    if (bar.time < last.time || (bar.time === last.time && eventTime < lastCandleEvent)) return;
    if (bar.time > last.time + period[state.tf]) {
      if (!resyncInFlight) {
        resyncInFlight = true;
        loadMarket({preserve:true,keepViewport:true}).finally(() => { resyncInFlight = false; });
      }
      return;
    }
    const added = bar.time > last.time;
    if (added) { last.closed = true; values.push(bar); }
    else values[values.length - 1] = bar;
    lastCandleEvent = eventTime;
    state.data.as_of = bar.time;
    state.data.data_end = bar.time;
    state.data.dataset_rows = values.length;
    candles.update(nativeForecast ? nativeForecast.marketBar(bar) : {time:bar.time,open:bar.open,high:bar.high,low:bar.low,close:bar.close});
    const previous = added ? emaValues.at(-1)?.value : emaValues.at(-2)?.value;
    const value = previous == null ? bar.close : previous + (2 / 21) * (bar.close - previous);
    const ema = {time:bar.time,value};
    if (added) emaValues.push(ema); else emaValues[emaValues.length - 1] = ema;
    emaSeries.update(nativeForecast ? nativeForecast.emaPoint(ema) : ema);
    if (added || bar.closed) {
      clearTimeout(patternRefreshTimer);
      patternRefreshTimer = setTimeout(refreshPatterns, 2500);
    }
  }

  function applyTicker(ticker) {
    if (ticker.symbol!==state.symbol || ticker.timeframe!==state.tf || state.data?.symbol!==state.symbol) return;
    if (!state.data || ticker.updated_at < lastTickerEvent) return;
    if (![ticker.last,ticker.change_24h,ticker.high_24h,ticker.low_24h,ticker.volume_24h,ticker.updated_at].every(Number.isFinite)) return;
    lastTickerEvent = ticker.updated_at;
    Object.assign(state.data, {last:ticker.last,change_24h:ticker.change_24h,high_24h:ticker.high_24h,low_24h:ticker.low_24h,volume_24h:ticker.volume_24h,updated_at:ticker.updated_at});
    renderPrices();
  }

  async function refreshPatterns() {
    const request = state.request, tf = state.tf, symbol=state.symbol;
    if (!state.data || state.data.mode === 'snapshot' || patternPollRequest === request) return;
    patternPollRequest = request;
    try {
      const result = await fetchJSON(`/api/patterns?symbol=${encodeURIComponent(symbol)}&tf=${encodeURIComponent(tf)}&view=${forecastApiView}`);
      if (request !== state.request || tf !== state.tf || symbol!==state.symbol) return;
      if (result.symbol!==symbol || result.timeframe!==tf) throw new Error("Sai nguồn pattern.");
      result.signals=patternPresentation.timeline(result.signals).items.reverse();
      state.data.pipeline = result.pipeline;
      // A server reconnect may briefly return an empty bootstrap snapshot.
      // Keep the reader's selection until a complete scan is authoritative.
      if (["live","no_qualified_patterns","awaiting_validation"].includes(result.pipeline?.status) || result.signals.length) {
        state.data.signals = result.signals;
        state.selected = result.signals.find((signal) => signal.id === state.selected?.id) || result.signals[0] || null;
        observePatternNotifications(result.signals, result.server_time);
      }
      renderPattern();
      renderHistory();
      renderPipeline();
    } catch {
      $("pipeline-status").dataset.status = "error";
      $("pipeline-status").textContent = "Bộ quét đang gián đoạn · Đang thử kết nối lại";
    } finally { if (patternPollRequest === request) patternPollRequest = null; }
  }

  function observePatternNotifications(signals, serverTime) {
    const fresh = notificationSession.observe(marketKey(), signals.filter(s=>s.actionable), serverTime, period[state.tf]);
    const note = state.notifications[marketKey()] ||= {latestNew:null,unread:new Set()};
    if (fresh.length) {
      note.latestNew = fresh[0];
      fresh.forEach(signal => note.unread.add(signal.id));
      if (!$("pattern-notification").hidden) note.unread.clear();
      toast(`New pattern · ${ticker()} · ${patternName(fresh[0])} · ${state.tf}`);
    }
    updateNotification();
  }

  function notificationSignal() {
    const recent = state.notifications[marketKey()]?.latestNew;
    return state.selected || state.data?.signals.find(signal => signal.id === state.followedPatternId) || state.data?.signals.find(signal => signal.id === recent?.id) || state.data?.signals[0];
  }

  function updateNotification() {
    const note = state.notifications[marketKey()];
    const latest = notificationSignal();
    $("alert-button-label").textContent = latest ? `Theo dõi ${patternName(latest)}` : "Theo dõi pattern";
    $("notification-empty").hidden = Boolean(latest);
    $("notification-content").hidden = !latest;
    $("notification-dot").hidden = !note?.unread.size || !$("pattern-notification").hidden;
    $("notification-heading-label").textContent = latest && latest.id === note?.latestNew?.id ? "PATTERN MỚI" : "PATTERN ĐANG XEM";
    $("pattern-alert-note").textContent = note?.unread.size ? `${note.unread.size} pattern mới trong phiên` : "Báo khi có pattern mới trong phiên";
    if (!latest) return;
    $("notification-time").textContent = `${ticker()} · ${dateTime(latest.available_at)} UTC · ${latest.tf}`;
    $("notification-name").textContent = patternName(latest);
    $("notification-direction").textContent = latest.direction === "LONG" ? "Hướng tăng · LONG" : "Hướng giảm · SHORT";
    $("notification-direction").className = "notification-direction " + (latest.direction === "LONG" ? "positive" : "negative");
    $("notification-pattern-status").textContent = latest.reference_only ? "Tham khảo · Similarity >90% · không kích hoạt" : isLiveSignal(latest) ? "Đang mở" : `${latest.backfilled?"Lịch sử dựng lại":"Lịch sử"} · ${statusName[latest.status]}`;
    $("notification-match-label").textContent = "Độ khớp hình dạng";
    const similarity = Number(latest.similarity);
    $("notification-similarity").textContent = Number.isFinite(similarity) ? `${similarity.toFixed(1)}%` : "—";
    const prediction=latest.prediction;
    $("notification-up-probability").textContent = prediction ? `${(Number(prediction.up_probability || 0) * 100).toFixed(0)}%` : "—";
    $("notification-down-probability").textContent = prediction ? `${(Number(prediction.down_probability || 0) * 100).toFixed(0)}%` : "—";
    $("notification-evidence-note").textContent = latest.reference_only ? "Độ tương đồng vượt 90% nhưng cấu hình chưa đạt bộ lọc; chỉ dùng để quan sát hình dạng." : latest.accuracy_source==="frozen_btc"?"BTC sử dụng cấu hình chuẩn đã cố định, không được chọn lại.":`Đã quan sát từ ${dateTime(latest.accuracy_anchor)} UTC · ${latest.validation_samples || "—"} trường hợp đã kết thúc.`;
    $("notification-accuracy-note").textContent=prediction?`Xác suất tăng/giảm từ ${prediction.sample_count} trường hợp đã kết thúc; giá đích trên chart là mức TP/SL đối xứng 1:1 của setup hiện tại. Đây là thống kê lịch sử, không phải cam kết giá.`:"Chưa đủ trường hợp lịch sử để tính hai xác suất tăng/giảm.";
  }

  function closeNotification() {
    $("pattern-notification").hidden = true;
    $("alert-button").setAttribute("aria-expanded", "false");
    updateNotification();
  }

  const showInfo = async () => {
    $("info-dialog").showModal();
    try {
      const result=await fetchJSON("/api/research");
      const rows=result.report?.results || [];
      $("research-summary").textContent=result.progress.status==="complete"?`Đã xét ${rows.length} tổ hợp mẫu × thị trường; ${rows.filter(r=>r.qualified).length} tổ hợp đạt tiêu chí. Đây là sàng lọc nghiên cứu, chưa phải bảo đảm hiệu quả thực tế.`:`Trạng thái nghiên cứu: ${result.progress.status} · ${result.progress.symbol || ""} ${result.progress.timeframe || ""}`;
    } catch { $("research-summary").textContent="Chưa tải được báo cáo kiểm định."; }
  };
  ["data-info", "history-info"].forEach((id) => $(id)?.addEventListener("click", showInfo));
  $("about-nav").addEventListener("click",()=>window.location.assign(new URL('research.html',window.location.href).href));
  ["report-button", "performance-nav", "ranking-nav"].forEach((id) => $(id)?.addEventListener("click", showInfo));
  $("close-dialog").addEventListener("click", () => $("info-dialog").close());
  $("info-dialog").addEventListener("click", (event) => { if (event.target === $("info-dialog")) { const r = event.target.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) event.target.close(); } });
  document.querySelectorAll("[data-frame]").forEach((button) => button.addEventListener("click", async () => {
    if (state.tf === button.dataset.frame) return;
    state.tf = button.dataset.frame;
    state.limit = 4;
    closeNotification();
    await loadMarket();
  }));
  $("ema-toggle").addEventListener("click", () => { state.ema = !state.ema; $("ema-toggle").setAttribute("aria-pressed", state.ema); emaSeries.applyOptions({ visible: state.ema }); });
  $("forecast-line-toggle").addEventListener("click", () => { forecastLineVisible = !forecastLineVisible; updateForecastLayerVisibility(); });
  $("forecast-candle-toggle").addEventListener("click", () => { if (spotlightForecastMode) return; forecastCandleVisible = !forecastCandleVisible; updateForecastLayerVisibility(); });
  $("forecast-long-toggle").addEventListener("click", () => { forecastLongVisible = !forecastLongVisible; updateForecastLayerVisibility(); });
  $("forecast-short-toggle").addEventListener("click", () => { forecastShortVisible = !forecastShortVisible; updateForecastLayerVisibility(); });
  $("pattern-toggle").addEventListener("click", () => { state.patterns = !state.patterns; $("pattern-toggle").setAttribute("aria-pressed", state.patterns); updateForecastLayerVisibility(); if (state.data) renderPattern(); });
  $("spotlight-focus").addEventListener("click", toggleSpotlightFocus);
  $("pattern-previous").addEventListener("click", () => { if (state.patternView.older) selectSignal(state.patternView.older, {scroll:false}); });
  $("pattern-next").addEventListener("click", () => { if (state.patternView.newer) selectSignal(state.patternView.newer, {scroll:false}); });
  $("pattern-latest").addEventListener("click", () => { if (state.patternView.latest) selectSignal(state.patternView.latest, {scroll:false}); });
  $("pattern-focus-button").addEventListener("click", () => { if (state.selected) selectSignal(state.selected, {scroll:false}); });
  $("reset-chart").addEventListener("click", resetRange);
  $("expand-chart").addEventListener("click", () => { const expanded = $("terminal").classList.toggle("is-expanded"); $("expand-chart").setAttribute("aria-pressed", expanded); });
  $("signal-rows")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-signal]");
    if (!button) return;
    const signal = historySignals().find((s) => s.id === button.dataset.signal);
    if (!signal) return;
    if (!signal.is_demo) { selectSignal(signal); return; }
    $("demo-signal-title").textContent = `${signal.ticker} · ${signal.type}`;
    $("demo-signal-time").textContent = dateTime(signal.detected_at) + " UTC";
    $("demo-signal-details").innerHTML = [
      ["Tài sản", `${coins[signal.ticker].name} (${signal.ticker})`], ["Loại", signal.type],
      ["Khung giao dịch", signal.horizon], ["Hướng", signal.direction],
      ["Entry", money(signal.entry)], ["Close", money(signal.close)], ["PNL", pct(signal.pnl)],
      ["Trạng thái", signal.status === "OPEN" ? "Đang mở" : "Đã đóng"],
    ].map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join("");
    $("demo-signal-dialog").showModal();
  });
  $("history-source-toggle")?.addEventListener("click", () => { state.historyMode = state.historyMode === "demo" ? "engine" : "demo"; state.limit = 4; renderHistory(); });
  $("close-demo-signal").addEventListener("click", () => $("demo-signal-dialog").close());
  $("latest-button").addEventListener("click", resetRange);
  document.querySelectorAll("[data-range]").forEach((button) => button.addEventListener("click", () => {
    if (!state.data) return;
    const bars = state.data.candles, last = bars.at(-1).time;
    const seconds = button.dataset.range === "1w" ? 7 * 86400 : button.dataset.range === "1m" ? 30 * 86400 : Infinity;
    const first = bars.find((bar) => bar.time >= last - seconds) || bars[0];
    candles.priceScale().setAutoScale(true);
    chart.timeScale().setVisibleRange({from:first.time,to:last});
  }));
  $("chart-state").addEventListener("click", (event) => { if (event.target.closest("#retry-market")) loadMarket({preserve:true}); });
  document.querySelectorAll("[data-filter]").forEach((button) => button.addEventListener("click", () => { state.filter = button.dataset.filter; state.limit = 4; document.querySelectorAll("[data-filter]").forEach((b) => b.classList.toggle("selected", b === button)); renderHistory(); }));
  $("more-signals")?.addEventListener("click", () => { state.limit += 8; renderHistory(); });
  $("alert-button").addEventListener("click", () => {
    const open = $("pattern-notification").hidden;
    $("pattern-notification").hidden = !open;
    $("alert-button").setAttribute("aria-expanded", open);
    if (open) state.notifications[marketKey()]?.unread.clear();
    updateNotification();
  });
  $("close-notification").addEventListener("click", closeNotification);
  $("notification-view").addEventListener("click", () => { const signal = notificationSignal(); closeNotification(); if (signal) selectSignal(signal); });
  document.addEventListener("click", (event) => { if (!$("notification-anchor").contains(event.target)) closeNotification(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeNotification(); });
  function renderAssetIdentity() {
    const coin=coins[ticker()];
    $("asset-heading").innerHTML=`${esc(coin.name)} <span>${ticker()}</span>`;
    $("asset-glyph").textContent=coin.glyph;
    $("asset-glyph").classList.toggle("near-glyph",ticker()==="NEAR");
    $("asset-pair").innerHTML=`${ticker()}<span class="quote"> / USDT</span>`;
    $("asset-subtitle").textContent=coin.name+" · Spot";
    $("overview-eyebrow").textContent="TỔNG QUAN · "+ticker();
    $("asset-description").textContent=ticker()==="BTC"?"Mạng thanh toán ngang hàng và tài sản số lớn nhất theo vốn hóa, vận hành bởi cộng đồng phát triển mã nguồn mở.":`${coin.name} · Giá và pattern được phân tích riêng từ ${ticker()}/USDT trên Binance Spot.`;
    $("chart-panel").setAttribute("aria-label","Biểu đồ giá "+coin.name);
    $("chart-title").textContent=`${ticker()} / USDT · ${state.tf} · Binance`;
    $("reference-price").textContent=$("market-price").textContent="—";
    $("market-overview-price").textContent=$("market-change").textContent=$("market-volume").textContent="—";
    $("market-overview-range").textContent="Đang tải biên độ 24h…";
    $("market-overview-heading").textContent="Đang kết nối "+coin.name+"…";
    $("reference-asof").textContent=ticker()+"/USDT · Đang kết nối…";
    $("market-range-label").textContent=" · "+ticker()+"/USDT · Đang kết nối…";
  }
  async function chooseAsset(symbol) {
    if (!supportedTickers.includes(symbol.replace(/USDT$/,''))) return;
    $("search-result").hidden=true; $("coin-query").value="";
    if (symbol===state.symbol) return;
    state.symbol=symbol; state.limit=4; state.selected=null; state.followedPatternId=null; state.selectionPinned=false; state.data=null;
    closeNotification(); renderAssetIdentity(); await loadMarket();
  }
  const searchCoin = () => {
    const q=$("coin-query").value.trim().toLowerCase();
    const matches=supportedTickers.filter(t=>!q || (t+" "+coins[t].name).toLowerCase().includes(q));
    $("search-result").hidden=false;
    $("search-result").innerHTML=matches.map(t=>`<button type="button" data-choose-symbol="${t}USDT" class="coin-search-option"><span>${coinMark(t)} <strong>${t}</strong><small>${esc(coins[t].name)}</small></span><span>${t===ticker()?"Đang xem":"USDT ↗"}</span></button>`).join("") || '<span class="search-empty">Không có coin phù hợp</span>';
  };
  $("coin-query").addEventListener("input", searchCoin);
  $("coin-search").addEventListener("submit", (event) => { event.preventDefault(); const q=$("coin-query").value.trim().toLowerCase(); const matches=supportedTickers.filter(t=>(t+" "+coins[t].name).toLowerCase().includes(q)); if(q&&matches.length===1)chooseAsset(matches[0]+"USDT"); else searchCoin(); });
  $("coin-query").addEventListener("focus",searchCoin);
  $("search-result").addEventListener("click",event=>{const button=event.target.closest("[data-choose-symbol]");if(button)chooseAsset(button.dataset.chooseSymbol);});
  document.addEventListener("click",event=>{if(!$("coin-search").contains(event.target))$("search-result").hidden=true;});
  $("coin-query").addEventListener("keydown",event=>{if(event.key==="Escape")$("search-result").hidden=true;});
  try {
    initChart();
    if (nativeV40Mode) document.title='GFI Intelligence — V40 Pattern Path · 10 candles';
    if (meanForecastMode) document.title='GFI Intelligence — V40 Mean Candle Forecast';
    if (zigzagForecastMode) {
      document.title = spotlightForecastMode ? 'GFI-Similar-Pattern' : guidedForecastMode
        ? 'GFI Intelligence — Guided Pattern Path'
        : 'GFI Intelligence — V40 Pattern Path · 10 candles';
      $("forecast-line-toggle").firstChild.textContent = guidedForecastMode || spotlightForecastMode ? 'PATH ' : 'TP/SL ';
      $("forecast-candle-toggle").firstChild.textContent = 'CANDLE ';
      $("forecast-long-toggle").title = 'Bật/tắt kịch bản tăng';
      $("forecast-short-toggle").title = 'Bật/tắt kịch bản giảm';
    }
    updateForecastLayerVisibility();
    feed = new window.GFILiveFeed({onCandle:applyCandle,onTicker:applyTicker,onStatus:setProviderStatus,onError:(error) => { $("dataset-note").title = "Binance Spot · " + error.message; }});
    document.addEventListener("visibilitychange", () => { if (!document.hidden && state.data) refreshPatterns(); });
    window.addEventListener("pagehide", () => { feed.stop(); clearInterval(patternPollTimer); });
    // Start the requested market immediately from the built-in BTC/NEAR/SOL
    // catalog. A slow catalog request must never leave the terminal stuck at
    // “Đang kết nối” before the price/chart request can begin.
    const symbol=(initialQuery.get('symbol')||'BTCUSDT').toUpperCase();
    if(supportedTickers.includes(symbol.replace(/USDT$/,''))) state.symbol=symbol;
    if(Object.hasOwn(period,initialQuery.get('tf')))state.tf=initialQuery.get('tf');
    renderAssetIdentity();
    loadMarket();
    fetchJSON('/api/assets').then(catalog => {
      supportedTickers = Object.values(catalog.assets).map(asset=>asset.ticker);
      for (const asset of Object.values(catalog.assets)) coins[asset.ticker] = {name:asset.name,glyph:asset.glyph,className:'coin-'+asset.ticker.toLowerCase()};
      // Catalog hydration is background-only. Re-running the identity reset
      // after market data renders would put the visible price back to “—”.
      if (!state.data) renderAssetIdentity();
    }).catch(()=>{});
  }
  catch (error) { setLoading(true, error.message); }
})();
