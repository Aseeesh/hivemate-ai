/* Hivemate chat widget. Embed: <script src="https://API/widget.js" data-key="pk_..." async></script>
   Builds DOM with textContent only (no HTML parsing), so replies cannot inject markup. */
(function () {
  var s = document.currentScript || document.querySelector('script[data-key][src*="widget.js"]');
  if (!s || !s.dataset.key) return;
  var base = new URL(s.src).origin, key = s.dataset.key, accent = s.dataset.color || '#2f6f5e';
  var wa = /^\d{8,15}$/.test(s.dataset.whatsapp || '') ? s.dataset.whatsapp : ''; // optional: lets the visitor carry on in the business's own WhatsApp
  var store = {
    get: function (k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { sessionStorage.setItem(k, v); } catch (e) {} }
  };
  var convKey = 'hivemate:' + key, convId = store.get(convKey) || null, busy = false;

  function el(tag, css, text) {
    var n = document.createElement(tag);
    if (css) n.style.cssText = css;
    if (text) n.textContent = text;
    return n;
  }
  function call(path, body) {
    return fetch(base + path + (body ? '' : '?key=' + encodeURIComponent(key)), body ? {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(Object.assign({ key: key }, body))
    } : undefined).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); });
  }

  var host = el('div', 'position:fixed;right:20px;bottom:20px;z-index:2147483000;font:14px/1.4 system-ui,sans-serif');
  var panel = el('div', 'display:none;flex-direction:column;width:min(360px,calc(100vw - 40px));height:min(520px,calc(100vh - 100px));background:#fff;color:#1b1f1d;border:1px solid #d5dad7;border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.18);overflow:hidden;margin-bottom:12px');
  var head = el('div', 'padding:12px 14px;color:#fff;font-weight:600;background:' + accent, 'Chat with us');
  var log = el('div', 'flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px;background:#f6f8f7');
  log.setAttribute('aria-live', 'polite');
  var form = el('form', 'display:flex;gap:8px;padding:10px;border-top:1px solid #e3e7e5;background:#fff');
  var input = el('input', 'flex:1;padding:9px 10px;border:1px solid #c6ccc9;border-radius:8px;font:inherit;color:inherit;background:#fff');
  input.maxLength = 800; input.placeholder = 'Type your message'; input.setAttribute('aria-label', 'Your message');
  var send = el('button', 'padding:9px 14px;border:0;border-radius:8px;color:#fff;font:inherit;cursor:pointer;background:' + accent, 'Send');
  send.type = 'submit';
  var note = el('div', 'padding:0 12px 8px;font-size:11px;color:#6b7370;background:#fff', 'AI assistant. It can make mistakes; the team may follow up.');
  var launcher = el('button', 'width:56px;height:56px;border-radius:50%;border:0;color:#fff;font-size:24px;cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.25);background:' + accent, '\u{1F4AC}');
  launcher.setAttribute('aria-label', 'Open chat');
  form.append(input, send); panel.append(head, log, form, note);
  if (wa) {
    var link = el('a', 'display:block;padding:0 12px 8px;font-size:12px;color:' + accent + ';background:#fff;text-decoration:underline', 'Prefer WhatsApp? Continue there');
    link.href = 'https://wa.me/' + wa + '?text=' + encodeURIComponent('Hi, I was chatting on your website.'); link.target = '_blank'; link.rel = 'noopener noreferrer';
    panel.append(link);
  }
  host.append(panel, launcher); document.body.appendChild(host);

  function bubble(text, mine) {
    var b = el('div', 'max-width:85%;padding:8px 11px;border-radius:12px;white-space:pre-wrap;word-wrap:break-word;' +
      (mine ? 'align-self:flex-end;color:#fff;background:' + accent : 'align-self:flex-start;background:#fff;border:1px solid #e0e5e2'), text);
    log.appendChild(b); log.scrollTop = log.scrollHeight; return b;
  }

  var opened = false;
  launcher.onclick = function () {
    var show = panel.style.display === 'none';
    panel.style.display = show ? 'flex' : 'none';
    if (show && !opened) {
      opened = true;
      call('/info').then(function (r) {
        if (!r.ok) { bubble('Chat is not available right now.', false); input.disabled = send.disabled = true; return; }
        head.textContent = r.body.business ? 'Chat with ' + r.body.business : 'Chat with us';
        bubble('Hi! I’m ' + r.body.agentName + '. How can I help?', false);
      }).catch(function () { bubble('Chat is not available right now.', false); });
    }
    if (show) input.focus();
  };

  form.onsubmit = function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text || busy) return;
    input.value = ''; busy = true; bubble(text, true);
    var wait = bubble('…', false);
    call('/chat', { message: text, conversationId: convId }).then(function (r) {
      if (r.ok) { convId = r.body.conversationId; store.set(convKey, convId); }
      wait.textContent = r.ok ? (r.body.reply || '') : (r.body.error || 'Something went wrong.');
      if (r.ok && !r.body.reply) wait.remove();
    }).catch(function () { wait.textContent = 'Network problem. Please try again.'; })
      .then(function () { busy = false; input.focus(); });
  };
})();
