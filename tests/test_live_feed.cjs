const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const now = 1793340000000;
let clock = now, nextTimer = 0;
const timers = new Map(), sockets = [], statuses = [], bars = [], tickers = [];
class FakeSocket {
  static OPEN = 1;
  constructor(url) { this.url=url; this.readyState=1; sockets.push(this); }
  close() { this.readyState=3; this.onclose?.(); }
}
const candle = {time: Math.floor(now / 3600000) * 3600, open:100,high:103,low:99,close:102,volume:3,closed:false};
const context = {
  window:{}, document:{hidden:false,addEventListener(){}}, WebSocket:FakeSocket,
  Date:class extends Date { static now(){ return clock; } },
  setTimeout:(fn)=>{timers.set(++nextTimer,fn);return nextTimer;}, clearTimeout:(id)=>timers.delete(id),
  setInterval:(fn)=>{timers.set(++nextTimer,fn);return nextTimer;}, clearInterval:(id)=>timers.delete(id),
  fetch:async(url)=>{const query=new URL(url,'http://local').searchParams;return {ok:true,json:async()=>({symbol:query.get('symbol'),timeframe:query.get('tf'),server_time:now,updated_at:now,candles:[candle],last:102,change_24h:2,high_24h:103,low_24h:99,volume_24h:20})};},
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/live-feed.js'),'utf8'),context);
const feed = new context.window.GFILiveFeed({onStatus:s=>statuses.push(s),onCandle:b=>bars.push(b),onTicker:t=>tickers.push(t),onError:e=>{throw e;}});
(async()=>{
  feed.start('BTCUSDT','1h',now);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(bars.length,1,'REST fallback supplies a real snapshot');
  assert.equal(statuses.at(-1),'polling');
  const socket=sockets.at(-1);
  socket.onmessage({data:JSON.stringify({data:{e:'24hrTicker',s:'BTCUSDT',E:now,c:'104',P:'4',h:'105',l:'99',v:'30'}})});
  assert.equal(statuses.at(-1),'live');
  assert.equal(tickers.at(-1).last,104);
  const count=tickers.length;
  socket.onmessage({data:JSON.stringify({data:{e:'24hrTicker',s:'BTCUSDT',E:now-60000,c:'1',P:'1',h:'1',l:'1',v:'1'}})});
  assert.equal(tickers.length,count,'Stale websocket events must not replace live prices');
  assert.equal(statuses.at(-1),'stale');
  socket.onclose();
  assert.equal(statuses.at(-1),'reconnecting','A disconnect schedules recovery without an undefined-variable exception');
  assert.ok(feed.reconnectTimer);
  const previousHandler=socket.onmessage;
  feed.start('BTCUSDT','4h',now);
  previousHandler({data:JSON.stringify({data:{e:'24hrTicker',s:'BTCUSDT',E:now,c:'999',P:'1',h:'999',l:'1',v:'1'}})});
  assert.notEqual(tickers.at(-1).last,999,'Old timeframe socket cannot update a new session');
  const btcHandler=sockets.at(-1).onmessage;
  feed.start('NEARUSDT','1d',now);
  await new Promise(resolve=>setImmediate(resolve));
  assert.ok(sockets.at(-1).url.includes('nearusdt@kline_1d/nearusdt@ticker'));
  assert.equal(tickers.at(-1).symbol,'NEARUSDT');
  btcHandler({data:JSON.stringify({data:{e:'24hrTicker',s:'BTCUSDT',E:now,c:'999',P:'1',h:'999',l:'1',v:'1'}})});
  assert.notEqual(tickers.at(-1).last,999,'Old coin cannot contaminate NEAR');
  sockets.at(-1).onmessage({data:JSON.stringify({data:{e:'24hrTicker',s:'BTCUSDT',E:now,c:'888',P:'1',h:'888',l:'1',v:'1'}})});
  assert.notEqual(tickers.at(-1).last,888,'Wrong symbol is rejected even on the current socket');
  const nearHandler=sockets.at(-1).onmessage;
  feed.start('SOLUSDT','1w',now);
  await new Promise(resolve=>setImmediate(resolve));
  assert.ok(sockets.at(-1).url.includes('solusdt@kline_1w/solusdt@ticker'));
  assert.equal(tickers.at(-1).symbol,'SOLUSDT');
  nearHandler({data:JSON.stringify({data:{e:'24hrTicker',s:'NEARUSDT',E:now,c:'999',P:'1',h:'999',l:'1',v:'1'}})});
  assert.notEqual(tickers.at(-1).last,999,'Old NEAR session cannot contaminate SOL weekly');
  feed.stop();
  assert.equal(feed.stopped,true);
  assert.equal(sockets.at(-1).onmessage,null);
  console.log('PASS live feed: REST fallback, freshness, reconnection, symbol/timeframe isolation including 1D, cleanup');
})().catch(error=>{console.error(error);process.exitCode=1;});
