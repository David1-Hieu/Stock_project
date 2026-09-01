(async()=>{
 const render=async()=>{try{const r=await StockApp.api('/api/dashboard/summary');const b=r.benchmarks||{};
   document.getElementById('vnindexValue').textContent=StockApp.num(b.VNINDEX?.close);document.getElementById('vnindexDate').textContent=b.VNINDEX?.trade_date||'Chưa có snapshot';
   document.getElementById('vn30Value').textContent=StockApp.num(b.VN30?.close);document.getElementById('vn30Date').textContent=b.VN30?.trade_date||'Chưa có snapshot';
   document.getElementById('watchCount').textContent=r.watchlist_count??0;document.getElementById('portfolioCount').textContent=r.portfolio_count??0;
   document.getElementById('topStocks').innerHTML=(r.top_stocks||[]).map(x=>`<div class="list-item"><div><a class="ticker-link" href="/analysis/${StockApp.escape(x.symbol)}">${StockApp.escape(x.symbol)}</a><small> Grade ${StockApp.escape(x.grade||'—')}</small></div><strong>${StockApp.num(x.final_score??x.screening_score)}</strong></div>`).join('')||'<div class="subtle">Chưa có screening. Chạy batch_collect.py trước.</div>';
   document.getElementById('recentRecommendations').innerHTML=(r.recent_recommendations||[]).map(x=>`<div class="list-item"><div><a class="ticker-link" href="/analysis/${StockApp.escape(x.symbol)}">${StockApp.escape(x.symbol)}</a><small> ${StockApp.escape(x.analysis_date)}</small></div><span class="status-pill">${StockApp.escape(x.action)}</span></div>`).join('')||'<div class="subtle">Chưa đủ 5 phiên theo dõi.</div>';
 }catch(e){StockApp.toast(e.message,true)}}; await render();
 document.getElementById('runMonitor')?.addEventListener('click',async e=>{const btn=e.currentTarget;btn.disabled=true;btn.textContent='Đang chạy...';try{const r=await StockApp.api('/api/monitor/run',{method:'POST',body:'{}'});StockApp.toast(`Đã capture ${r.captured_count||0} snapshot.`);await render();}catch(err){StockApp.toast(err.message,true)}finally{btn.disabled=false;btn.textContent='Chạy EOD Monitor thủ công';}});
})();
