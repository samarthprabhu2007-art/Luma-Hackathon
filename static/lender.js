/* Build visible text with DOM APIs so reviewed OCR fields always remain plain text. */
const $ = id => document.getElementById(id);
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}
const money = value => value == null ? 'Pending' : new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:2}).format(value);
const dateText = value => {
  if (!value) return 'Date to confirm';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString('en-IN',{day:'numeric',month:'short',...(String(value).length>10?{hour:'numeric',minute:'2-digit'}:{})});
};
let limit=50;
let page = 'Overview', borrowers = [], selected;
function badge(state) { const b=el('span','badge',state); b.dataset.state=state; return b; }
function detail(row) {
  const panel=$('detail'); panel.replaceChildren(el('small','label','BORROWER DETAIL'));
  if (!row) {panel.append(el('p','empty','Select a borrower to see their follow-up.'));return;}
  const who=el('div','who'), title=el('div');
  title.append(el('h2','',row.name),el('small','muted',[row.id,row.language].filter(Boolean).join(' · ')));
  who.append(el('span','avatar',(row.name||row.id).split(' ').map(s=>s[0]).slice(0,2).join('')),title);
  const log=el('button','primary','Add handwritten log');log.onclick=()=>window.openListImport(null,row);
  const next=el('div','next'); next.append(el('small','label','NEXT FOLLOW-UP'),el('h3','',row.action),el('p','',dateText(row.due)+' · '+(row.owner||'Unassigned')));
  const facts=el('dl'); for(const [key,value] of [['Outstanding',money(row.balance)],['Priority score',row.score??'Unranked'],['Last outcome',row.outcome]]) facts.append(el('dt','',key),el('dd','',value));
  panel.append(who,badge(row.status),log,next,el('small','label','DECISION REASON'),el('p','',row.reason),facts,el('small','label','BORROWER HISTORY'));
  for(const entry of row.history||[]) {const item=el('div','entry');item.append(el('strong','',entry.title),el('small','muted',dateText(entry.at)),el('p','',entry.detail));if(entry.scan){const source=el('button','', 'View scan');source.onclick=()=>window.openImportedScan(entry.scan);item.append(source);}panel.append(item);}
  if(row.sourceImageId && window.openImportedScan){const btn=el('button','','View original scan');btn.onclick=()=>window.openImportedScan(row.sourceImageId);panel.append(btn);}
  if(window.addReminderPanel)window.addReminderPanel(panel,row);
}
function render() {
  $('crumb').textContent=page; $('heading').textContent={Overview:'Collections overview','Follow-ups':'Follow-up schedule',Activity:'Collection activity'}[page];
  $('listTitle').textContent={Overview:'Borrower queue','Follow-ups':'Scheduled tasks',Activity:'Event log'}[page];
  $('source').textContent=({demo:'DEMO BOOK',live:'SHARED BOOK',offline:'QUEUE OFFLINE',connecting:'CONNECTING'})[QueueStore.source];
  const stats=[['Outstanding balance',money(borrowers.reduce((n,r)=>n+(Number(r.balance)||0),0)),'Across the book','₹'],['Eligible borrowers',borrowers.filter(r=>r.status==='Eligible').length,'Ready for outreach','↗'],['Needs attention',borrowers.filter(r=>['Paused','Human review'].includes(r.status)).length,'Reconciliation & hardship','◷']];
  $('stats').replaceChildren(...stats.map(([label,value,caption,icon])=>{const box=el('div','metric'),head=el('div','pair',label);head.append(el('span','symbol',icon));box.append(head,el('b','',value),el('small','',caption));return box;}));
  const query=$('search').value.trim().toLowerCase(), filter=$('status').value;
  const matches=borrowers.filter(r=>(filter==='All statuses'||r.status===filter)&&[r.name,r.id].join(' ').toLowerCase().includes(query));
  let entries=matches.map(row=>({row}));
  if(page==='Follow-ups')entries=entries.filter(({row})=>row.action).sort((a,b)=>(a.row.due||'z').localeCompare(b.row.due||'z'));
  if(page==='Activity')entries=matches.flatMap(row=>(row.history||[]).map(event=>({row,event}))).sort((a,b)=>new Date(b.event.at)-new Date(a.event.at));
  if(!entries.some(e=>e.row.id===selected))selected=entries[0]?.row.id;
  $('count').textContent=entries.length+' '+(page==='Follow-ups'?'tasks':page==='Activity'?'events':'borrowers');
  $('list').replaceChildren(...entries.slice(0,limit).map(({row,event})=>{
    const btn=el('button','row'+(row.id===selected?' active':''));btn.type='button';btn.setAttribute('aria-pressed',String(row.id===selected));
    const first=el('div'),last=el('div','right');
    first.append(el('strong','',event?.title||(page==='Overview'?row.name:row.action)),el('small','muted',page==='Overview'?row.id+' · '+(row.language||'Language pending'):row.name+' · '+(event?dateText(event.at):row.owner)));
    last.append(el('strong','',page==='Overview'?money(row.balance):page==='Follow-ups'?dateText(row.due):''),el('br'),badge(row.status));
    btn.append(el('span','rank',page==='Overview'&&row.score!=null?String(borrowers.indexOf(row)+1).padStart(2,'0'):'·'),first,last);
    btn.onclick=()=>{selected=row.id;render();if(matchMedia('(max-width:800px)').matches)$('detail').scrollIntoView({block:'start'});};return btn;
  }));
  if(entries.length>limit){const more=el('button','row','Show more');more.onclick=()=>{limit+=50;render();};$('list').append(more);}
  if(!entries.length)$('list').append(el('p','empty','No matching records.'));
  detail(matches.find(r=>r.id===selected));
}
document.querySelectorAll('nav button').forEach(btn=>btn.onclick=()=>{document.querySelector('[aria-current]')?.removeAttribute('aria-current');btn.setAttribute('aria-current','page');page=btn.dataset.page;render();});
$('search').oninput=render;$('status').onchange=render;
$('date').textContent=new Date().toLocaleDateString('en-IN',{weekday:'short',day:'numeric',month:'short',year:'numeric'});
$('add').onclick=()=>window.openListImport(async rows=>{const result=await QueueStore.importRows(rows);$('feedback').textContent=result.added+' added · '+result.skipped+' duplicate or incomplete entries skipped.';return result;});
QueueStore.subscribe(rows=>{borrowers=rows;render();});


$('datasetLabel').onkeydown=e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();$('dataset').click();}};
$('dataset').onchange=async e=>{
  const file=e.target.files[0]; if(!file)return;
  $('feedback').textContent='Importing dataset?';
  try{
    const response=await fetch('/api/book/dataset',{method:'POST',body:file});
    const data=await response.json();
    if(!response.ok)throw Error(data.detail);
    await QueueStore.refresh();
    $('feedback').textContent=data.added+' new borrowers imported. Existing loans were preserved.';
  }catch(err){$('feedback').textContent=err.message;}
  e.target.value='';
};
