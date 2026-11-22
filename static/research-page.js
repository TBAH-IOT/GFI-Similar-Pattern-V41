'use strict';
const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const percent=n=>n==null?'—':(n*100).toFixed(2)+'%',key=p=>p.name+'|'+p.method;
const FRAMES=['15m','1h','4h'],DEFAULTS={'15m':100,'1h':75,'4h':50};
let snapshot=null,catalog=null;
function liveFor(symbol,tf){return snapshot.live_by_symbol?.[symbol]?.[tf]||{};}
function ready(live){return ['live','no_qualified_patterns'].includes(live.status);}
function rowsFor(symbol,tf){
 const live=liveFor(symbol,tf),metrics=new Map((live.metrics||[]).map(m=>[key(m),m]));
 return (snapshot.report?.results||[]).filter(r=>r.symbol===symbol&&r.timeframe===tf).map(r=>{
  const m=ready(live)?metrics.get(key(r)):null;
  return {r,m,stats:m||r.test,active:m?m.active:r.qualified};
 });
}
async function refresh(){try{
 const results=await Promise.all([fetch('/api/research').then(r=>r.json()),fetch('/api/catalog').then(r=>r.json()),fetch('/api/btc-baseline').then(r=>r.json())]);
 [snapshot,catalog]=results;
 $('definition-count').textContent=catalog.patterns.length;
 $('strategy-count').textContent=catalog.strategies.length;
 $('catalogue-scope').textContent='78 mẫu tự động · 156 chiều thuận/ngược. Mỗi phương pháp được test riêng; không chọn mẫu hoặc ngưỡng bằng accuracy trước test. Pipeline nghiên cứu hiện chỉ chạy 15m, 1h và 4h; 1D tạm dừng.';
 const selected=$('family').value;
 $('family').innerHTML='<option value="">Tất cả nhóm mô hình giá</option>'+[...new Map(catalog.patterns.map(p=>[p.group,p.group_label]))].map(([k,v])=>'<option value="'+esc(k)+'">'+esc(v)+'</option>').join('');$('family').value=selected;
 $('btc').innerHTML='<p>BTC 15m/1h/4h giữ nguyên baseline commit '+esc(results[2].source_commit)+'. Đợt nghiên cứu 20/80 này chỉ chạy NEAR và SOL; BTC 1D chưa được kiểm định lại theo chính sách mới.</p>';
 const progress=snapshot.progress;
 $('status').textContent=progress.status==='complete'?'Hoàn tất · '+new Date(snapshot.report.activated_at).toLocaleString('vi-VN'):'Đang chạy '+(progress.symbol||'')+' '+(progress.timeframe||'')+' · '+(progress.stage||progress.status);
 render();
 }catch(e){$('status').textContent='Chưa kết nối được · '+e.message;}}
