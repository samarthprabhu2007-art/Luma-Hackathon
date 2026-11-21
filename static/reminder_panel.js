/* Sarvam reminder + Cashfree pay link. Used under a borrower's detail and on the Reminder studio page.
   Built with DOM APIs (textContent only) so borrower fields stay plain text. */
(function () {
  const LANGS = [['hi', 'Hindi'], ['kn', 'Kannada'], ['ta', 'Tamil'], ['te', 'Telugu']];
  const FROM_BOOK = {'hi-IN': 'hi', 'kn-IN': 'kn', 'ta-IN': 'ta', 'te-IN': 'te'};
  const state = new Map(); // row id -> inputs, result and live payment status
  const timers = new Map(); // row id -> interval id
  const money = n => new Intl.NumberFormat('en-IN', {style: 'currency', currency: 'INR', maximumFractionDigits: 2}).format(n);
  const live = id => document.querySelector('.rem[data-id="' + CSS.escape(id) + '"]');

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function stateFor(row) {
    if (!state.has(row.id)) {
      state.set(row.id, {lang: FROM_BOOK[row.language] || 'hi', amount: row.balance || '', phone: '9999999999', name: row.name || ''});
    }
    return state.get(row.id);
  }

  function setStatus(box, s) {
    const node = box.querySelector('.stamp');
    if (!node) return;
    node.textContent = (s.status || '-').replace('_', ' ') + (s.paid ? ' · ' + money(s.paid) : '');
    node.dataset.state = s.status || '';
  }

  function poll(row) {
    clearInterval(timers.get(row.id));
    const s = stateFor(row);
    const started = Date.now();
    const timer = setInterval(async () => {
      try {
        const res = await fetch('/api/status/' + encodeURIComponent(s.result.link_id), {cache: 'no-store'});
        const data = await res.json();
        s.status = data.link_status;
        s.paid = data.amount_paid || 0;
        const box = live(row.id);
        if (box) setStatus(box, s);
        if (['PAID', 'EXPIRED', 'CANCELLED'].includes(s.status) || Date.now() - started > 600000) clearInterval(timer);
      } catch (_) { /* keep polling */ }
    }, 3000);
    timers.set(row.id, timer);
  }

  async function send(row, button) {
    const s = stateFor(row);
    s.error = ''; s.result = null;
    if (!String(s.name).trim()) { s.error = 'Enter the borrower\'s name first.'; const b = live(row.id); if (b) paint(b, row); return; }
    button.disabled = true; button.textContent = 'Working...';
    try {
      const res = await fetch('/api/remind', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: String(s.name).trim(), phone: String(s.phone).trim(), amount: Number(s.amount),
                              language: s.lang, borrower_id: row.studio ? null : row.id}),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
      s.result = data; s.status = data.link_status; s.paid = 0;
      poll(row);
    } catch (err) {
      s.error = String(err.message || err);
    }
    const box = live(row.id);
    if (box) paint(box, row);
  }

  function field(label, input) {
    const wrap = el('label', 'rem-field');
    wrap.append(el('span', '', label), input);
    return wrap;
  }

  function paint(box, row) {
    const s = stateFor(row);
    box.replaceChildren();
    if (!row.studio) box.append(el('h3', 'rem-title', 'Remind and collect'));

    const lang = el('select');
    for (const [code, name] of LANGS) { const o = el('option', '', name); o.value = code; lang.append(o); }
    lang.value = s.lang; lang.onchange = () => { s.lang = lang.value; };
    const amount = el('input'); amount.type = 'number'; amount.min = '1'; amount.value = s.amount; amount.oninput = () => { s.amount = amount.value; };
    const phone = el('input'); phone.inputMode = 'numeric'; phone.maxLength = 10; phone.value = s.phone; phone.oninput = () => { s.phone = phone.value; };
    const form = el('div', 'rem-form');
    if (row.studio) {
      const name = el('input'); name.value = s.name; name.placeholder = 'Borrower name'; name.oninput = () => { s.name = name.value; };
      form.append(field('Borrower name', name));
    }
    form.append(field('Language', lang), field('Amount (INR)', amount), field('Phone, sandbox test number', phone));
    const go = el('button', 'primary', 'Send reminder and create pay link');
    go.type = 'button'; go.onclick = () => send(row, go);
    box.append(form, go);

    if (s.error) box.append(el('p', 'rem-error', s.error));
    const r = s.result;
    if (!r) return;

    const steps = el('ul', 'rem-steps');
    const add = (text, ok) => steps.append(el('li', ok ? 'ok' : 'warn', text));
    add(r.text_source === 'sarvam' ? 'Translated by Sarvam' : 'Used the built-in message', r.text_source === 'sarvam');
    add(r.audio_b64 ? 'Voiced by Sarvam' : 'No audio, text only', !!r.audio_b64);
    add('Pay link created by Cashfree', true);
    for (const n of r.notes || []) add(n, false);
    box.append(steps, el('p', 'rem-msg', r.text));

    if (r.audio_b64) {
      const audio = el('audio'); audio.controls = true; audio.src = 'data:audio/wav;base64,' + r.audio_b64;
      box.append(audio);
    }
    const pay = el('div', 'rem-pay');
    const info = el('div', 'rem-link');
    const link = el('a', '', r.link_url); link.href = r.link_url; link.target = '_blank'; link.rel = 'noopener';
    info.append(el('small', 'muted', 'Pay link'), link, el('span', 'stamp', '-'));
    if (window.QRCode) {
      const qr = el('div', 'rem-qr'); pay.append(qr);
      new window.QRCode(qr, {text: r.link_url, width: 112, height: 112});
    }
    pay.append(info);
    box.append(pay, el('p', 'muted', 'Sandbox only, no real money. Test UPI: success@upi'));
    setStatus(box, s);
  }

  window.addReminderPanel = function (panel, row) {
    const box = el('section', 'rem');
    box.dataset.id = row.id;
    if (row.studio) box.classList.add('studio-form');
    panel.append(box);
    paint(box, row);
  };
})();
