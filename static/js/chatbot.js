(()=>{
  const bubble=document.getElementById('chatBubble');
  const panel=document.getElementById('chatPanel');
  const close=document.getElementById('chatClose');
  const form=document.getElementById('chatForm');
  const input=document.getElementById('chatInput');
  const messages=document.getElementById('chatMessages');

  if(!bubble||!panel)return;

  const openChat=()=>{
    panel.hidden=false;
    panel.setAttribute('aria-hidden','false');
    bubble.setAttribute('aria-expanded','true');
    input?.focus();
  };

  const closeChat=()=>{
    panel.hidden=true;
    panel.setAttribute('aria-hidden','true');
    bubble.setAttribute('aria-expanded','false');
    bubble.focus();
  };

  bubble.addEventListener('click',()=>{
    if(panel.hidden) openChat();
    else closeChat();
  });

  close?.addEventListener('click',(event)=>{
    event.preventDefault();
    event.stopPropagation();
    closeChat();
  });

  document.addEventListener('keydown',(event)=>{
    if(event.key==='Escape'&&!panel.hidden) closeChat();
  });

  const add=(text,role)=>{
    const d=document.createElement('div');
    d.className=`chat-msg ${role}`;
    d.textContent=text;
    messages.appendChild(d);
    messages.scrollTop=messages.scrollHeight;
  };

  form?.addEventListener('submit',async e=>{
    e.preventDefault();
    const text=input.value.trim();
    if(!text)return;
    add(text,'user');
    input.value='';
    add('Đang phân tích context...','assistant');
    const placeholder=messages.lastElementChild;
    try{
      const body={message:text,page:document.body.dataset.page||'',symbol:document.body.dataset.symbol||''};
      const r=await StockApp.api('/api/chat',{method:'POST',body:JSON.stringify(body)});
      placeholder.textContent=r.answer||r.error||'Không có phản hồi.';
    }catch(err){
      placeholder.textContent=`Lỗi chatbot: ${err.message}. Kiểm tra Ollama bằng lệnh ollama serve.`;
    }
  });
})();