function render(){
 if(!snapshot||!catalog)return;
 const [symbol,tf]=$('timeframe').value.split(':'),live=liveFor(symbol,tf),market=snapshot.report?.markets?.[symbol+':'+tf];
 const coverage=snapshot.report?.coverage_by_market?.[symbol+':'+tf];
 const required=live.minimum_samples||coverage?.effective_minimum||DEFAULTS[tf];
 const strategies=new Map(catalog.strategies.map(p=>[p.name,p]));
 const all=rowsFor(symbol,tf),rows=all.filter(({r,active})=>{
  const p=strategies.get(r.name)||{};
  return (!$('family').value||p.group===$('family').value)&&(!$('variant').value||r.variant===$('variant').value)&&
   (!$('filter').value||active===($('filter').value==='active'))&&
   (r.display_name+' '+r.name+' '+r.method).toLowerCase().includes($('query').value.toLowerCase());
 });
 rows.sort((a,b)=>Number(b.active)-Number(a.active)||(b.stats.win_rate??-1)-(a.stats.win_rate??-1)||a.r.name.localeCompare(b.r.name)||a.r.method.localeCompare(b.r.method));
 $('active-count').textContent=all.filter(r=>r.active).length;
 $('observation-count').textContent=all.reduce((n,r)=>n+r.stats.n,0).toLocaleString('en-US');
 const c=market?.calibration;
 $('anchor').textContent=market?'Test từ '+new Date(market.test_from*1000).toLocaleString('vi-VN',{timeZone:'UTC'})+' UTC · 20% setup / 80% test · '+all.length+' cấu hình · N hiệu lực cho '+symbol.replace('USDT','')+'/'+tf+' = '+required+' mẫu.'+(coverage?(' Mục tiêu ≥'+coverage.target+' cấu hình; hiện có '+coverage.qualified_configurations+'.'):'')+(required<DEFAULTS[tf]?' Đã hạ theo ladder coverage của đúng coin–khung; đây là kết quả thăm dò.':'')+(c?' Đã khóa: ZigZag '+(c.zigzag_reversal_pct*100).toFixed(2)+'%; Pivot ±'+c.pivot_radius+' nến; EMA '+c.ema_span+' / Peaks ±'+c.ema_peak_radius+'.':''):'Khung này đang chờ chạy kiểm định.';
 const audits=all.map(x=>x.r.test.audit).filter(Boolean),sum=k=>audits.reduce((n,a)=>n+(a[k]||0),0);
 const finished=sum('completed'),expired=sum('expired'),enough=all.filter(x=>x.r.test.n>=required).length;
 $('audit-summary').textContent=audits.length?'Lượt kiểm định '+symbol.replace('USDT','')+' '+tf.toUpperCase()+': '+enough+' / '+all.length+' cấu hình đủ mẫu; '+all.filter(x=>x.r.qualified).length+' cấu hình đạt thêm accuracy >55%. Hết hạn: '+expired.toLocaleString('en-US')+' / '+finished.toLocaleString('en-US')+' mẫu đã kết thúc ('+percent(finished?expired/finished:null)+').':'Đang chờ báo cáo chẩn đoán của lượt kiểm định mới.';
 const cells=[['Tín hiệu khớp','raw_matches'],['TP/SL không hợp lệ','invalid_risk'],['Chồng lấn · vẫn giữ','kept_overlapping'],['Đang chờ kết quả','pending'],['Gián đoạn dữ liệu','gap'],['Ngoài kỳ đánh giá','outside_period'],['Đã kết thúc · N','completed']];
 $('audit-funnel').innerHTML=cells.map(([label,k])=>'<tr><td>'+label+'</td><td>'+(audits.length?sum(k).toLocaleString('en-US'):'—')+'</td></tr>').join('');
 $('rows').innerHTML=rows.map(({r,m,stats,active})=>'<tr><td><strong>'+esc(r.display_name)+'</strong><small>'+esc(strategies.get(r.name)?.group_label||'Mô hình giá')+' · '+esc(r.variant)+'</small></td><td>'+esc(r.method)+'<small>Ngưỡng cố định '+r.threshold+'</small></td><td>'+percent(stats.win_rate)+'</td><td>'+stats.n+' / '+stats.wins+'</td><td title="'+esc('Chẩn đoán lượt kiểm định: khoảng TP/SL trung vị '+percent(r.test.audit?.median_risk_pct)+' của giá entry; thời gian giữ trung vị '+(r.test.audit?.median_holding_bars??'—')+' nến. Với mẫu hết hạn, mức đi thuận trung vị đạt '+(r.test.audit?.expired_median_mfe_r==null?'—':r.test.audit.expired_median_mfe_r.toFixed(2))+' lần khoảng TP.')+'">'+(stats.expired??'—')+'<small>'+percent(stats.n?(stats.expired??0)/stats.n:null)+' / N</small></td><td>'+percent(m?.opposite_win_rate)+'</td><td class="'+((stats.mean_net_return??0)<0?'bad':'good')+'">'+percent(stats.mean_net_return)+'</td><td><span class="tag '+(active?'active':'')+'">'+(active?(ready(live)?'Đang đạt chuẩn':'Đạt kiểm định'):stats.n===0?'Chưa có mẫu kết thúc':stats.n<required?'Chưa đủ '+required+' mẫu':'Accuracy ≤55%')+'</span></td></tr>').join('')||'<tr><td colspan="8">'+(all.length?'Chưa có cấu hình phù hợp bộ lọc. Chọn “Tất cả trạng thái” để xem toàn bộ kết quả.':'Đang chờ kiểm định khung này.')+'</td></tr>';
 $('market-summary').innerHTML=['NEARUSDT','SOLUSDT'].flatMap(s=>FRAMES.map(t=>{
  const a=rowsFor(s,t),qualified=a.filter(x=>x.active),unique=new Set(qualified.map(x=>x.r.base_pattern)).size;
 const minimum=snapshot.report?.coverage_by_market?.[s+':'+t]?.effective_minimum||DEFAULTS[t];
  return '<tr><td>'+s.replace('USDT','')+'</td><td>'+t.toUpperCase()+'</td><td>'+(a.length?unique:'—')+'</td><td>'+(a.length?qualified.length:'—')+'</td><td>'+(a.length?a.filter(x=>x.stats.n>=minimum).length+' / '+a.length:'—')+'</td><td>'+minimum+'</td></tr>';
 })).join('');
}
['timeframe','family','variant','filter'].forEach(id=>$(id).addEventListener('change',render));$('query').addEventListener('input',render);$('refresh').addEventListener('click',refresh);refresh();setInterval(refresh,10000);
