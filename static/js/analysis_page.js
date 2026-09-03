(()=>{
  const symbol = String(window.CURRENT_SYMBOL || 'FPT').trim().toUpperCase();
  let latestBundle = null;
  const $ = (id) => document.getElementById(id);
  const esc = (v) => StockApp.escape(v ?? '—');
  const num = (v, digits=2) => {
    if (v === null || v === undefined || v === '' || Number.isNaN(Number(v))) return 'N/A';
    return Number(v).toLocaleString('vi-VN', {minimumFractionDigits: digits, maximumFractionDigits: digits});
  };
  const money = (v, formatted) => formatted || (v === null || v === undefined ? 'N/A' : Number(v).toLocaleString('vi-VN'));
  const pct = (v, digits=1) => v === null || v === undefined ? 'N/A' : `${num(v,digits)}%`;
  const pill = (text, tone='') => `<span class="analysis-pill ${tone}">${esc(text)}</span>`;
  const scoreTone = (v) => Number(v) >= 80 ? 'good' : Number(v) >= 60 ? 'warn' : Number(v) > 0 ? 'bad' : '';
  const trendTone = (v) => {
    const x=String(v||'').toUpperCase();
    return x.includes('TĂNG') || x.includes('UP') || x.includes('BULL') ? 'good' : x.includes('GIẢM') || x.includes('DOWN') || x.includes('BEAR') ? 'bad' : 'warn';
  };

  const tabs=document.querySelectorAll('.tab');
  tabs.forEach(t=>t.addEventListener('click',()=>{
    tabs.forEach(x=>x.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(x=>x.classList.remove('active'));
    t.classList.add('active');
    $(`tab-${t.dataset.tab}`)?.classList.add('active');
  }));

  function setLoading(on){
    if ($('analysisLoading')) $('analysisLoading').hidden=!on;
    if ($('refreshAnalysis')) $('refreshAnalysis').disabled=on;
  }

  function status(message, error=false){
    const box=$('analysisStatus');
    if(!box) return;
    if(!message){ box.hidden=true; return; }
    box.hidden=false;
    box.className=`analysis-status ${error?'error':''}`;
    box.textContent=message;
  }

  function metricCard(label,value,help='',tone=''){
    return `<article class="metric-card"><span>${esc(label)}</span><strong class="${tone}">${value}</strong><small>${esc(help)}</small></article>`;
  }

  function dataCell(label,value,extra=''){
    return `<div class="data-cell"><span>${esc(label)}</span><strong>${value}</strong>${extra?`<small>${esc(extra)}</small>`:''}</div>`;
  }

  function renderSignals(signals={}){
    const active=Object.entries(signals||{}).filter(([,v])=>v && v.active);
    if(!active.length) return '<div class="empty-state">Không có tín hiệu kỹ thuật đang kích hoạt ở phiên gần nhất.</div>';
    return `<div class="signal-grid">${active.map(([key,v])=>{
      const negative=/bearish|death|below|overbought/.test(key);
      const positive=/bullish|golden|above|oversold|volume/.test(key) && !negative;
      const tone=negative?'bad':positive?'good':'warn';
      return `<article class="signal-card ${tone}"><div class="signal-name">${esc(key.replaceAll('_',' ').toUpperCase())}</div><div class="signal-value">${v.value===null||v.value===undefined?'':num(v.value,2)}</div><p>${esc(v.description||'')}</p></article>`;
    }).join('')}</div>`;
  }

  function renderMiniChart(rows=[]){
    const clean=(rows||[]).filter(r=>Number.isFinite(Number(r.close))).slice(-60);
    if(clean.length<2) return '<div class="empty-state">Chưa đủ dữ liệu để vẽ biểu đồ giá.</div>';
    const values=clean.map(r=>Number(r.close));
    const min=Math.min(...values), max=Math.max(...values), span=(max-min)||1;
    const w=960,h=260,pad=18;
    const pts=values.map((v,i)=>{
      const x=pad+i*(w-pad*2)/(values.length-1);
      const y=h-pad-(v-min)*(h-pad*2)/span;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    const first=clean[0],last=clean[clean.length-1];
    const change=((Number(last.close)/Number(first.close))-1)*100;
    return `<div class="analysis-chart-wrap">
      <div class="chart-meta"><div><strong>Biểu đồ giá đóng cửa</strong><small>${esc(first.date)} → ${esc(last.date)}</small></div><span class="analysis-pill ${change>=0?'good':'bad'}">${change>=0?'+':''}${num(change,2)}%</span></div>
      <svg class="analysis-price-chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Biểu đồ giá ${esc(symbol)}"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="3" vector-effect="non-scaling-stroke"/></svg>
      <div class="chart-range"><span>Low: ${num(min,2)}</span><span>High: ${num(max,2)}</span></div>
    </div>`;
  }

  function renderTechnical(t, chartRows){
    const i=t.indicators||{};
    return `
      <div class="analysis-section-head"><div><p class="eyebrow">TECHNICAL ANALYSIS</p><h2>Phân tích kỹ thuật</h2></div><div>${pill(t.trend||'SIDEWAY',trendTone(t.trend))}</div></div>
      <div class="data-grid analysis-kpi-grid">
        ${dataCell('Giá gần nhất', num(t.last_price,2))}
        ${dataCell('Ngày dữ liệu', esc(t.last_date||'N/A'))}
        ${dataCell('RSI (14)', num(i.rsi,2), Number(i.rsi)>70?'Vùng quá mua':Number(i.rsi)<30?'Vùng quá bán':'Vùng trung tính')}
        ${dataCell('MACD', num(i.macd,3))}
        ${dataCell('MACD Signal', num(i.macd_signal,3))}
        ${dataCell('MACD Histogram', num(i.macd_hist,3))}
      </div>
      ${renderMiniChart(chartRows)}
      <div class="analysis-two-col">
        <section class="analysis-subpanel">
          <h3>Xu hướng & đường trung bình</h3>
          <table class="analysis-table"><tbody>
            <tr><td>EMA20</td><td>${num(i.ema20,2)}</td></tr>
            <tr><td>EMA50</td><td>${num(i.ema50,2)}</td></tr>
            <tr><td>EMA200</td><td>${num(i.ema200,2)}</td></tr>
            <tr><td>Volume MA20</td><td>${num(i.volume_ma20,0)}</td></tr>
          </tbody></table>
        </section>
        <section class="analysis-subpanel">
          <h3>Bollinger Bands</h3>
          <table class="analysis-table"><tbody>
            <tr><td>Upper Band</td><td>${num(i.bb_upper,2)}</td></tr>
            <tr><td>Middle Band</td><td>${num(i.bb_mid,2)}</td></tr>
            <tr><td>Lower Band</td><td>${num(i.bb_lower,2)}</td></tr>
            <tr><td>Vị trí giá</td><td>${t.last_price!=null&&i.bb_upper!=null&&Number(t.last_price)>Number(i.bb_upper)?pill('Trên Upper','warn'):t.last_price!=null&&i.bb_lower!=null&&Number(t.last_price)<Number(i.bb_lower)?pill('Dưới Lower','warn'):pill('Trong dải','good')}</td></tr>
          </tbody></table>
        </section>
      </div>
      <section class="analysis-subpanel signal-section"><h3>Tín hiệu kích hoạt hiện tại</h3>${renderSignals(t.signals)}</section>`;
  }

  function renderIncomeTable(income=[]){
    if(!income.length) return '<div class="empty-state">Chưa lấy được dữ liệu kết quả kinh doanh.</div>';
    return `<div class="analysis-table-wrap"><table class="analysis-table wide"><thead><tr><th>Kỳ</th><th>Doanh thu</th><th>LN gộp</th><th>LN ròng</th><th>DT YoY</th><th>LN YoY</th></tr></thead><tbody>${income.map(r=>`<tr><td>${esc(r.period)}</td><td>${esc(money(r.revenue,r.revenue_formatted))}</td><td>${esc(money(r.gross_profit,r.gross_profit_formatted))}</td><td>${esc(money(r.net_income,r.net_income_formatted))}</td><td>${pct(r.revenue_growth_yoy)}</td><td>${pct(r.profit_growth_yoy)}</td></tr>`).join('')}</tbody></table></div>`;
  }

  function renderFundamental(f){
    const r=(f.ratios||[])[0]||{};
    const score=f.score||{};
    const b=f.balance||{};
    return `
      <div class="analysis-section-head"><div><p class="eyebrow">FUNDAMENTAL ANALYSIS</p><h2>Phân tích cơ bản</h2></div><div>${pill(`Grade ${score.grade||'N/A'}`,scoreTone(score.score))}</div></div>
      <div class="data-grid analysis-kpi-grid">
        ${dataCell('P/E', num(r.pe,2),'lần')}
        ${dataCell('P/B', num(r.pb,2),'lần')}
        ${dataCell('ROE', pct(r.roe), 'Khả năng sinh lời trên VCSH')}
        ${dataCell('ROA', pct(r.roa), 'Khả năng sinh lời trên tài sản')}
        ${dataCell('EPS', num(r.eps,0),'đồng/cp')}
        ${dataCell('Debt / Equity', num(r.debt_equity,2),'lần')}
        ${dataCell('Net Margin', pct(r.net_margin),'Biên lợi nhuận ròng')}
        ${dataCell('Điểm cơ bản', `${num(score.score,0)}/100`, esc(score.grade||'N/A'))}
      </div>
      <section class="analysis-subpanel"><h3>Bảng cân đối kế toán</h3><table class="analysis-table"><tbody>
          <tr><td>Năm / kỳ</td><td>${esc(b.year||'N/A')}</td></tr>
          <tr><td>Tổng tài sản</td><td>${esc(money(b.total_assets,b.total_assets_formatted))}</td></tr>
          <tr><td>Tổng nợ</td><td>${esc(money(b.total_debt,b.total_debt_formatted))}</td></tr>
          <tr><td>Vốn chủ sở hữu</td><td>${esc(money(b.equity,b.equity_formatted))}</td></tr>
          <tr><td>Tiền & tương đương tiền</td><td>${esc(money(b.cash,b.cash_formatted))}</td></tr>
        </tbody></table></section>
      <section class="analysis-subpanel"><h3>Kết quả kinh doanh các kỳ gần nhất</h3>${renderIncomeTable(f.income||[])}</section>`;
  }

  function renderOverview(t,f,row,monitor){
    const r=(f.ratios||[])[0]||{};
    const score=f.score||{};
    const finalScore=row.final_score ?? row.screening_score;
    const monitorData=(monitor&&monitor.success)?monitor:null;
    return `
      <div class="analysis-section-head"><div><p class="eyebrow">OVERVIEW</p><h2>${esc(symbol)} — Tổng quan phân tích</h2></div><div>${pill(t.trend||'SIDEWAY',trendTone(t.trend))}</div></div>
      <div class="data-grid">
        ${dataCell('Giá gần nhất',num(t.last_price,2),t.last_date||'')}
        ${dataCell('Final Score',finalScore==null?'N/A':`${num(finalScore,1)}/100`,row.grade?`Grade ${row.grade}`:'')}
        ${dataCell('Fundamental Score',score.score==null?'N/A':`${num(score.score,0)}/100`,score.grade?`Grade ${score.grade}`:'')}
        ${dataCell('RSI',num(t.indicators?.rsi,2))}
        ${dataCell('P/E',num(r.pe,2),'lần')}
        ${dataCell('ROE',pct(r.roe))}
      </div>
      <div class="analysis-two-col overview-lower">
        <section class="analysis-summary-box"><h3>Đánh giá cơ bản</h3><p>${esc(score.summary_vi||'Chưa có đánh giá cơ bản.')}</p></section>
        <section class="analysis-summary-box"><h3>Theo dõi 5 phiên</h3>${monitorData?`<p>Return 5 phiên: <strong>${pct(monitorData.return_5d,2)}</strong></p><p>RS vs VNIndex: <strong>${pct(monitorData.relative_strength_vnindex,2)}</strong></p><p>Action: ${pill(monitorData.system_action||'WATCH','warn')}</p>`:'<p>Chưa đủ snapshot 5 phiên hoặc chưa chạy EOD monitor.</p>'}</section>
      </div>`;
  }

  function renderMonitor(m){
    if(!m || !m.success) return '<div class="empty-state">Chưa đủ 5 phiên snapshot. Chạy <code>python -m monitoring.run_eod</code> sau mỗi phiên để tích lũy dữ liệu.</div>';
    const fields=[
      ['Return 5 phiên',pct(m.return_5d,2)],
      ['Volatility 5 phiên',pct(m.volatility_5d,2)],
      ['Max Drawdown',pct(m.max_drawdown_5d,2)],
      ['RS vs VNIndex',pct(m.relative_strength_vnindex,2)],
      ['RS vs VN30',pct(m.relative_strength_vn30,2)],
      ['Technical Score thay đổi',num(m.technical_score_change,1)],
      ['Final Score',num(m.final_score,1)],
      ['System Action',pill(m.system_action||'WATCH','warn')],
    ];
    return `<div class="analysis-section-head"><div><p class="eyebrow">5-SESSION MONITOR</p><h2>Theo dõi 5 phiên giao dịch</h2></div></div><div class="data-grid">${fields.map(([a,b])=>dataCell(a,b)).join('')}</div>`;
  }

  function renderAI(){
    $('tab-ai').innerHTML=`<div class="analysis-section-head"><div><p class="eyebrow">OLLAMA</p><h2>AI Analysis</h2><p class="subtle compact">Dữ liệu kỹ thuật/cơ bản tải độc lập. Chỉ gọi Ollama khi bạn yêu cầu.</p></div></div><button id="runAI" class="button">Tạo AI Analysis</button><div id="aiOut" class="analysis-ai-output"><p>Chưa chạy AI Analysis.</p></div>`;
    $('runAI')?.addEventListener('click',async e=>{
      const btn=e.currentTarget,out=$('aiOut');btn.disabled=true;out.innerHTML='<p>Đang gọi Ollama...</p>';
      try{
        const full=await StockApp.api(`/api/analysis/${encodeURIComponent(symbol)}?type=full`);
        const text=full.comprehensive_analysis||full.llm_analysis||full.error||JSON.stringify(full,null,2);
        out.innerHTML=`<pre class="analysis-output">${esc(text)}</pre>`;
      }catch(err){out.innerHTML=`<div class="empty-state error">${esc(err.message)}<br>Nếu liên quan Ollama, chạy <code>ollama serve</code>.</div>`;}finally{btn.disabled=false;}
    });
  }

  async function load(){
    setLoading(true); status('');
    try{
      // One unified backend request prevents duplicate OHLCV downloads and computes
      // scores for the ticker being viewed instead of depending on latest screening.
      const bundle=await StockApp.api(`/api/analysis-data/${encodeURIComponent(symbol)}?chart_days=90`);
      latestBundle = bundle;
      const t=bundle.technical||{};
      const f=bundle.fundamental||{};
      const scoring=bundle.scoring||{};
      const components=scoring.components||{};
      const row={
        final_score: scoring.final_score,
        screening_score: scoring.final_score,
        fundamental_score: components.fundamental?.score ?? f.score?.score,
        valuation_score: components.valuation?.score,
        technical_score: components.technical?.score,
        risk_score: components.risk?.score,
        grade: scoring.grade,
        eligible: scoring.eligible,
        action: scoring.action,
      };
      const m=bundle.monitor||null;
      const chartRows=bundle.chart||[];

      const componentScores=[
        ['Final Score',row.final_score??row.screening_score,'Điểm tổng hợp'],
        ['Fundamental',row.fundamental_score,'Chất lượng doanh nghiệp'],
        ['Valuation',row.valuation_score,'Định giá'],
        ['Technical',row.technical_score,'Xu hướng & động lượng'],
        ['Risk',row.risk_score,'Cao = an toàn hơn'],
      ];
      $('scoreStrip').innerHTML=componentScores.map(([label,value,help])=>metricCard(label,value==null?'N/A':num(value,1),help,scoreTone(value))).join('');

      $('tab-overview').innerHTML=renderOverview(t,f,row,m);
      $('tab-technical').innerHTML=bundle.technical?renderTechnical(t,chartRows):`<div class="empty-state error">${esc(bundle.errors?.technical||'Technical chưa tải được')}</div>`;
      $('tab-fundamental').innerHTML=bundle.fundamental?renderFundamental(f):`<div class="empty-state error">${esc(bundle.errors?.fundamental||'Fundamental chưa tải được')}</div>`;
      $('tab-monitor').innerHTML=renderMonitor(m);
      renderAI();

      const failures=[];
      if(bundle.errors?.technical) failures.push(`kỹ thuật: ${bundle.errors.technical}`);
      if(bundle.errors?.fundamental) failures.push(`cơ bản: ${bundle.errors.fundamental}`);
      if(bundle.errors?.scoring) failures.push(`chấm điểm: ${bundle.errors.scoring}`);
      // Monitor can legitimately be unavailable until 5 EOD snapshots exist, so it
      // should not make the whole Analysis page look broken.
      if(failures.length) status(`Một phần dữ liệu chưa tải được — ${failures.join(' | ')}`,true);
      else status('');
    }catch(err){
      status(`Không thể tải phân tích ${symbol}: ${err.message}`,true);
    }finally{setLoading(false);}
  }

  $('analysisSymbolForm')?.addEventListener('submit',(e)=>{
    e.preventDefault();
    const next=String($('analysisSymbolInput')?.value||'').trim().toUpperCase();
    if(!/^[A-Z0-9._-]{1,12}$/.test(next)){StockApp.toast('Mã cổ phiếu không hợp lệ',true);return;}
    window.location.href=`/analysis/${encodeURIComponent(next)}`;
  });
  $('refreshAnalysis')?.addEventListener('click',load);
  function snapshotFromBundle(bundle){
    if(!bundle?.technical) return null;
    const t=bundle.technical||{};
    const i=t.indicators||{};
    const scoring=bundle.scoring||{};
    const c=scoring.components||{};
    const chart=Array.isArray(bundle.chart)?bundle.chart:[];
    const bar=chart.length?chart[chart.length-1]:{};
    const score=(name)=>c?.[name]?.score ?? null;
    const tradeDate=String(t.last_date||bar.date||'').slice(0,10);
    if(!tradeDate) return null;
    return {
      trade_date: tradeDate,
      open: bar.open ?? null, high: bar.high ?? null, low: bar.low ?? null,
      close: t.last_price ?? bar.close ?? null, volume: bar.volume ?? null,
      rsi: i.rsi ?? null, macd: i.macd ?? null, macd_signal: i.macd_signal ?? null,
      ema20: i.ema20 ?? null, ema50: i.ema50 ?? null, ema200: i.ema200 ?? null,
      technical_score: score('technical'), fundamental_score: score('fundamental'),
      valuation_score: score('valuation'), risk_score: score('risk'),
      final_score: scoring.final_score ?? null,
      captured_at: new Date().toISOString()
    };
  }

  $('addCurrentWatch')?.addEventListener('click',async()=>{
    try{
      const snapshot=snapshotFromBundle(latestBundle);
      await StockApp.api('/api/watchlist',{method:'POST',body:JSON.stringify({symbol,snapshot})});
      StockApp.toast(snapshot ? `${symbol} đã vào Watchlist và lưu dữ liệu phân tích mới nhất` : `${symbol} đã vào Watchlist; chạy EOD để có giá/score`);
    }catch(e){StockApp.toast(e.message,true);}
  });
  load();
})();
