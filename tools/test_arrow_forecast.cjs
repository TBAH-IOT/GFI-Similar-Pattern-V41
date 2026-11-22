const assert = require('node:assert/strict');
const {zigzag,Controller,ArrowGuide,smoothSegments} = require('../static/forecast-arrows.js');
const closes=[101,103,102,100,101,105,104,103,106,109,108,107,110,112,111,110,113,114,113,116];
const rows=closes.map((close,i)=>({time:i+1,open:i?closes[i-1]:100,high:close+.5,low:close-.5,close}));
const turns=zigzag(rows,100,0,{limit:.005});
assert.equal(turns[0].value,100);
assert.equal(turns.at(-1).value,116.5);
assert.ok(turns.length>5,'Retain real pullbacks');
assert.ok(zigzag(rows,100,0).filter(p=>p.confirmed).length<=6,'Adaptive threshold limits clutter');
for (const p of turns.slice(1)) {
  const row=rows[p.index-1];
  assert.ok(p.value>=row.low-1e-9&&p.value<=row.high+1e-9,'Every pivot comes from a historical H/L range');
}
for (const s of smoothSegments(turns.map(p=>({x:p.index*6,y:p.value})))) {
  for (let i=0;i<=100;i++) {
    const t=i/100,u=1-t;
    const y=u**3*s.start.y+3*u*u*t*s.c1.y+3*u*t*t*s.c2.y+t**3*s.end.y;
    assert.ok(y>=Math.min(s.start.y,s.end.y)-1e-9 && y<=Math.max(s.start.y,s.end.y)+1e-9,'Rounded path cannot introduce an extra swing');
  }
}
const monotone=rows.map((r,i)=>({...r,open:99+i,high:100.5+i,low:99.5+i,close:100+i}));
const monotonePivots=zigzag(monotone,100,0);
assert.ok(monotonePivots.every((p,i)=>!i||p.value>=monotonePivots[i-1].value),'Never invent a pullback for monotone data');
const hitRows=[105,112,106,100].map((close,i)=>({time:i+1,open:100,high:close+1,low:close-1,close}));
const hitPath=zigzag(hitRows,100,0,110);
assert.equal(hitPath.at(-1).value,110,'TP endpoint stays locked at the forecast target');
assert.equal(hitPath.at(-1).time,4,'The H/L-scaled 20-bar path keeps its full source horizon');
assert.ok(hitPath.slice(1).every(p=>p.value>=100&&p.value<=110),'Bullish path stays between Entry and TP');
const sigmaPath=zigzag(rows,100,0,130,{entrySigma:5});
assert.ok(sigmaPath.slice(1).every(p=>p.value>=105&&p.value<=130),'Bullish path keeps a one-sigma gap from Entry');
const series=[];
const chart={addSeries:(kind,options)=>{const s={options,rows:[],setData(x){this.rows=x;},applyOptions(x){Object.assign(this.options,x);}};series.push(s);return s;},timeScale:()=>({timeToCoordinate:t=>20+t*6,width:()=>500}),panes:()=>[{getHeight:()=>400}]};
const real={priceToCoordinate:p=>300-(p-100)*5,setData(){},attachPrimitive(p){p.attached({requestUpdate(){}});},detachPrimitive(){}};
const controller=new Controller(chart,real,{CandlestickSeries:{}},p=>p.toFixed(2),{getBars:()=>[]});
controller.visibility(true,true);
controller.show({entry:100,available_at:0,tp:130,sl:70,prediction:{path_start:'entry_bar',candle_horizon_bars:20,up_probability:.6,down_probability:.4,up_representative:{candles:rows.map(r=>({open:r.open/100,high:r.high/100,low:r.low/100,close:r.close/100}))}}},1);
assert.equal(controller.summary.up.length,15,'V40 arrow display uses a compact 15-bar window from the 20-bar source');
assert.equal(series.some(s=>s.options.visible),true,'CANDLE keeps the hollow forecast renderer available in V40');
assert.equal(controller.guide.lineVisible,false,'Old TP/SL guide stays off by default');
assert.ok(controller.arrows.branchVisible('up'));
controller.arrows.set({up:rows,down:rows,entry:100,time:0,entrySigma:10},{tp:105,sl:95,prediction:{up_probability:.6,down_probability:.4}});
assert.deepEqual(controller.arrows.lowRange,{up:true,down:true},'Low-range mode detects TP/SL inside one sigma');
controller.visibility(true,true,false,true);
assert.equal(controller.arrows.branchVisible('up'),false,'LONG switch hides only its arrow');
controller.visibility(false,false);
assert.equal(controller.arrows.branchVisible('up'),false,'Arrow switch hides the entire layer');
const emphasis=new ArrowGuide(chart,real,p=>String(p));
emphasis.spotlight=true;
let previous=0;
for (const rate of [0,.3,.5,.55,.65,.8,1]) {
  emphasis.set(null,{accuracy_source:'frozen_btc',configured_win_rate:rate});
  assert.ok(emphasis.accuracyWeight>previous,'V41 forecast weight increases with any higher validated accuracy');
  previous=emphasis.accuracyWeight;
}
emphasis.set(null,{accuracy_source:'frozen_btc',configured_win_rate:.8,reference_only:true});
assert.ok(emphasis.accuracyWeight<previous,'Unqualified references do not get high-accuracy emphasis');
emphasis.spotlight=false;
emphasis.set(null,{accuracy_source:'frozen_btc',configured_win_rate:.8});
assert.equal(emphasis.accuracyWeight,1,'Other forecast versions keep their original stroke weight');
console.log('PASS: engine reversal logic, adaptive threshold, source pivots, 20-bar source / 15-bar arrow display, independent toggles');
