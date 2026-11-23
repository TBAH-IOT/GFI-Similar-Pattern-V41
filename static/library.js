'use strict';
const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let patterns=[],group='';
function art(p){
 const y=p.template,lo=Math.min(...y),hi=Math.max(...y),span=hi-lo||1;
 const xy=y.map((v,i)=>[22+p.template_times[i]*286,112-(v-lo)/span*82]);
 const points=xy.map(pair=>pair.join(',')).join(' '),color=p.status==='reference_only'?'#718393':'#dfbf67';
 const label='Hình minh họa '+p.display_name;
 return '<svg class="art" viewBox="0 0 330 146" role="img" aria-label="'+esc(label)+'"><path d="M22 30H308M22 71H308M22 112H308M22 18V124M93 18V124M165 18V124M237 18V124M308 18V124" stroke="#202a32" stroke-width=".7" fill="none"/><polyline points="'+points+'" stroke="'+color+'" stroke-width="2" fill="none" stroke-linejoin="round" stroke-linecap="round"/>'+xy.map(([x,y])=>'<circle cx="'+x+'" cy="'+y+'" r="2" fill="'+color+'"/>').join('')+'<text x="22" y="139" fill="#52626f" font-size="8" font-family="Consolas,monospace">'+(p.recognition==='original_5_point_similarity'?'ORIGINAL TEMPLATE':'SCHEMATIC PRICE PATH')+'</text></svg>';
}
function render(){
 const q=$('query').value.toLowerCase().trim(),implementation=$('implementation').value,direction=$('direction').value;
 const rows=patterns.filter(p=>(!group||p.group===group)&&(!implementation||(p.recognition==='weekly_context')===(implementation==='weekly'))&&(!direction||p.direction===direction)&&[p.name,p.display_name,p.description,...p.aliases].join(' ').toLowerCase().includes(q));
 $('result-count').textContent=rows.length+' / '+patterns.length+' định nghĩa';
 $('categories').querySelectorAll('button').forEach(b=>{b.classList.toggle('selected',b.dataset.group===group);b.setAttribute('aria-pressed',String(b.dataset.group===group));});
 $('cards').innerHTML=rows.map(p=>{
  const ref=p.status==='reference_only',direction=p.direction==='Up'?'Bullish':p.direction==='Down'?'Bearish':'Chờ phá biên';
 const method=p.recognition==='original_5_point_similarity'?'Template gốc':p.recognition==='weekly_context'?'Bối cảnh tuần · tham khảo':p.recognition==='curve_similarity'?'Đường giá tương tự':'Quy tắc cấu trúc';
  return '<article class="card"><div class="card-top"><div class="card-group">'+esc(p.group_label)+'</div><h2>'+esc(p.display_name)+'</h2></div>'+art(p)+'<div class="card-body"><div class="chips"><span class="chip '+(p.direction==='Down'?'bearish':p.direction==='Breakout'?'neutral':'')+'">'+direction+'</span><span class="chip '+(ref?'reference':'method')+'">'+(ref?'Chỉ tra cứu':method)+'</span></div><p>'+esc(p.description)+'</p>'+(p.aliases.length?'<p class="aliases">Còn gọi: '+p.aliases.map(esc).join(' · ')+'</p>':'')+'<details><summary>Cách triển khai &amp; nguồn</summary><p>'+esc(p.implementation_notes)+'</p><p>'+(ref?'Chưa tham gia kiểm định hoặc tạo tín hiệu.':'Đã có cách tìm tự động. Khả năng kích hoạt phụ thuộc kết quả kiểm định riêng cho từng coin × khung.')+'</p><a target="_blank" rel="noopener noreferrer" href="'+esc(p.source)+'">Tài liệu tham chiếu ↗</a></details></div></article>';
 }).join('')||'<p class="empty">Không có mô hình phù hợp. Thử một tên hoặc nhóm khác.</p>';
}
async function init(){try{
 const response=await fetch('api/catalog');if(!response.ok)throw Error('Không tải được thư viện');const data=await response.json();patterns=data.patterns;
 const groups=new Map(patterns.map(p=>[p.group,p.group_label]));
 $('total').textContent=patterns.length;$('groups-total').textContent=groups.size;$('searchable').textContent=patterns.filter(p=>p.status==='searchable').length;$('reference').textContent=patterns.filter(p=>['weekly_context','roof_geometry','wolfe_geometry','gap_classification'].includes(p.recognition)).length;
 $('categories').innerHTML=[['','Tất cả'],...groups].map(([key,label])=>'<button type="button" data-group="'+esc(key)+'" aria-pressed="false">'+esc(label)+'</button>').join('');
 $('categories').addEventListener('click',e=>{const b=e.target.closest('button');if(b){group=b.dataset.group;render();}});render();
 }catch(e){$('result-count').textContent='Không kết nối được thư viện: '+e.message;}}
['implementation','direction'].forEach(id=>$(id).addEventListener('change',render));$('query').addEventListener('input',render);init();
