window.StockApp = {
  async api(url, options={}) {
    const opts = {...options};
    opts.headers = {'Content-Type':'application/json', ...(opts.headers||{})};
    const res = await fetch(url, opts);
    let payload = {};
    try { payload = await res.json(); } catch (_) {}
    if (!res.ok && res.status !== 207 && res.status !== 409) throw new Error(payload.error || `HTTP ${res.status}`);
    return payload;
  },
  num(value, digits=2) { const n=Number(value); return Number.isFinite(n) ? n.toLocaleString('en-US',{maximumFractionDigits:digits}) : '—'; },
  pct(value) { const n=Number(value); return Number.isFinite(n) ? `${n>=0?'+':''}${n.toFixed(2)}%` : '—'; },
  toast(message, error=false) { const el=document.getElementById('toast'); if(!el)return; el.textContent=message; el.className=`toast${error?' error':''}`; el.hidden=false; setTimeout(()=>el.hidden=true,3200); },
  escape(value) { const div=document.createElement('div'); div.textContent=String(value ?? ''); return div.innerHTML; },
};
