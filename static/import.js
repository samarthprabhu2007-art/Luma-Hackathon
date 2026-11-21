(() => {
  'use strict';
  const intents = {
    'Review borrower record': 'Paused',
    'Schedule callback': 'Scheduled',
    'Check promise': 'Scheduled',
    'Reconcile payment claim': 'Paused',
    'Human hardship review': 'Human review',
    'Will pay now': 'Paused',
    'No response': 'Paused'
  };
  const columns = {
    id: /^(?:loan|borrower|account)(?: number| no| id)$|^id$/,
    name: /^(?:borrower |customer )?name$/,
    balance: /^(?:(?:outstanding|remaining|due|overdue) )?(?:amount|balance)(?: due)?$/,
    promisedAmount: /^promis(?:e|ed) amount$/,
    due: /^(?:promise[d]?|callback|follow up|due)(?: date| time)?$/,
    owner: /^(?:owner|assigned to|staff(?: member)?|officer)$/,
    intent: /^(?:intent|action|follow up action|payment claim|outcome)$/
  };
  const el = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  };
  function button(label, fn, cls) {
    const b = el('button', label, cls);
    b.type = 'button'; b.addEventListener('click', fn); return b;
  }
  function field(label, control) {
    const wrap = el('label', undefined, 'li-field');
    wrap.append(el('span', label), control);
    return wrap;
  }
  function input(value = '', type = 'text') {
    const n = el('input'); n.type = type; n.value = value; return n;
  }
  function select(options, current) {
    const n = el('select');
    options.forEach(([v, title]) => n.add(new Option(title, v)));
    if (current) n.value = current;
    return n;
  }
  function amount(raw) {
    const cleaned = String(raw || '').replace(/^(?:INR|Rs\.?|₹)\s*/i,'').replaceAll(',','').trim();
    return /^\d+(?:\.\d{1,2})?$/.test(cleaned) ? cleaned : '';
  }
  function interpret(header) {
    const h = header.toLowerCase().replace(/[^a-z0-9]+/g,' ').replace(/\b(?:inr|rs)\b/g,'').trim();
    return Object.keys(columns).find(k => columns[k].test(h));
  }
  function extract(text) {
    const groups = [];
    for (const m of text.matchAll(/<table\b[^>]*>([\s\S]*?)<\/table>/gi)) {
      const grid = [...m[1].matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)].map(row =>
        [...row[1].matchAll(/<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/gi)].map(c =>
          c[1].replace(/<[^>]+>/g,' ').replace(/&amp;/g,'&').replace(/&nbsp;/g,' ').trim()));
      groups.push(grid);
    }
    let grid = [];
    for (const line of text.split(/\r?\n/)) {
      if (line.includes('|') || line.includes('\t')) {
        const cells = line.trim().replace(/^\||\|$/g,'').split(line.includes('|') ? '|' : '\t').map(x => x.trim());
        if (!cells.every(c => /^:?-+:?$/.test(c))) grid.push(cells);
      } else if (grid.length) { groups.push(grid); grid = []; }
    }
    groups.push(grid);
    const result = [];
    groups.forEach(([headers, ...rows]) => {
      if (!headers) return;
      const keys = headers.map(interpret);
      if (!keys.includes('id') && !keys.includes('name')) return;
      rows.forEach(row => {
        const rec = {};
        keys.forEach((k,i) => { if(k) rec[k] = row[i] || ''; });
        if (rec.id || rec.name) result.push(rec);
      });
    });
    if (!result.length) {
      let note = {};
      for (const line of text.split(/\r?\n/)) {
        const pair = line.match(/^\s*[-*# ]*([^:]{1,45}):\s*(.+)$/);
        if (!pair) continue;
        const key = interpret(pair[1]);
        if (!key) continue;
        if (key === 'id' && note.id) { result.push(note); note = {}; }
        note[key] = pair[2].replace(/^\*+|\*+$/g,'').trim();
      }
      if (Object.keys(note).length) result.push(note);
    }
    if (!result.length) {
      const lines = text.trim().split(/\r?\n/);
      const header = lines.findIndex(line => /^\s*loan\s+id\s+(?:borrower\s+)?name\s+(?:amount|balance)\s*$/i.test(line));
      if (header !== -1) {
        for (const line of lines.slice(header + 1)) {
          const row = line.trim().match(/^(\S+)\s+(.+?)\s+(?:₹\s*)?([\d,]+(?:\.\d{1,2})?)$/u);
          if (row) result.push({id: row[1], name: row[2], balance: amount(row[3])});
        }
      }
    }
    return result;
  }
  async function saveSource(id,{file}) {
    const res=await fetch("/api/book/scans/"+encodeURIComponent(id),{method:"PUT",headers:{"Content-Type":file.type},body:file});
    if(!res.ok)throw Error("Could not save the source scan.");
  }
  window.openImportedScan=id=>window.open("/api/book/scans/"+encodeURIComponent(id),"_blank","noopener");
  function preview(file, url) {
    const n = el(file.type === 'application/pdf' ? 'iframe' : 'img',undefined,'li-preview');
    n.title = 'Original source scan'; n.alt = n.title; n.src = url; return n;
  }
  window.openListImport = function(onConfirm, borrower) {
    const dlg = el('dialog',undefined,'li-dialog');
    dlg.setAttribute('aria-labelledby','li-title');
    const header = el('header',undefined,'li-header');
    const h = el('h2','Add a borrower list'); h.id = 'li-title';
    if(borrower) h.textContent='Handwritten log ? '+borrower.name;
    header.append(h,button('Close',()=>dlg.close(),'li-btn'));
    const body = el('div',undefined,'li-body'), foot = el('footer',undefined,'li-footer');
    const msg = el('p','','li-message'); msg.setAttribute('role','status');
    const abort = new AbortController();
    let file, url, raw, busy = false;
    dlg.append(header,body,msg,foot); document.body.append(dlg); dlg.showModal();
    dlg.addEventListener('close',()=>{abort.abort();if(url) URL.revokeObjectURL(url);dlg.remove();});
    dlg.addEventListener('cancel',ev=>{if(busy) ev.preventDefault();});
    const chooser = input('', 'file'); chooser.accept = 'image/png,image/jpeg,application/pdf';
    const camera = input('', 'file');
    camera.accept = 'image/jpeg,image/png';
    camera.setAttribute('capture', 'environment');
    camera.hidden = true;
    const takePhoto = button('Take photo', () => camera.click(), 'li-btn');
    const attachment = el('p', '', 'li-attachment');
    attachment.setAttribute('aria-live', 'polite');
    let selectedFile;
    function choose(source, other) {
      if (!source.files.length) return;
      selectedFile = source.files[0];
      other.value = '';
      attachment.textContent = selectedFile.name;
      msg.textContent = '';
    }
    camera.onchange = () => choose(camera, chooser);
    chooser.onchange = () => choose(chooser, camera);
    const lang = select([['en-IN','English'],['kn-IN','Kannada'],['hi-IN','Hindi'],['ta-IN','Tamil'],['te-IN','Telugu']]);
    const staff = input(), date = input('', 'date');
    const now = new Date(); date.value = [now.getFullYear(), String(now.getMonth()+1).padStart(2,'0'),String(now.getDate()).padStart(2,'0')].join('-');
    body.append(el('p','Upload a synthetic borrower list or meeting note. Sarvam reads the scan so you can check each entry before adding it.'),takePhoto,camera,attachment,field('Or choose a file · PNG, JPEG or PDF · up to 8 MB',chooser),field('Document language',lang),field('Staff member who recorded the list',staff),field('Record date',date));
    const read = button('Read with Sarvam',async()=>{
      file = selectedFile;
      if (!file || !['image/png','image/jpeg','application/pdf'].includes(file.type) || file.size>8*1024*1024 || !file.size) {msg.textContent='Choose a PNG, JPEG or PDF under 8 MB.';return;}
      if(!staff.value.trim() || !date.value){msg.textContent='Enter the staff member and record date.';return;}
      read.disabled=true; chooser.disabled=true;takePhoto.disabled=true;lang.disabled=true;staff.disabled=true;date.disabled=true;
      msg.textContent='Reading the scan with Sarvam…';
      try {
        const res = await fetch('/api/lender/ocr?language='+encodeURIComponent(lang.value),{method:'POST',body:file,headers:{'Content-Type':file.type},signal:abort.signal});
        const data = await res.json();
        if(!res.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Sarvam could not read this scan.');
        raw = data.text || ''; if (!raw.trim()) throw Error('No text was detected. Try a clearer scan.');
        url = URL.createObjectURL(file);
        if(!borrower){ review(); return; }
        h.textContent='Review handwritten log ? '+borrower.name;
        const editor=el('textarea'); editor.value=raw;editor.rows=10;editor.style.width='100%';
        body.replaceChildren(preview(file,url),field('Correct the transcription before saving',editor));
        foot.replaceChildren();msg.textContent='Check names, amounts and dates against the source.';
        const scan=crypto.randomUUID();
        const save=button('Confirm and save log',async()=>{
          if(!editor.value.trim())return;
          save.disabled=true;
          try{
            await saveSource(scan,{file});
            const res=await fetch('/api/book/'+encodeURIComponent(borrower.id)+'/logs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:editor.value.trim(),staff:staff.value.trim(),scan})});
            if(!res.ok)throw Error('Could not attach the log.');
            await QueueStore.refresh();dlg.close();
          }catch(e){msg.textContent=e.message;save.disabled=false;}
        },'li-primary');foot.append(save);
      } catch (e) {
        if(abort.signal.aborted) return;
        msg.textContent=e.message; read.disabled=false; chooser.disabled=false;takePhoto.disabled=false;lang.disabled=false;staff.disabled=false;date.disabled=false;
      }
    },'li-primary'); foot.append(read);
    function review() {
      body.replaceChildren(); foot.replaceChildren(); h.textContent='Review extracted list';
      msg.textContent='Field confidence is unavailable. Check every entry against the original.';
      const layout=el('div',undefined,'li-layout'), source=el('section'), entries=el('section');
      const details=el('details');details.append(el('summary','Extracted text'),el('pre',raw));
      source.append(el('h3','Original scan'),preview(file,url),details);
      const cards=el('div'); const records=[];
      function addRow(data={}) {
        const card=el('fieldset',undefined,'li-card'), legend=el('legend','Borrower');
        const id=input(data.id), name=input(data.name), bal=input(amount(data.balance),'number'), promise=input(amount(data.promisedAmount),'number'), due=input(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(data.due || '') ? data.due : '', 'datetime-local'), owner=input(data.owner || staff.value.trim());
        [bal,promise].forEach(n=>{n.min=0; n.step='.01';});
        const action=select(Object.keys(intents).map(k=>[k,k]),Object.hasOwn(intents,data.intent)?data.intent:'Review borrower record');
        const remove=button('Remove entry',()=>{records.splice(records.indexOf(rec),1);card.remove();},'li-btn');
        const rec={id,name,bal,promise,due,owner,action};
        const fields=el('div',undefined,'li-grid');
        fields.append(field('Loan ID',id),field('Borrower name',name),field('Outstanding balance (₹)',bal),field('Promised amount (₹)',promise),field('Confirmed intent',action),field('Follow-up owner',owner),field('Follow-up due date and time',due));
        card.append(legend,fields);
        if(data.due) card.append(el('p','Date read from scan: '+data.due));
        if(data.intent) card.append(el('p','Extracted outcome: '+data.intent));
        card.append(remove); cards.append(card);records.push(rec);
      }
      const rows=extract(raw);
      (rows.length ? rows : [{}]).forEach(addRow);
      entries.append(el('h3','Borrower entries'),cards,button('Add another entry',()=>addRow(),'li-btn'));
      layout.append(source,entries); body.append(layout);
      const check=input('','checkbox');
      foot.append(field('I checked these entries against the scan',check));
      const confirm=button('Confirm and add', async()=>{
        if(busy) return;
        if(!check.checked || !records.length){msg.textContent='Review at least one entry and check the confirmation box.';return;}
        const ids=new Set(), result=[], sourceImageId=crypto.randomUUID();
        for(const r of records){
          const id=r.id.value.trim(), name=r.name.value.trim(), owner=r.owner.value.trim(), action=r.action.value, due=r.due.value.trim();
          if(!id || !name || !owner || !r.bal.value || !r.bal.validity.valid || !r.promise.validity.valid || ids.has(id.toLowerCase())) {msg.textContent='Each entry needs a unique loan ID, name, owner and valid outstanding balance.';return;}
          if(!due){msg.textContent='Set the follow-up due date and time. For callbacks, use the borrower’s chosen time.';r.due.focus();return;}
          ids.add(id.toLowerCase());result.push({id,name,balance:Number(r.bal.value),promisedAmount:r.promise.value?Number(r.promise.value):null,action,status:intents[action],owner,due,reason:'Staff-confirmed '+action.toLowerCase()+'.',score:null,sourceImageId,sourceDate:date.value,sourceStaff:staff.value.trim()});
        }
        busy=true;confirm.disabled=true;header.querySelector('button').disabled=true;
        try{await saveSource(sourceImageId,{file,text:raw,date:date.value,staff:staff.value.trim()});await onConfirm(result);dlg.close();}
        catch(e){msg.textContent=e.message || 'Could not save this list on the device.';}
        finally{busy=false;confirm.disabled=false;header.querySelector('button').disabled=false;}
      },'li-primary');foot.append(confirm);
    }
  };
})();
