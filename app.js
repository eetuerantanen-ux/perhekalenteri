/* Perhekalenteri – keittiön tabletti. Kaikki aikalaskenta Europe/Helsinki-ajassa. */
(() => {
  "use strict";
  const TZ = "Europe/Helsinki";
  const DATA_URL = "data.enc.json";
  const KEY_STORE = "perhekalenteri.avain.v1";
  const LOCAL_DEV = ["127.0.0.1", "localhost"].includes(location.hostname);
  const REFRESH_MS = 5 * 60 * 1000;      // data 5 min välein
  const HARD_RELOAD_MS = 6 * 3600 * 1000; // koko sivu 6 h välein
  const NIGHT_FROM = 21, NIGHT_TO = 6;    // yötila klo 21–06
  const STALE_MIN = 180;
  const params = new URLSearchParams(location.search);
  const forcedMode = params.get("tila");  // "paiva" | "yo" (testaukseen)

  const WD = ["su", "ma", "ti", "ke", "to", "pe", "la"];
  const WD_LONG = ["sunnuntai", "maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai"];
  const MON = ["tammikuuta", "helmikuuta", "maaliskuuta", "huhtikuuta", "toukokuuta", "kesäkuuta", "heinäkuuta", "elokuuta", "syyskuuta", "lokakuuta", "marraskuuta", "joulukuuta"];

  let DATA = null, lastFetchOk = true, lastFetchAt = null;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /* ---------- aika-apurit ---------- */
  const fmtParts = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
  function hk(date) {
    const p = {}; for (const x of fmtParts.formatToParts(date)) p[x.type] = x.value;
    const y = +p.year, m = +p.month, d = +p.day;
    return { y, m, d, hh: +p.hour, mm: +p.minute, ss: +p.second, wd: new Date(Date.UTC(y, m - 1, d)).getUTCDay(), key: `${p.year}-${p.month}-${p.day}` };
  }
  function offsetMin(date) { const p = hk(date); return (Date.UTC(p.y, p.m - 1, p.d, p.hh, p.mm, p.ss) - Math.floor(date.getTime() / 1000) * 1000) / 60000; }
  function midnight(key) { // Helsingin keskiyö avaimelle YYYY-MM-DD
    const [y, m, d] = key.split("-").map(Number);
    let t = Date.UTC(y, m - 1, d); t -= offsetMin(new Date(t)) * 60000; t = Date.UTC(y, m - 1, d) - offsetMin(new Date(t)) * 60000;
    return new Date(t);
  }
  function addDays(key, n) { const [y, m, d] = key.split("-").map(Number); const t = new Date(Date.UTC(y, m - 1, d + n)); return t.toISOString().slice(0, 10); }
  function keyInfo(key) { const [y, m, d] = key.split("-").map(Number); return { y, m, d, wd: new Date(Date.UTC(y, m - 1, d)).getUTCDay() }; }
  function isoWeek(key) { const [y, m, d] = key.split("-").map(Number); const t = new Date(Date.UTC(y, m - 1, d)); const dn = (t.getUTCDay() + 6) % 7; t.setUTCDate(t.getUTCDate() - dn + 3); const fy = new Date(Date.UTC(t.getUTCFullYear(), 0, 4)); return 1 + Math.round(((t - fy) / 864e5 - 3 + ((fy.getUTCDay() + 6) % 7)) / 7); }
  const hm = (date) => { const p = hk(date); return `${String(p.hh).padStart(2, "0")}.${String(p.mm).padStart(2, "0")}`; };
  const shortDate = (key) => { const i = keyInfo(key); return `${WD[i.wd]} ${i.d}.${i.m}.`; };
  function now() { const n = params.get("nyt"); return n ? new Date(n) : new Date(); }

  /* ---------- sää-ikonit (inline SVG, ei ulkoisia riippuvuuksia) ---------- */
  const SUN = '<circle cx="32" cy="32" r="11" fill="#f2b33d"/><g stroke="#f2b33d" stroke-width="4" stroke-linecap="round"><path d="M32 8v6M32 50v6M8 32h6M50 32h6M15 15l4 4M45 45l4 4M15 49l4-4M45 19l4-4"/></g>';
  const MOON = '<path d="M40 12a20 20 0 1 0 12 30A17 17 0 0 1 40 12z" fill="#e9d79a"/>';
  const CLOUD = (y = 0, c = "#c9c2b8") => `<path transform="translate(0 ${y})" d="M20 50h26a11 11 0 0 0 0-22 15 15 0 0 0-28 3 9.5 9.5 0 0 0 2 19z" fill="${c}"/>`;
  const SMALL_SUN = '<g transform="translate(-6 -8) scale(.75)">' + SUN + '</g>';
  const SMALL_MOON = '<g transform="translate(-4 -6) scale(.75)">' + MOON + '</g>';
  const DROPS = '<g stroke="#4c8dc4" stroke-width="3.5" stroke-linecap="round"><path d="M24 54l-3 7M34 54l-3 7M44 54l-3 7"/></g>';
  const FLAKES = '<g fill="#8fb7d9"><circle cx="22" cy="58" r="3"/><circle cx="33" cy="61" r="3"/><circle cx="44" cy="58" r="3"/></g>';
  const BOLT = '<path d="M34 46l-8 12h7l-4 9 11-14h-7l4-7z" fill="#f2b33d"/>';
  const FOG = '<g stroke="#b3aca2" stroke-width="4" stroke-linecap="round"><path d="M12 26h40M8 36h44M14 46h36"/></g>';
  function wIcon(code, day = 1) {
    const sky = day ? SMALL_SUN : SMALL_MOON;
    let g;
    if (code === 0) g = day ? SUN : MOON;
    else if (code === 1 || code === 2) g = sky + CLOUD(0, "#ddd6cc");
    else if (code === 3) g = CLOUD(-2, "#bdb5aa");
    else if (code === 45 || code === 48) g = FOG;
    else if ([51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82].includes(code)) g = CLOUD(-6, "#a9a198") + DROPS;
    else if ([71, 73, 75, 77, 85, 86].includes(code)) g = CLOUD(-6, "#bdb5aa") + FLAKES;
    else if (code >= 95) g = CLOUD(-8, "#8f877d") + BOLT;
    else g = CLOUD(-2);
    return `<svg viewBox="0 0 64 64" aria-hidden="true">${g}</svg>`;
  }
  function wText(c) {
    if (c === 0) return "Selkeää"; if (c === 1) return "Enimmäkseen selkeää"; if (c === 2) return "Puolipilvistä"; if (c === 3) return "Pilvistä";
    if (c === 45 || c === 48) return "Sumua"; if (c >= 51 && c <= 55) return "Tihkusadetta"; if (c === 56 || c === 57) return "Jäätävää tihkua";
    if (c === 61) return "Heikkoa sadetta"; if (c === 63) return "Sadetta"; if (c === 65) return "Runsasta sadetta"; if (c === 66 || c === 67) return "Jäätävää sadetta";
    if (c === 71) return "Heikkoa lumisadetta"; if (c === 73) return "Lumisadetta"; if (c === 75) return "Runsasta lumisadetta"; if (c === 77) return "Lumijyväsiä";
    if (c >= 80 && c <= 82) return "Sadekuuroja"; if (c === 85 || c === 86) return "Lumikuuroja"; if (c >= 95) return "Ukkosta"; return "–";
  }
  const deg = (v) => (v == null ? "–" : `${Math.round(v)}°`);

  /* ---------- jäsenet ja värit ---------- */
  const member = (k) => (DATA?.jasenet?.[k]) || { nimi: k, tunnus: "?", vari: "#8a7a6a" };
  const evColor = (e) => member(e.henkilot?.[0] || e.kalenteri).vari;
  const evWho = (e) => (e.henkilot || []).map((k) => member(k).nimi).join(", ");

  /* ---------- tapahtumat päivälle ---------- */
  function eventsForDay(key) {
    const s = midnight(key), e = midnight(addDays(key, 1));
    const out = [];
    for (const ev of DATA?.tapahtumat || []) {
      const a = new Date(ev.alku), b = new Date(ev.loppu);
      if (!(a < e && b > s)) continue;
      const long = ev.kokopaiva || (b - a) >= 24 * 3600e3;
      const startsBefore = a < s, endsAfter = b > e;
      let time = "";
      if (!long) {
        if (startsBefore) time = `→ ${hm(b)}`;
        else if (endsAfter) time = `${hm(a)} →`;
        else time = hm(a);
      }
      let sub = "";
      if (long) {
        const lastKey = ev.kokopaiva ? addDays(hk(b).key, -1) : hk(b).key;
        if (lastKey !== key && lastKey > key) sub = `${shortDate(lastKey)} asti`;
        else if (!ev.kokopaiva && startsBefore) sub = `päättyy ${hm(b)}`;
      }
      out.push({ ...ev, a, b, long, time, sub, startsBefore, endsAfter });
    }
    out.sort((x, y) => (y.long - x.long) || (x.a - y.a));
    return out;
  }

  /* ---------- renderöinti ---------- */
  function renderHeader(n) {
    const p = hk(n);
    $("time").textContent = `${String(p.hh).padStart(2, "0")}.${String(p.mm).padStart(2, "0")}`;
    $("date").textContent = `${WD_LONG[p.wd].replace(/^./, (x) => x.toUpperCase())} ${p.d}. ${MON[p.m - 1]}`;
    $("week").textContent = `Viikko ${isoWeek(p.key)}`;
    $("brandSub").textContent = `${p.d}.${p.m}.${p.y}`;
    const night = forcedMode ? forcedMode === "yo" : (p.hh >= NIGHT_FROM || p.hh < NIGHT_TO);
    document.body.classList.toggle("night", night);
  }

  function renderMembers() {
    const keys = Object.keys(DATA?.jasenet || {}).filter((k) => k !== "pyha");
    $("members").innerHTML = keys.map((k) => { const m = member(k); return `<div class="chip"><span class="avatar" style="background:${m.vari}">${esc(m.tunnus)}</span>${esc(m.nimi)}</div>`; }).join("");
  }

  function renderStatus(n) {
    if (!DATA) { $("status").innerHTML = '<span class="warn">Ei tietoja vielä</span>'; return; }
    const upd = new Date(DATA.paivitetty);
    const ageMin = (n - upd) / 60000;
    let html = `Päivitetty ${hm(upd)}`;
    if (!lastFetchOk) html = `<span class="warn">Ei yhteyttä</span> ${html}`;
    else if (ageMin > STALE_MIN) html = `<span class="warn">Tiedot vanhoja</span> ${html}`;
    $("status").innerHTML = html;
  }

  function renderWeather(n) {
    const w = DATA?.saa;
    if (!w?.nyt) { $("weather").innerHTML = '<div class="card-title">Sää · Koria</div><div class="empty">Säätietoja ei saatu.</div>'; return; }
    const c = w.nyt;
    const nowH = n.getTime();
    const hours = (w.tunnit || []).filter((h) => midnight(h.aika.slice(0, 10)).getTime() + (+h.aika.slice(11, 13)) * 3600e3 >= nowH - 3600e3);
    const pick = []; for (let i = 1; i < hours.length && pick.length < 6; i += 2) pick.push(hours[i]);
    const todayKey = hk(n).key;
    const days = (w.paivat || []).filter((d) => d.pvm >= todayKey).slice(0, 5);
    const today = days[0];
    $("weather").innerHTML = `
      <div class="card-title">Sää · Koria <small>${esc(w.lahde)}</small></div>
      <div class="w-now">${wIcon(c.koodi, c.paiva)}
        <div><div class="w-temp">${deg(c.lampo)}</div></div>
        <div><div class="w-desc">${wText(c.koodi)}</div>
          <div class="w-meta">Tuntuu ${deg(c.tuntuu)} · tuuli ${Math.round(c.tuuli)} m/s</div></div>
      </div>
      <div class="w-hours">${pick.map((h) => `<div>${h.aika.slice(11, 13)}${wIcon(h.koodi, h.paiva)}<b>${deg(h.lampo)}</b></div>`).join("")}</div>
      <div class="w-days">${days.map((d, i) => `<div class="w-day"><span>${i === 0 ? "Tänään" : WD[keyInfo(d.pvm).wd].replace(/^./, (x) => x.toUpperCase())}</span>${wIcon(d.koodi, 1)}
        <span class="rain">${d.sade_tn >= 30 && d.sade_mm >= 0.2 ? `${d.sade_mm.toFixed(1).replace(".", ",")} mm` : ""}</span>
        <span class="rng">${deg(d.max)} <span>/ ${deg(d.min)}</span></span></div>`).join("")}</div>
      ${today ? `<div class="w-sun">Aurinko nousee ${today.aurinko_nousee.slice(11)} · laskee ${today.aurinko_laskee.slice(11)}</div>` : ""}`;
  }

  function renderToday(n) {
    const key = hk(n).key;
    const evs = eventsForDay(key);
    const longs = evs.filter((e) => e.long), timed = evs.filter((e) => !e.long);
    let html = `<div class="card-title">Tänään <small>${esc(shortDate(key))}</small></div><div class="ev-list">`;
    for (const e of longs) html += `<div class="banner${e.alustava ? " tent" : ""}" style="background:${evColor(e)}22;border-left:6px solid ${evColor(e)}">${esc(e.otsikko)}<span class="sub">${esc(e.sub || "koko päivä")} · ${esc(evWho(e))}</span></div>`;
    let nowShown = false, shown = 0;
    const MAX = Math.max(2, 7 - longs.length);
    for (const e of timed) {
      const past = e.b <= n, cur = e.a <= n && e.b > n;
      if (!nowShown && !past) { html += `<div class="nowline">nyt ${hm(n)}</div>`; nowShown = true; }
      if (shown >= MAX) continue;
      const end = e.endsAfter ? "" : (e.startsBefore ? "" : `<small>– ${hm(e.b)}</small>`);
      html += `<div class="ev${past ? " past" : ""}${cur ? " now" : ""}${e.alustava ? " tent" : ""}"><div class="t">${esc(e.time)}${end}</div>
        <div class="body" style="border-color:${evColor(e)}"><div class="title">${esc(e.otsikko)}</div><div class="who">${esc(evWho(e))}${e.paikka ? " · " + esc(e.paikka) : ""}${e.alustava ? " · alustava" : ""}</div></div></div>`;
      shown++;
    }
    if (timed.length > shown) html += `<div class="more">+${timed.length - shown} muuta</div>`;
    if (!nowShown && timed.length) html += `<div class="nowline">nyt ${hm(n)}</div>`;
    if (!evs.length) html += `<div class="empty">Ei merkintöjä tälle päivälle.</div>`;
    $("today").innerHTML = html + "</div>";
  }

  function renderUpcoming(n) {
    const todayKey = hk(n).key;
    const weather = Object.fromEntries((DATA?.saa?.paivat || []).map((d) => [d.pvm, d]));
    let html = `<div class="card-title">Tulevat päivät</div><div class="days">`;
    for (let i = 1; i <= 6; i++) {
      const key = addDays(todayKey, i), info = keyInfo(key), w = weather[key];
      // Jo käynnissä olevat monipäiväiset näytetään vain ensimmäisellä rivillä, jotta lista mahtuu ruutuun.
      const evs = eventsForDay(key).filter((e) => !(e.long && e.startsBefore && i > 1));
      const label = i === 1 ? "Huomenna" : `${WD_LONG[info.wd]}`;
      const wk = info.wd === 1 ? ` · vk ${isoWeek(key)}` : "";
      const MAXP = 3;
      const pills = evs.slice(0, MAXP).map((e) => e.long
        ? `<span class="pill span${e.alustava ? " tent" : ""}" style="background:${evColor(e)}">${esc(e.otsikko)}${e.sub ? ` <small style="opacity:.85;font-weight:700">· ${esc(e.sub)}</small>` : ""}</span>`
        : `<span class="pill${e.alustava ? " tent" : ""}" style="border-color:${evColor(e)}"><span class="pt">${esc(e.time)}</span>${esc(e.otsikko)}</span>`).join("");
      html += `<div class="day${info.wd === 0 || info.wd === 6 ? " weekend" : ""}"><div class="dl"><b>${label}</b><span>${info.d}.${info.m}.${wk}${w ? ` ${wIcon(w.koodi, 1)}${deg(w.max)}` : ""}</span></div>
        <div class="pills">${pills || '<span class="none">Ei merkintöjä</span>'}${evs.length > MAXP ? `<span class="more">+${evs.length - MAXP}</span>` : ""}</div></div>`;
    }
    $("upcoming").innerHTML = html + "</div>";
  }

  function renderMenu(n) {
    const lists = DATA?.ruokalistat || [];
    const p = hk(n);
    const todayKey = p.key;
    // Ennen klo 13 näytetään tämän päivän lounas, sen jälkeen seuraavan päivän, jolle lista löytyy.
    const allDates = [...new Set(lists.flatMap((l) => (l.paivat || []).filter((d) => d.ateriat?.length).map((d) => d.pvm)))].sort();
    const target = allDates.find((d) => (p.hh < 13 ? d >= todayKey : d > todayKey));
    const lbl = !target ? "" : target === todayKey ? "tänään" : target === addDays(todayKey, 1) ? `huomenna ${shortDate(target)}` : shortDate(target);
    let html = `<div class="card-title">Ruokalista <small>${esc(lbl)}</small></div>`;
    const SHOW = ["Aamupala", "Lounas", "Välipala"];
    for (const l of lists) {
      const kids = (l.henkilot || []).map(member);
      html += `<div class="menu-head">${kids.map((m) => `<span class="avatar" style="background:${m.vari}">${esc(m.tunnus)}</span>`).join("")}
        <span class="menu-place">${esc(kids.map((m) => m.nimi).join(" ja "))} · ${esc(l.otsikko)}</span></div>`;
      if (!l.ok) { html += `<div class="empty">Ruokalistaa ei saatu.</div>`; continue; }
      const day = (l.paivat || []).find((d) => d.pvm === target);
      const meals = SHOW.map((n) => day?.ateriat?.find((x) => x.ateria.trim().toLowerCase() === n.toLowerCase())).filter(Boolean);
      if (!meals.length) { html += `<div class="empty">Ei ruokalistaa tälle päivälle.</div>`; continue; }
      html += `<div class="meals">` + meals.map((m) => {
        const [main, ...sides] = m.ruoat.map((r) => r.nimi);
        const lunch = /^lounas$/i.test(m.ateria.trim());
        return `<div class="meal${lunch ? " lunch" : ""}"><div class="mn">${esc(m.ateria.trim())}</div><div><span class="main">${esc(main)}</span>${sides.length ? `<span class="side">, ${esc(sides.join(", "))}</span>` : ""}</div></div>`;
      }).join("") + `</div>`;
    }
    if (!lists.length) html += `<div class="empty">Ruokalistoja ei saatu.</div>`;
    $("menu").innerHTML = html;
  }

  function renderReminders(n) {
    const r = DATA?.muistutukset;
    const todayKey = hk(n).key;
    let html = `<div class="card-title">Muistutukset</div>`;
    if (!r || r.tila !== "ok") {
      html += `<div class="tulossa"><b>Tulossa</b>eVakan muistutukset näkyvät tässä, kun yhteys on valmis.</div>`;
    } else {
      const items = r.kohteet.filter((x) => !x.pvm || x.pvm >= todayKey).slice(0, 4);
      if (!items.length) html += `<div class="empty">Ei avoimia muistutuksia.</div>`;
      for (const x of items) {
        let d = "–", sm = "";
        if (x.pvm) {
          const days = Math.round((midnight(x.pvm) - midnight(todayKey)) / 864e5);
          d = shortDate(x.pvm); sm = days === 0 ? "tänään" : days === 1 ? "huomenna" : `${days} pv`;
        }
        const kid = x.lapsi ? member(x.lapsi.toLowerCase()) : null;
        html += `<div class="rem"><div class="d">${esc(d)}${sm ? `<small>${esc(sm)}</small>` : ""}</div>
          <div><div class="x">${esc(x.otsikko)}</div><div class="src"><i style="background:${kid ? kid.vari : "var(--ink-3)"}"></i>${esc(x.lahde || "")}${kid ? " · " + esc(kid.nimi) : ""}</div></div></div>`;
      }
      if (r.kohteet.length > items.length && items.length === 4) html += `<div class="more">+ lisää</div>`;
    }
    $("reminders").innerHTML = html;
  }

  function renderTodo() {
    const t = DATA?.muistilista;
    let html = `<div class="card-title">Muistilista</div>`;
    if (!t || t.tila !== "ok") html += `<div class="tulossa"><b>Tulossa</b>Google Keepin ”Muistilista” näkyy tässä, kun yhteys on valmis.</div>`;
    else {
      const open = t.kohteet.filter((x) => !x.tehty), done = t.kohteet.filter((x) => x.tehty);
      const items = [...open, ...done].slice(0, 6);
      if (!items.length) html += `<div class="empty">Lista on tyhjä.</div>`;
      html += items.map((x) => `<div class="todo-item${x.tehty ? " done" : ""}"><span class="box"></span>${esc(x.teksti)}</div>`).join("");
      if (t.kohteet.length > items.length) html += `<div class="more">+${t.kohteet.length - items.length} muuta</div>`;
    }
    $("todo").innerHTML = html;
  }

  function renderFoot() {
    const errs = (DATA?.virheet || []).map((e) => e.lahde);
    $("foot").innerHTML = `<span>Lähteet: Google-kalenteri · Open-Meteo (sää) · Kouvolan Aromi14 (ruokalistat) · eVaka (Arjen apuri)${errs.length ? " · virhe: " + esc(errs.join(", ")) : ""}</span><span>Yötila klo ${NIGHT_FROM}–0${NIGHT_TO} · <a href="#" id="forgetLink">unohda salasana</a></span>`;
  }

  function renderAll() {
    const n = now();
    renderHeader(n); renderMembers(); renderStatus(n);
    if (!DATA) return;
    renderWeather(n); renderToday(n); renderUpcoming(n); renderMenu(n); renderReminders(n); renderTodo(); renderFoot();
  }

  /* ---------- salaus: AES-GCM + PBKDF2 (WebCrypto) ---------- */
  const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  const toB64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));
  let ENC = null;
  async function deriveKey(pw, enc) {
    const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(pw), "PBKDF2", false, ["deriveKey"]);
    return crypto.subtle.deriveKey({ name: "PBKDF2", hash: "SHA-256", salt: b64(enc.salt), iterations: enc.iter }, base, { name: "AES-GCM", length: 256 }, true, ["decrypt"]);
  }
  async function decryptWith(key, enc) {
    const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(enc.iv) }, key, b64(enc.ct));
    return JSON.parse(new TextDecoder().decode(pt));
  }
  async function storedKey(enc) {
    try {
      const st = JSON.parse(localStorage.getItem(KEY_STORE) || "null");
      if (!st || st.salt !== enc.salt || st.iter !== enc.iter) return null;
      return await crypto.subtle.importKey("raw", b64(st.k), "AES-GCM", false, ["decrypt"]);
    } catch (e) { return null; }
  }
  function showLock(msg) {
    const l = $("lock"); l.hidden = false; $("lockMsg").textContent = msg || "";
    setTimeout(() => $("lockPw").focus(), 50);
  }
  async function unlock(ev) {
    ev.preventDefault();
    const pw = $("lockPw").value; if (!pw || !ENC) return;
    $("lockBtn").disabled = true; $("lockMsg").textContent = "Avataan…";
    try {
      const key = await deriveKey(pw, ENC);
      DATA = await decryptWith(key, ENC);
      localStorage.setItem(KEY_STORE, JSON.stringify({ salt: ENC.salt, iter: ENC.iter, k: toB64(await crypto.subtle.exportKey("raw", key)) }));
      $("lockPw").value = ""; $("lock").hidden = true; lastFetchOk = true; renderAll();
    } catch (e) { $("lockMsg").textContent = "Väärä salasana – yritä uudelleen."; }
    $("lockBtn").disabled = false;
  }
  function forget() { localStorage.removeItem(KEY_STORE); DATA = null; location.reload(); }

  async function load() {
    try {
      const r = await fetch(`${DATA_URL}?t=${Date.now()}`, { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      ENC = await r.json();
      const key = await storedKey(ENC);
      if (!key) { if (!DATA) showLock(""); else lastFetchOk = true; }
      else {
        try { DATA = await decryptWith(key, ENC); lastFetchOk = true; lastFetchAt = new Date(); $("lock").hidden = true; }
        catch (e) { localStorage.removeItem(KEY_STORE); showLock("Salasana on vaihtunut – anna uusi salasana."); }
      }
    } catch (e) {
      if (LOCAL_DEV && !DATA) { // paikallinen esikatselu ilman salausta
        try { const r2 = await fetch(`data.json?t=${Date.now()}`, { cache: "no-store" }); if (r2.ok) { DATA = await r2.json(); $("lock").hidden = true; } } catch (_) {}
      }
      if (DATA) lastFetchOk = !!DATA && lastFetchOk; else lastFetchOk = false;
      if (!DATA) lastFetchOk = false;
    }
    renderAll();
  }
  $("lockForm").addEventListener("submit", unlock);
  document.addEventListener("click", (e) => { if (e.target && e.target.id === "forgetLink") { e.preventDefault(); if (confirm("Unohdetaanko tallennettu salasana tältä laitteelta?")) forget(); } });

  // Kello tikittää sekunnin välein, muu näkymä päivittyy minuutin välein, data 5 min välein.
  renderHeader(now());
  load();
  setInterval(() => renderHeader(now()), 1000);
  setInterval(renderAll, 60 * 1000);
  setInterval(load, REFRESH_MS);
  setTimeout(() => location.reload(), HARD_RELOAD_MS);
  // Pidä näyttö hereillä, jos selain tukee (Android Chrome).
  if ("wakeLock" in navigator) { const lock = () => navigator.wakeLock.request("screen").catch(() => {}); lock(); document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && lock()); }
})();
