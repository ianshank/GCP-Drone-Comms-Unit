"""Self-contained chat widget for embedding the SA assistant in a dashboard.

``CHAT_WIDGET_HTML`` is a single static page with no external dependencies; it
POSTs to ``/chat`` (same origin) and renders the reply. Drop the assistant's URL
into a Cockpit iframe widget (or any browser tab) to get the chat pane. Keeping
it a pure constant means it is trivially served by ``server.build_app`` and
verifiable in a unit test.
"""

from __future__ import annotations

CHAT_WIDGET_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>SA Assistant</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; font: 14px/1.45 system-ui, sans-serif; background: #11151c; color: #e6e9ef; }
  header { padding: 10px 14px; background: #1b2230; font-weight: 600; }
  #log { padding: 12px 14px; height: calc(100vh - 122px); overflow-y: auto; }
  .msg { margin: 0 0 10px; padding: 8px 10px; border-radius: 8px; white-space: pre-wrap; }
  .user { background: #24314a; }
  .bot { background: #1d2531; }
  .meta { color: #8a93a6; font-size: 12px; }
  form { display: flex; gap: 8px; padding: 10px 14px; background: #1b2230; }
  input { flex: 1; padding: 9px 10px; border-radius: 8px; border: 1px solid #2c3650;
          background: #0d1117; color: #e6e9ef; }
  button { padding: 9px 14px; border: 0; border-radius: 8px; background: #3b6ea5;
           color: #fff; cursor: pointer; }
  button:disabled { opacity: .5; cursor: default; }
</style>
</head>
<body>
<header>Situational-Awareness Assistant <span class="meta">(read-only)</span></header>
<div id="log"></div>
<form id="f">
  <input id="q" autocomplete="off" placeholder="Ask about the drone or TAK tracks..." />
  <button id="send" type="submit">Send</button>
</form>
<script>
  const log = document.getElementById("log");
  const form = document.getElementById("f");
  const input = document.getElementById("q");
  const send = document.getElementById("send");
  function add(text, cls) {
    const el = document.createElement("div");
    el.className = "msg " + cls;
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const prompt = input.value.trim();
    if (!prompt) return;
    add(prompt, "user");
    input.value = "";
    send.disabled = true;
    const pending = add("...", "bot");
    try {
      const res = await fetch("chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      const data = await res.json();
      pending.textContent = data.reply || data.error || "(no reply)";
    } catch (err) {
      pending.textContent = "request failed: " + err;
    } finally {
      send.disabled = false;
      input.focus();
    }
  });
</script>
</body>
</html>
"""
