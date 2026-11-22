const assert=require('node:assert/strict');
const makeAdapter=require('../static/integration/similar-pattern-adapter.js');
const Presentation=require('../static/pattern-presentation.js');
let calls=[],disposed=false;
class Forecast {
  clear(){calls.push('clear')}
  show(s,step){calls.push(['show',s.id,step])}
  visibility(...args){calls.push(['visibility',...args])}
  dispose(){disposed=true}
}
const Adapter=makeAdapter({Controller:Forecast},Presentation);
const chart={addSeries:()=>({setData(rows){calls.push(['shape',rows.length])}}),removeSeries(){calls.push('remove')}};
let market,view;
const adapter=new Adapter({chart,candleSeries:{},LC:{LineSeries:{}},onMarket:d=>{market=d},onSignals:v=>{view=v}});
const signal={id:'one',symbol:'NEARUSDT',tf:'1h',name:'Wedge_Falling',method:'Pivot Window',direction:'LONG',available_at:100,points:[{time:1,value:1},{time:2,value:2}]};
global.fetch=async(url)=>({ok:true,json:async()=>({symbol:'NEARUSDT',timeframe:'1h',mode:'snapshot',candles:[],signals:[signal],pipeline:{status:'snapshot'}})});
(async()=>{
  await adapter.start('NEARUSDT','1h');assert.equal(market.symbol,'NEARUSDT');assert.equal(view.main.id,'one');
  assert.ok(calls.some(c=>Array.isArray(c)&&c[0]==='show'&&c[2]===3600));
  adapter.setVisibility({short:false});assert.deepEqual(calls.at(-1),['visibility',true,true,true,false]);
  adapter.setEnabled(false);assert.equal(calls.at(-1),'clear');
  adapter.dispose();assert.equal(disposed,true);
  console.log('PASS: existing-chart adapter loads correct market, renders patterns, applies scenario toggles and disposes; no fitContent/viewport APIs are required.');
})().catch(error=>{console.error(error);process.exitCode=1});
