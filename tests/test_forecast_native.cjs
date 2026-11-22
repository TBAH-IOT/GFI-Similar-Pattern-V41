const assert = require('node:assert/strict');
const { projectOHLC, Controller, intersectionMasks, volatilityCalibration } = require('../static/forecast-native.js');
const entry = 100, time = 1793685600, step = 3600;
const rows = [
  { open: 1, high: 1.003, low: .987, close: .991 },
  { open: .991, high: 1.001, low: .988, close: .997 },
  { open: .997, high: 1.012, low: .994, close: 1.008 },
  { open: 1.008, high: 1.011, low: 1, close: 1.003 },
  { open: 1.003, high: 1.019, low: 1.001, close: 1.016 },
  { open: 1.016, high: 1.022, low: 1.012, close: 1.019 },
  { open: 1.019, high: 1.033, low: 1.018, close: 1.03 },
  { open: 1.03, high: 1.035, low: 1.03, close: 1.035 },
  { open: 1.035, high: 1.035, low: 1.02, close: 1.025 },
  { open: 1.025, high: 1.05, low: 1.025, close: 1.04 },
];
const approx = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b}`);
for (const coinEntry of [76656.71, 4.37, 186.21]) {
  for (const tfStep of [900, 3600, 14400]) {
    const bars = projectOHLC(rows, coinEntry, time, tfStep, 10, true);
    assert.equal(bars.length, 10);
    assert.equal(bars[0].time, time+tfStep, 'Entry candle is untouched; forecast begins one real slot later');
    assert.equal(bars[0].open, coinEntry);
    for (let i = 0; i < 10; i++) {
      assert.equal(bars[i].time, time + (i+1) * tfStep);
      for (const key of ['open', 'high', 'low', 'close']) approx(bars[i][key], rows[i][key] * coinEntry);
    }
    assert.ok(bars[0].close < coinEntry, 'Historical pullback crosses Entry without invention');
    assert.ok(bars[6].close > coinEntry);
    assert.ok(new Set(bars.map(b => (b.close - b.open).toFixed(8))).size > 4, 'Keep individual OHLC bodies');
    assert.equal(bars[7].high, Math.max(bars[7].open, bars[7].close), 'No upper wick is added');
    assert.equal(bars[7].low, Math.min(bars[7].open, bars[7].close), 'Wickless real candle remains wickless');
    assert.equal(bars[8].high, bars[8].open, 'Lower-wick-only candle has no upper wick');
    assert.equal(bars[9].low, bars[9].open, 'Upper-wick-only candle has no lower wick');
  }
}
const legacy = rows.map(r => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, v + .002])));
const translated = projectOHLC(legacy, entry, time, step, 10, false);
approx(translated[0].open, entry);
approx(translated[6].close, 103);
assert.deepEqual(projectOHLC([], entry, time, step), []);
assert.deepEqual(projectOHLC([{}], entry, time, step), []);
// A historical high-volatility regime must fit the market at Entry without
// flattening individual bodies/wicks or consulting later market candles.
const calmMarket = Array.from({length:40},(_,i)=>({time:time-(40-i)*step,open:100,high:100.1,low:99.9,close:100}));
const normalized = volatilityCalibration(rows, calmMarket, entry, time);
assert.equal(normalized.basis, 'pre_entry_median_true_range');
assert.equal(normalized.referenceBars, 32);
assert.ok(normalized.scale < .2, 'Volatile source is reduced to the quieter Entry regime');
const scaled = projectOHLC(rows, entry, time, step, 10, true, normalized.scale);
for (let i=0;i<10;i++) for (const field of ['open','high','low','close']) {
  approx(scaled[i][field]-entry,(rows[i][field]-1)*entry*normalized.scale);
}
assert.ok(scaled[0].close < entry, 'Real source pullback is retained after calibration');
assert.equal(scaled[7].low,scaled[7].open,'No lower wick is invented by scaling');
assert.equal(scaled[7].high,scaled[7].close,'No upper wick is invented by scaling');
const unseenFuture = [...calmMarket,...Array.from({length:12},(_,i)=>({time:time+i*step,open:100,high:10000,low:1,close:9000}))];
assert.deepEqual(volatilityCalibration(rows,unseenFuture,entry,time),normalized,'Forecast calibration cannot look at Entry or later candles');
assert.equal(volatilityCalibration(rows,calmMarket.slice(0,10),entry,time).scale,1,'Insufficient pre-Entry history never fabricates a calibration');
const sourceCopy = JSON.stringify(rows), marketCopy = JSON.stringify(calmMarket);
volatilityCalibration(rows,calmMarket,entry,time);
assert.equal(JSON.stringify(rows),sourceCopy);
assert.equal(JSON.stringify(calmMarket),marketCopy);
let requested = 0, primitive;
const seriesCreated = [];
const makeSeries = options => ({ options, rows: [], setData(rows) { this.rows = rows; },
  applyOptions(o) { Object.assign(this.options, o); } });
const chart = {
  addSeries(kind, options) { const s = makeSeries(options); seriesCreated.push({kind, s}); return s; },
  timeScale: () => ({ timeToCoordinate: t => (t - time) / step * 6 + 60, width: () => 600 }),
  panes: () => [{ getHeight: () => 400 }],
};
const real = { priceToCoordinate: p => 200 - (p - entry) * 10,
  attachPrimitive(p) { primitive = p; p.attached({ requestUpdate: () => requested++ }); } };
const LC = { CandlestickSeries: { type: 'Candlestick' } };
const marketBars = Array.from({length:12},(_,i)=>({time:time+i*step,open:100,high:102,low:99,close:101}));
let drawnMarket = [], drawnEMA = [];
real.setData = bars => { drawnMarket = bars; };
const c = new Controller(chart, real, LC, p => p.toFixed(2), {
  getBars:()=>marketBars, getEMA:()=>marketBars.map(b=>({time:b.time,value:100})),
  emaSeries:{setData(points){drawnEMA=points;}},
});
c.show({ entry, available_at: time, tp: 120, sl: 80, prediction: {
  path_start: 'entry_bar', up_representative: {candles: rows}, down_representative: null,
  horizon_bars: 7, candle_horizon_bars: 10, up_probability: .6, down_probability: .4, path_sample_count: 45,
} }, step);
assert.equal(seriesCreated.length, 5, 'Two forecast scenarios plus three intersection-only decorations');
for (const {kind, s} of seriesCreated) {
  assert.equal(kind, LC.CandlestickSeries, 'Use exactly the same library renderer as real candles');
  assert.equal(s.options.priceScaleId, 'right');
  assert.equal(s.options.upColor, 'transparent');
  assert.equal(s.options.downColor, 'transparent');
}
assert.equal(seriesCreated[0].s.options.borderUpColor, seriesCreated[0].s.options.borderDownColor, 'Up scenario stays green through a pullback');
assert.equal(seriesCreated[1].s.options.borderUpColor, seriesCreated[1].s.options.borderDownColor, 'Down scenario stays red through a rebound');
assert.notEqual(seriesCreated[0].s.options.borderUpColor, seriesCreated[1].s.options.borderUpColor);
assert.equal(seriesCreated[0].s.rows[0].open, entry);
assert.equal(seriesCreated[0].s.rows.length, 10);
assert.equal(seriesCreated[0].s.rows[0].time,time+step);
assert.equal(drawnMarket[0].color, undefined, 'Entry bar keeps real market color');
assert.ok(drawnMarket[1].color.includes('146,161,166'), 'Only the forecast window uses subdued real candles');
assert.equal(drawnMarket[11].color,undefined);
assert.equal(marketBars[1].color,undefined,'Raw market data is never mutated');
assert.ok(drawnEMA[1].color);
approx(seriesCreated[0].s.rows[6].close, 103, 'No stretching final OHLC to TP=120');
assert.equal(seriesCreated[1].s.rows.length, 0, 'Never mirror a missing historical branch');
const moves = [], arcs = [];
const context = new Proxy({}, { get: (_, key) => key === 'moveTo' ? (...args) => moves.push(args) : key === 'arc' ? (...args) => arcs.push(args) : () => {} });
primitive.draw({ useMediaCoordinateSpace: fn => fn({ context, mediaSize: { width: 600, height: 400 } }) });
assert.deepEqual(moves[0], [60, 200], 'Entry guide begins at the exact native candle coordinate');
assert.ok(arcs.some(a => a[0] === 60 && a[1] === 200), 'White origin uses the same Entry coordinate');
assert.equal(primitive.priceAxisViews()[2].text(), '100.00');
c.visibility(false, true);
assert.equal(primitive.lineVisible, false);
assert.equal(seriesCreated[0].s.options.visible, true);
c.visibility(true, false);
assert.equal(seriesCreated[0].s.options.visible, false);
assert.equal(primitive.lineVisible, true);
assert.ok(drawnMarket.every(bar=>bar.color===undefined),'Turning off CANDLE restores the original market palette');
assert.ok(drawnEMA.every(point=>point.color===undefined));
c.visibility(true,true,false,true);
assert.equal(c.upSeries.options.visible,false,'LONG toggles only the green candle scenario');
assert.equal(c.downSeries.options.visible,true);
assert.equal(c.overlapBody.options.visible,false,'No white overlap remains when one scenario is off');
assert.equal(primitive.lineVisible,true,'Scenario toggles do not affect the dashed lines');
assert.ok(drawnMarket.every(bar=>bar.color===undefined),'A hidden sole available scenario restores market candles');
c.visibility(true,true,true,false);
assert.equal(c.upSeries.options.visible,true);
assert.equal(c.downSeries.options.visible,false,'SHORT toggles only the red candle scenario');
assert.ok(drawnMarket[1].color,'Market focus remains when one actual scenario is visible');
c.visibility(true,true,false,false);
assert.ok(drawnMarket.every(bar=>bar.color===undefined),'Turning off both scenarios restores real colors');
for(const mask of [c.overlapBody,c.overlapWickA,c.overlapWickB]) assert.equal(mask.options.visible,false);
c.visibility(true,true,true,true);
for(const mask of [c.overlapBody,c.overlapWickA,c.overlapWickB]) assert.equal(mask.options.visible,true);
c.visibility(true,false,false,true);
assert.equal(c.downSeries.options.visible,false,'CANDLE remains the master switch');
c.visibility(true,true);
assert.equal(c.upSeries.options.visible,false,'Master CANDLE retains LONG/SHORT choices');
assert.equal(c.downSeries.options.visible,true);
c.clear();
assert.equal(primitive.data, null);
assert.equal(seriesCreated[0].s.rows.length, 0);
assert.ok(requested > 0);
// Exercise the integrated renderer, including its unchanged TP/SL guide.
const calibratedController = new Controller(chart,real,LC,p=>p.toFixed(2),{getBars:()=>calmMarket});
calibratedController.show({entry,available_at:time,tp:120,sl:80,prediction:{
  path_start:'entry_bar',up_representative:{candles:rows},down_representative:{candles:rows},
  up_probability:.6,down_probability:.4,
}},step);
assert.deepEqual(calibratedController.summary.up,scaled);
assert.deepEqual(calibratedController.summary.upCalibration,normalized);
assert.equal(calibratedController.guide.data.up,120,'TP level is not altered to fit the preview');
assert.equal(calibratedController.guide.data.down,80);
assert.equal(calibratedController.guide.data.upProbability,.6);
calibratedController.visibility(true,true,false,true);
calibratedController.show({entry,available_at:time,tp:120,sl:80,prediction:{
  path_start:'entry_bar',up_representative:{candles:rows},down_representative:{candles:rows},
  up_probability:.6,down_probability:.4,
}},step);
assert.equal(calibratedController.upSeries.options.visible,false,'Pattern refresh keeps the user scenario choice');
assert.equal(calibratedController.downSeries.options.visible,true);
const intersections=intersectionMasks(
  [{time:1,open:102,close:108,high:110,low:100}],
  [{time:1,open:106,close:104,high:111,low:101}]);
assert.deepEqual(intersections.body,[{time:1,open:104,close:106,low:104,high:106}]);
assert.deepEqual(intersections.wickA,[{time:1,open:101,close:101,low:101,high:102}]);
assert.deepEqual(intersections.wickB,[{time:1,open:108,close:108,low:108,high:110}]);
assert.deepEqual(intersectionMasks([{time:1,open:1,close:2,high:2,low:1}],[{time:1,open:4,close:3,high:4,low:3}]),{body:[],wickA:[],wickB:[]});
assert.deepEqual(intersectionMasks([{time:1,open:1,close:2,high:2,low:1}],[{time:2,open:1,close:2,high:2,low:1}]),{body:[],wickA:[],wickB:[]});
console.log('PASS: pre-Entry volatility calibration without lookahead; one shared affine scale preserves candle shape/pullbacks; unchanged TP/SL probabilities; one-slot forecast offset; native widths; white intersections; reversible market palette; independent toggles.');
