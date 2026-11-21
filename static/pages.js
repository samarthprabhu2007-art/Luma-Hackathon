/* Extra pages: Payments (live pay-link ledger) and Reminder studio.
   lender.js calls setView(page) from the tab buttons; it returns true when this file handled the page. */
(function () {
  const $ = id => document.getElementById(id);
  const DASH = ['main > .mast', '#stats', '.board', '#feedback'];
  const VIEWS = {Payments: 'view-payments', Studio: 'view-studio'};
  const FINAL = ['PAID', 'EXPIRED', 'CANCELLED'];
  const LANG_NAME = {hi: 'Hindi', kn: 'Kannada', ta: 'Tamil', te: 'Telugu'};
  const money = n => new Intl.NumberFormat('en-IN', {style: 'currency', currency: 'INR', maximumFractionDigits: 2}).format(n || 0);
  const status = new Map(); // link id -> {link_status, amount_paid}
  let poller, studioMounted = false;

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function ago(iso) {
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + ' min ago';
    return Math.floor(s / 3600) + ' h ago';
  }

  function stamp(state) {
    const s = el('span', 'stamp', (state || '-').replace('_', ' '));
    s.dataset.state = state || '';
    return s;
  }

  async function refreshStatuses(links) {
    await Promise.all(links.slice(0, 30).map(async l => {
      const known = status.get(l.link_id);
      if (known && FINAL.includes(known.link_status)) return;
      try {
        const res = await fetch('/api/status/' + encodeURIComponent(l.link_id), {cache: 'no-store'});
        if (res.ok) { const d = await res.json(); status.set(l.link_id, {link_status: d.link_status, amount_paid: d.amount_paid || 0}); }
      } catch (_) { /* leave the last known status */ }
    }));
  }

  function drawPayments(links) {
    const rows = links.map(l => ({l, s: status.get(l.link_id) || {link_status: null, amount_paid: 0}}));
    const sum = (f) => rows.filter(f).length;
    const received = rows.reduce((n, r) => n + (Number(r.s.amount_paid) || 0), 0);
    const cells = [['Links sent', rows.length], ['Received', money(received)],
      ['Paid in full', sum(r => r.s.link_status === 'PAID')],
      ['Part paid', sum(r => r.s.link_status === 'PARTIALLY_PAID')],
      ['Waiting', sum(r => r.s.link_status === 'ACTIVE')]];
    $('pay-summary').replaceChildren(...cells.map(([k, v]) => { const c = el('div', 'cell'); c.append(el('span', 'k', k), el('b', 'v', String(v))); return c; }));
    $('pay-empty').hidden = rows.length > 0;
    $('pay-table').hidden = rows.length === 0;
    $('pay-table').tBodies[0].replaceChildren(...rows.map(({l, s}) => {
      const tr = el('tr');
      const who = el('td'); who.append(el('strong', '', l.name), el('small', 'muted', l.borrower_id || 'Reminder studio'));
      const open = el('a', 'quiet-link', 'Open link'); open.href = l.link_url; open.target = '_blank'; open.rel = 'noopener';
      const act = el('td'); act.append(open);
      const st = el('td'); st.append(stamp(s.link_status));
      tr.append(who, el('td', '', LANG_NAME[l.language] || l.language), el('td', 'num', money(l.amount)),
        el('td', 'num', s.amount_paid ? money(s.amount_paid) : '-'), st, el('td', 'muted', ago(l.created_at)), act);
      return tr;
    }));
  }

  async function loadPayments() {
    try {
      const res = await fetch('/api/links', {cache: 'no-store'});
      const links = await res.json();
      drawPayments(links);
      await refreshStatuses(links);
      drawPayments(links);
    } catch (_) { /* server restarting; try again on the next tick */ }
  }

  function mountStudio() {
    if (studioMounted) return;
    studioMounted = true;
    window.addReminderPanel($('studio-mount'), {id: 'studio', studio: true, name: '', balance: 500});
  }

  window.setView = function (page) {
    const extra = VIEWS[page];
    for (const sel of DASH) document.querySelectorAll(sel).forEach(n => { n.hidden = !!extra; });
    for (const id of Object.values(VIEWS)) $(id).hidden = id !== extra;
    clearInterval(poller);
    if (page === 'Payments') { $('crumb').textContent = 'Payments'; loadPayments(); poller = setInterval(loadPayments, 5000); }
    if (page === 'Studio') { $('crumb').textContent = 'Reminder studio'; mountStudio(); }
    return !!extra;
  };
})();
