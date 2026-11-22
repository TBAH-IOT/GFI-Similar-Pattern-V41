"use strict";
// Public, unauthenticated Binance Spot streams. No account or order access.
window.GFILiveFeed = class {
  constructor(handlers) {
    this.handlers = handlers;
    this.generation = 0;
    this.stopped = true;
    this.status = "";
    this.onVisible = () => { if (!document.hidden && !this.stopped) this.poll(); };
    document.addEventListener("visibilitychange", this.onVisible);
  }

  setStatus(kind) {
    if (this.status === kind) return;
    this.status = kind;
    this.handlers.onStatus(kind);
  }

  start(symbol, tf, serverTime) {
    if (!/^[A-Z0-9]{2,24}USDT$/.test(symbol)) throw new Error("Mã coin USDT không hợp lệ.");
    this.stop();
    this.stopped = false;
    this.tf = tf;
    this.symbol = symbol;
    this.lastMessage = 0;
    this.attempt = 0;
    this.lastEvent = 0;
    this.clockOffset = Date.now() - serverTime;
    this.setStatus("connecting");
    this.connect(this.generation);
    this.timer = setInterval(() => {
      if (Date.now() - this.lastMessage > 12000) {
        this.poll();
        if (this.socket?.readyState === WebSocket.OPEN && Date.now() - this.lastMessage > 20000) this.socket.close();
      }
    }, 5000);
    this.poll(); // Backfill any candles changed during initial history loading.
  }

  connect(generation) {
    if (this.stopped || generation !== this.generation) return;
    const streamSymbol = this.symbol.toLowerCase();
    const streams = `${streamSymbol}@kline_${this.tf}/${streamSymbol}@ticker`;
    const socket = new WebSocket(`wss://data-stream.binance.vision:443/stream?streams=${streams}`);
    this.socket = socket;
    socket.onmessage = (event) => {
      if (this.stopped || generation !== this.generation) return;
      try {
        const payload = JSON.parse(event.data);
        const data = payload.data || payload;
        if (data.s !== this.symbol || !Number.isFinite(data.E)) return;
        if (!["kline", "24hrTicker"].includes(data.e) || (data.e === "kline" && !data.k)) return;
        if (Math.abs((Date.now() - this.clockOffset) - data.E) > 30000) {
          this.setStatus("stale");
          this.poll();
          return;
        }
        this.lastMessage = Date.now();
        this.lastEvent = Math.max(this.lastEvent, data.E);
        this.attempt = 0;
        this.setStatus("live");
        if (data.e === "kline" && data.k.i === this.tf) {
          const k = data.k;
          this.handlers.onCandle({ symbol:this.symbol, timeframe:this.tf, time: Math.floor(k.t / 1000), open: +k.o, high: +k.h, low: +k.l, close: +k.c, volume: +k.v, closed: Boolean(k.x) }, data.E);
        } else if (data.e === "24hrTicker") {
          this.handlers.onTicker({ symbol:this.symbol, timeframe:this.tf, last: +data.c, change_24h: +data.P, high_24h: +data.h, low_24h: +data.l, volume_24h: +data.v, updated_at: data.E });
        }
      } catch (error) {
        this.handlers.onError?.(error);
      }
    };
    socket.onerror = () => { if (!this.stopped && generation === this.generation) this.poll(); };
    socket.onclose = () => {
      if (this.stopped || generation !== this.generation) return;
      this.setStatus("reconnecting");
      this.poll();
      clearTimeout(this.reconnectTimer);
      const delay = Math.min(30000, 1000 * 2 ** Math.min(this.attempt++, 5));
      this.reconnectTimer = setTimeout(() => this.connect(generation), delay);
    };
  }

  async poll() {
    if (this.stopped || this.pollingGeneration === this.generation) return;
    const generation = this.generation;
    this.pollingGeneration = generation;
    try {
      const response = await fetch(`${window.GFI_API_BASE || ""}/api/tick?symbol=${encodeURIComponent(this.symbol)}&tf=${encodeURIComponent(this.tf)}`, { cache: "no-store" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Không cập nhật được dữ liệu.");
      if (this.stopped || generation !== this.generation) return;
      if (result.symbol !== this.symbol || result.timeframe !== this.tf) throw new Error("Nguồn trả về sai coin hoặc khung nến.");
      this.clockOffset = Date.now() - result.server_time;
      result.candles.forEach((bar) => this.handlers.onCandle({...bar,symbol:result.symbol,timeframe:result.timeframe}, result.server_time));
      this.handlers.onTicker(result);
      if (Date.now() - this.lastMessage > 12000) this.setStatus("polling");
    } catch (error) {
      if (!this.stopped && generation === this.generation && Date.now() - this.lastMessage > 12000) {
        this.setStatus("stale");
        this.handlers.onError?.(error);
      }
    } finally {
      if (this.pollingGeneration === generation) this.pollingGeneration = null;
    }
  }

  stop() {
    this.stopped = true;
    this.generation++;
    clearInterval(this.timer);
    clearTimeout(this.reconnectTimer);
    if (this.socket) {
      this.socket.onclose = null;
      this.socket.onerror = null;
      this.socket.onmessage = null;
      this.socket.close();
      this.socket = null;
    }
  }
};
