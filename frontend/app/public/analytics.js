/* Usage metrics with consent (visits, active time, return visits).
 *
 * Nothing is stored or sent until the visitor accepts the banner. Accepting saves a random ID in
 * this browser (localStorage) and sends, to our own server only, that ID, the page path, the
 * language, the referrer's host and the seconds the page was visible. No IP address or user agent
 * is stored. Rejecting (or withdrawing later) deletes the ID and the server-side records.
 * Browsers that send Global Privacy Control / Do Not Track are treated as "reject" without a banner.
 * Loaded by every page; plain JS because the pages are either server-rendered or the React build.
 */
(function () {
  "use strict";

  var CONSENT_KEY = "eve_consent", VISITOR_KEY = "eve_vid", VISIT_KEY = "eve_sid", ACTIVE_KEY = "eve_last";
  var PING_MS = 30000, SESSION_GAP_MS = 30 * 60 * 1000;

  var TEXT = {
    en: { msg: "We'd like to measure visits and whether people come back, using a random ID stored in your browser. No IP address, no ads, never shared.", yes: "Accept", no: "Reject", more: "Details" },
    es: { msg: "Queremos medir las visitas y si la gente vuelve, con un ID aleatorio guardado en tu navegador. Sin IP, sin publicidad y sin compartirlo.", yes: "Aceptar", no: "Rechazar", more: "Detalles" },
    de: { msg: "Wir möchten Besuche und Wiederkehr messen, mit einer zufälligen ID in deinem Browser. Keine IP-Adresse, keine Werbung, keine Weitergabe.", yes: "Akzeptieren", no: "Ablehnen", more: "Details" },
    fr: { msg: "Nous aimerions mesurer les visites et les retours, avec un identifiant aléatoire stocké dans votre navigateur. Pas d'IP, pas de publicité, jamais partagé.", yes: "Accepter", no: "Refuser", more: "Détails" },
    it: { msg: "Vorremmo misurare le visite e i ritorni, con un ID casuale salvato nel tuo browser. Nessun IP, nessuna pubblicità, mai condiviso.", yes: "Accetta", no: "Rifiuta", more: "Dettagli" }
  };

  function read(store, key) { try { return store.getItem(key); } catch { return null; } }
  function write(store, key, value) { try { store.setItem(key, value); } catch { /* storage blocked */ } }
  function drop(store, key) { try { store.removeItem(key); } catch { /* storage blocked */ } }

  function lang() {
    var stored = read(window.localStorage, "lang");
    var code = (stored || document.documentElement.lang || navigator.language || "en").slice(0, 2).toLowerCase();
    return TEXT[code] ? code : "en";
  }

  function randomId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    var bytes = new Uint8Array(16);
    (window.crypto || window.msCrypto).getRandomValues(bytes);
    return Array.prototype.map.call(bytes, function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
  }

  function post(path, payload) {
    try {
      fetch(path, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        keepalive: true, credentials: "omit"
      }).catch(function () { /* analytics must never break the page */ });
    } catch { /* ignore */ }
  }

  var tracking = false, active = 0, timer = null, lastPing = 0;

  function visitId() {
    var now = Date.now(), last = Number(read(window.sessionStorage, ACTIVE_KEY) || 0), id = read(window.sessionStorage, VISIT_KEY);
    if (!id || (last && now - last > SESSION_GAP_MS)) { id = randomId(); active = 0; write(window.sessionStorage, VISIT_KEY, id); }
    write(window.sessionStorage, ACTIVE_KEY, String(now));
    return id;
  }

  function send(kind) {
    var vid = read(window.localStorage, VISITOR_KEY);
    if (!vid) { vid = randomId(); write(window.localStorage, VISITOR_KEY, vid); }
    var ref = "";
    try { ref = document.referrer ? new URL(document.referrer).hostname : ""; } catch { ref = ""; }
    lastPing = Date.now();
    post("/api/analytics/ping", {
      v: vid, s: visitId(), p: location.pathname, a: Math.min(active, 14400), e: kind, r: ref, l: lang()
    });
  }

  function startTracking() {
    if (tracking) return;
    // The owner's own browser (flagged by the app after signing in) is not measured.
    if (read(window.localStorage, "owner") === "1") return;
    tracking = true;
    send("view");
    timer = setInterval(function () {
      if (document.visibilityState !== "visible") return;
      active += 1;
      if (Date.now() - lastPing >= PING_MS) send("ping");
    }, 1000);
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "hidden" && tracking) send("ping");
    });
    window.addEventListener("pagehide", function () { if (tracking) send("ping"); });
  }

  function stopTracking(forget) {
    tracking = false;
    if (timer) clearInterval(timer);
    var vid = read(window.localStorage, VISITOR_KEY);
    if (forget && vid) post("/api/analytics/forget", { v: vid });
    drop(window.localStorage, VISITOR_KEY);
    drop(window.sessionStorage, VISIT_KEY);
    drop(window.sessionStorage, ACTIVE_KEY);
  }

  function choose(value) {
    var was = read(window.localStorage, CONSENT_KEY);
    write(window.localStorage, CONSENT_KEY, value);
    var banner = document.getElementById("eve-consent");
    if (banner) banner.remove();
    if (value === "granted") startTracking();
    else stopTracking(was === "granted");
  }

  function button(label, primary) {
    var b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.style.cssText = "font:600 14px/1 'Space Grotesk',system-ui,sans-serif;padding:10px 18px;border-radius:10px;cursor:pointer;" +
      "border:1px solid #3a4160;background:" + (primary ? "#5b8cff" : "transparent") + ";color:" + (primary ? "#08090f" : "#e8eaf0") + ";";
    return b;
  }

  function showBanner() {
    if (document.getElementById("eve-consent")) return;
    var t = TEXT[lang()];
    var box = document.createElement("div");
    box.id = "eve-consent";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-label", "Privacy");
    box.style.cssText = "position:fixed;left:12px;right:12px;bottom:12px;max-width:640px;margin:0 auto;z-index:2147483000;" +
      "background:#11131c;color:#e8eaf0;border:1px solid #2a3050;border-radius:14px;padding:16px;box-shadow:0 8px 30px rgba(0,0,0,.5);" +
      "font:14px/1.5 'Space Grotesk',system-ui,sans-serif;";
    var p = document.createElement("p");
    p.style.cssText = "margin:0 0 12px;";
    p.textContent = t.msg + " ";
    var more = document.createElement("a");
    more.href = "/privacy";
    more.textContent = t.more;
    more.style.cssText = "color:#8fb0ff;";
    p.appendChild(more);
    var row = document.createElement("div");
    row.style.cssText = "display:flex;gap:10px;flex-wrap:wrap;";
    var yes = button(t.yes, true), no = button(t.no, false);
    yes.addEventListener("click", function () { choose("granted"); });
    no.addEventListener("click", function () { choose("denied"); });
    row.appendChild(yes);
    row.appendChild(no);
    box.appendChild(p);
    box.appendChild(row);
    document.body.appendChild(box);
  }

  function init() {
    var optedOut = navigator.globalPrivacyControl === true || navigator.doNotTrack === "1";
    var stored = read(window.localStorage, CONSENT_KEY);
    if (optedOut) { if (stored === "granted") choose("denied"); return; }
    if (stored === "granted") startTracking();
    else if (stored !== "denied") showBanner();
    document.addEventListener("click", function (event) {
      var target = event.target;
      if (target && target.closest && target.closest("[data-eve-consent-settings]")) {
        event.preventDefault();
        showBanner();
      }
    });
  }

  window.eveAnalytics = { openSettings: showBanner };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
