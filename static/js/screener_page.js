(()=>{
 const body=document.getElementById('screeningBody'), meta=document.getElementById('screeningMeta');
 const load=async()=>{body.innerHTML='<tr><td colspan="9" class="subtle">Đang tải...</td></tr>';try{const r=await StockApp.api('/api/screening/latest');const rows=r.data||[];meta.textContent=`${r.file_name||''} · ${rows.length} mã`;
 body.innerHTML=rows.map((x,i)=>`<tr><td>${x.rank||i+1}</td><td><a class="ticker-link" href="/analysis/${StockApp.escape(x.symbol)}">${StockApp.escape(x.symbol)}</a></td><td><strong>${StockApp.num(x.final_score??x.screening_score)}</strong></td><td>${StockApp.num(x.fundamental_score)}</td><td>${StockApp.num(x.valuation_score)}</td><td>${StockApp.num(x.technical_score)}</td><td>${StockApp.num(x.risk_score)}</td><td><span class="score-pill">${StockApp.escape(x.grade||'—')}</span></td><td><button class="button secondary add-watch" data-symbol="${StockApp.escape(x.symbol)}">+ Watchlist</button></td></tr>`).join('');
 document.querySelectorAll('.add-watch').forEach(btn=>btn.addEventListener('click',async()=>{try{await StockApp.api('/api/watchlist',{method:'POST',body:JSON.stringify({symbol:btn.dataset.symbol})});StockApp.toast(`${btn.dataset.symbol} đã vào Watchlist`);}catch(e){StockApp.toast(e.message,true)}}));
 }catch(e){body.innerHTML=`<tr><td colspan="9" class="subtle">${StockApp.escape(e.message)}. Hãy chạy batch_collect.py.</td></tr>`;}};
 document.getElementById('reloadScreening')?.addEventListener('click',load);load();
})();
