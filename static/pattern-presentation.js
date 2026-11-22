"use strict";
(() => {
  function timeline(signals, selectedId) {
    const items = collapseOccurrences(signals.filter(s => s.points?.length)).sort((a,b) =>
      (a.available_at ?? a.detected_at) - (b.available_at ?? b.detected_at) || a.id.localeCompare(b.id));
    let index = items.findIndex(s => s.id === selectedId || s.occurrence_aliases?.includes(selectedId));
    if (index < 0) index = items.length - 1;
    return {items, main:items[index] || null, index, total:items.length,
      older:items[index-1] || null, newer:items[index+1] || null, latest:items.at(-1) || null};
  }

  function structureKey(signal) {
    const points = signal.points || [];
    if (points.some(p => !Number.isFinite(p.time))) return `id:${signal.id}`;
    const pivotCore = points.length === 5 && /^(EMA Peaks|Pivot Window|ZigZag(?: Limit)?)(?: Calibrated)?$/.test(signal.method || '') && points.every(p => Number.isFinite(p.value));
    const fixed = pivotCore ? points.slice(0,-1) : points;
    return JSON.stringify([signal.symbol || signal.ticker || null, signal.tf || null, signal.method || '',
      (signal.base_pattern || signal.name || '').replace(/__Inverse$/, ''), pivotCore ? 'pivot_core' : 'exact',
      fixed.map(p => [p.time, Number.isFinite(p.value) ? Number(p.value.toFixed(8)) : null])]);
  }

  function rank(signal) {
    const rate = signal.configured_win_rate;
    const qualified = signal.actionable || (Number.isFinite(rate) && rate > .55 && Number.isFinite(signal.validation_samples) && signal.validation_samples >= (signal.minimum_samples || 0));
    return [qualified ? 1 : 0, Number.isFinite(rate) ? rate : -1, Number(signal.similarity) || 0];
  }

  function collapseOccurrences(signals) {
    const ordered = signals.slice().sort((a,b) => {
      const time = (a.available_at ?? a.detected_at ?? 0) - (b.available_at ?? b.detected_at ?? 0);
      if (time) return time;
      const left = rank(a), right = rank(b);
      for (let i=0;i<left.length;i++) if (left[i] !== right[i]) return right[i] - left[i];
      return a.id.localeCompare(b.id);
    });
    const groups = new Map(), passthrough = [];
    for (const signal of ordered) {
      if (!signal.points?.length || signal.is_demo) { passthrough.push(signal); continue; }
      const key = structureKey(signal), first = groups.get(key);
      const ids = [signal.id, ...(signal.occurrence_aliases || [])];
      const seen = signal.last_seen_at ?? signal.available_at ?? signal.detected_at ?? 0;
      if (!first) groups.set(key, {...signal, occurrence_aliases:[...new Set(ids)], last_seen_at:seen});
      else {
        first.occurrence_aliases = [...new Set([...first.occurrence_aliases,...ids])];
        first.last_seen_at = Math.max(first.last_seen_at, seen);
      }
    }
    for (const signal of groups.values()) signal.occurrence_revisions = signal.occurrence_aliases.length;
    return [...passthrough,...groups.values()];
  }

  function createNotificationSession() {
    const frames = new Map();
    return {
      observe(scope, signals, serverTime, period) {
        signals = collapseOccurrences(signals);
        const now = serverTime / 1000;
        if (!frames.has(scope)) {
          frames.set(scope, { since: now, seen: new Set(signals.map(structureKey)) });
          return [];
        }
        const frame = frames.get(scope), fresh = [];
        for (const signal of signals) {
          const key = structureKey(signal);
          if (!frame.seen.has(key) && signal.available_at > frame.since && signal.available_at <= now && now - signal.available_at <= period * 2 + 30) fresh.push(signal);
          frame.seen.add(key);
        }
        return fresh.sort((a,b) => b.available_at - a.available_at);
      },
    };
  }

  const api = { timeline, createNotificationSession, collapseOccurrences, structureKey };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else window.GFIPatternPresentation = api;
})();
