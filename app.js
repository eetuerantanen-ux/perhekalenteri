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
  const VIEW_IDLE_MS = 30 * 1000; // viikko/kuukausi palaa päivään 30 s kuluttua
  const params = new URLSearchParams(location.search);
  const forcedMode = params.get("tila");  // "paiva" | "yo" (testaukseen)

  const WD = ["su", "ma", "ti", "ke", "to", "pe", "la"];
  const WD_LONG = ["sunnuntai", "maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai"];
  const MON = ["tammikuuta", "helmikuuta", "maaliskuuta", "huhtikuuta", "toukokuuta", "kesäkuuta", "heinäkuuta", "elokuuta", "syyskuuta", "lokakuuta", "marraskuuta", "joulukuuta"];
  const MON_NOM = ["tammikuu", "helmikuu", "maaliskuu", "huhtikuu", "toukokuu", "kesäkuu", "heinäkuu", "elokuu", "syyskuu", "lokakuu", "marraskuu", "joulukuu"];

  let DATA = null, lastFetchOk = true, lastFetchAt = null, PRICES = null, FORECAST = null;
  let currentView = "paiva", idleTimer = null, openDayKey = null, pricePopOpen = false, infoPopMode = null;
  // Scrollaus (t38u): veto vs. napautus + reunahäive-rekisteri.
  let _ptrDown = null, _ptrDragged = false, _scrollRegs = [];
  const PRICES_URL = (LOCAL_DEV && params.get("hinnat")) || "prices.json"; // ?hinnat= vain paikalliseen testaukseen
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
  function mondayOfIsoWeek(key) { return addDays(key, -((keyInfo(key).wd + 6) % 7)); }
  const isHolidayEv = (e) => (e.henkilot || []).includes("pyha") || e.kalenteri === "pyha";
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
  const badges = (e) => e.hoitovuoro ? (e.henkilot || []).map((k) => { const m = member(k); return `<span class="mini" style="background:${m.vari}">${esc(m.tunnus)}</span>`; }).join("") : "";
  const puokkari = (e) => (e.hoitovuoro && typeof e.puokkari === "boolean")
    ? `<span class="ptag${e.puokkari ? "" : " full"}" style="--c:${member(e.puokkari_kuka).vari}">${e.puokkari ? "Puokkari" : "Ei-puokkari"}</span>` : "";
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


  /* ---------- ruokalista hoitoajan ja lähteen mukaan ---------- */
  const MEAL_ORDER = ["Aamupala", "Lounas", "Välipala", "Päivällinen", "Iltapala"];
  function isWeekendKey(key) { const w = keyInfo(key).wd; return w === 0 || w === 6; }
  function isHolidayKey(key) { return eventsForDay(key).some(isHolidayEv); }
  function careShiftsOn(key) { return eventsForDay(key).filter((e) => e.hoitovuoro); }
  function isCareDay(key) { return careShiftsOn(key).length > 0; }
  function overnightStarts(key) {
    const end = midnight(addDays(key, 1));
    return careShiftsOn(key).some((e) => e.b > end);
  }
  function overnightEnds(key) {
    const start = midnight(key);
    return careShiftsOn(key).some((e) => e.a < start);
  }
  function listByRole(role) { return (DATA?.ruokalistat || []).find((l) => l.rooli === role); }
  function menuListForMeal(key, mealName) {
    const vuoro = listByRole("vuoro"), arki = listByRole("arki");
    const n = (mealName || "").trim().toLowerCase();
    const useVuoro = isWeekendKey(key) || isHolidayKey(key)
      || (overnightStarts(key) && (n === "päivällinen" || n === "iltapala"))
      || (overnightEnds(key) && n === "aamupala");
    if (useVuoro && vuoro) return vuoro;
    if (arki) return arki;
    return vuoro || (DATA?.ruokalistat || [])[0] || null;
  }
  function mealKids(key, mealName) {
    const shifts = careShiftsOn(key);
    if (!shifts.length) return [];
    const day0 = midnight(key).getTime(), next = midnight(addDays(key, 1)).getTime();
    const at = (h, m) => day0 + (h * 60 + m) * 60000;
    const kids = [];
    const add = (who) => { for (const k of who || []) if (!kids.includes(k)) kids.push(k); };
    // Ateria näytetään vain, jos hoitoaika oikeasti kattaa aterian tarjoiluhetken (start JA end huomioiden).
    // Näin lyhyt iltavuoro (esim. 19.30–20.30, vanhempien vaihto) näyttää vain iltapalan, ei päivällistä.
    for (const e of shifts) {
      const start = e.a.getTime(), end = e.b.getTime();
      let ok = false;
      if (mealName === "Aamupala") ok = Math.max(start, day0) <= at(8, 0);                 // aamupala: hoito alkaa klo 8 tai ennen
      else if (mealName === "Lounas") ok = start < at(11, 30) && end > at(11, 0);          // lounas tarjoillaan ~11.00–11.30
      else if (mealName === "Välipala") ok = start < at(14, 30) && end > at(14, 0);        // välipala ~14.00–14.30
      else if (mealName === "Päivällinen") ok = start < at(17, 30) && end > at(17, 0);     // päivällinen ~17.00–17.30 (yön yli: vain jos alkoi klo 17.30 mennessä)
      else if (mealName === "Iltapala") ok = (start < at(20, 0) && end > at(19, 30)) || end > next; // iltapala ~19.30–20.00 tai yön yli
      if (ok) add(e.henkilot);
    }
    return kids;
  }
  function careKids(key) {
    const kids = [];
    for (const e of careShiftsOn(key)) for (const k of e.henkilot || []) if (!kids.includes(k)) kids.push(k);
    return kids;
  }
  function findMeal(list, key, name) {
    const day = (list?.paivat || []).find((d) => d.pvm === key);
    return (day?.ateriat || []).find((a) => (a.ateria || "").trim().toLowerCase() === name.toLowerCase());
  }
  function dayMenu(key) {
    const care = isCareDay(key);
    if (!care) return { care: false, meals: [], sources: [] };
    const allKids = careKids(key);
    const meals = [], sources = [];
    for (const name of MEAL_ORDER) {
      const kids = mealKids(key, name);
      if (!kids.length) continue;
      const list = menuListForMeal(key, name);
      const item = findMeal(list, key, name);
      if (!item || !item.ruoat?.length) continue;
      const otsikko = list?.otsikko || "";
      meals.push({ name, item, kids, allKids, otsikko });
      if (otsikko && !sources.includes(otsikko)) sources.push(otsikko);
    }
    return { care: true, meals, sources };
  }
  function mealRowHtml(m, cls) {
    const [main, ...sides] = m.item.ruoat.map((r) => r.nimi);
    const lunch = /^lounas$/i.test(m.name);
    const differ = m.kids.length !== m.allKids.length;
    const av = differ ? m.kids.map((k) => { const x = member(k); return `<span class="mini" style="background:${x.vari}">${esc(x.tunnus)}</span>`; }).join("") : "";
    return `<div class="${cls}${lunch ? " lunch" : ""}"><div class="mn">${esc(m.name)}</div><div><span class="main">${esc(main)}</span>${sides.length ? `<span class="side">, ${esc(sides.join(", "))}</span>` : ""}${av ? `<span class="m-kids">${av}</span>` : ""}</div></div>`;
  }
  function nextCareDay(fromKey, inclusive) {
    const start = inclusive ? fromKey : addDays(fromKey, 1);
    const evs = DATA?.tapahtumat || [];
    const keys = new Set();
    for (const ev of evs) {
      if (!ev.hoitovuoro) continue;
      const a = hk(new Date(ev.alku)).key;
      const b = ev.kokopaiva ? addDays(hk(new Date(ev.loppu)).key, -1) : hk(new Date(ev.loppu)).key;
      let k = a;
      // overnight may span 2 days
      const last = b >= a ? b : a;
      while (k <= last) { if (k >= start) keys.add(k); if (k === last) break; k = addDays(k, 1); if (keys.size > 60) break; }
    }
    return [...keys].sort()[0] || null;
  }

  /* ---------- renderöinti ---------- */
  function renderHeader(n) {
    const p = hk(n);
    $("time").textContent = `${String(p.hh).padStart(2, "0")}.${String(p.mm).padStart(2, "0")}`;
    $("date").innerHTML = `<b>${WD_LONG[p.wd].replace(/^./, (x) => x.toUpperCase())}</b><span>${p.d}. ${MON[p.m - 1]}</span>`;
    if (p.ss === 0 || !$("price").innerHTML) renderPrice(n);
    $("week").textContent = `Viikko ${isoWeek(p.key)}`;
    $("brandSub").textContent = `${p.d}.${p.m}.${p.y}`;
    const night = forcedMode ? forcedMode === "yo" : (p.hh >= NIGHT_FROM || p.hh < NIGHT_TO);
    document.body.classList.toggle("night", night);
  }

  /* ---------- pörssisähkö (prices.json, julkinen) ---------- */
  function priceClass(c) { if (c == null || !isFinite(c)) return "p-none"; if (c < 5) return "p-green"; if (c <= 15) return "p-yellow"; if (c <= 30) return "p-orange"; return "p-red"; }
  function renderPrice(n) {
    const el = $("price"); if (!el) return;
    const t = n.getTime();
    const row = (PRICES?.hinnat || []).find((x) => { const a = Date.parse(x.alku); return a <= t && t < a + (PRICES.jakso_min || 15) * 60000; });
    const c = row ? row.c : null;
    el.className = "price " + priceClass(c);
    el.innerHTML = `<div class="pv">${c == null ? "–" : c.toFixed(2).replace(".", ",")}</div><div class="pu">c/kWh sis. alv</div>
      <div class="pu">${row ? `${hm(new Date(Date.parse(row.alku)))}–${hm(new Date(Date.parse(row.alku) + 15 * 60000))}` : "ei hintaa"}</div>
      <div class="plinks"><span class="plink" data-pmode="spot">käyrä</span><span class="plink fc" data-pmode="fc">ennuste</span></div>`;
    el.setAttribute("role", "button"); el.setAttribute("tabindex", "0");
    el.setAttribute("aria-label", "Näytä pörssisähkön hintakäyrä");
  }
  async function loadPrices() {
    try { const r = await fetch(`${PRICES_URL}?t=${Date.now()}`, { cache: "no-store" }); if (r.ok) PRICES = await r.json(); } catch (e) {}
    renderPrice(now());
    if (pricePopOpen) renderPricePop();
  }

  /* ---------- pörssisähkön hintakäyrä ja hintaennuste (leijuva ikkuna) ---------- */
  const PRICE_ICON = `<svg class="pl-ico" viewBox="0 0 16 12" aria-hidden="true"><path d="M1 11V7h3V4h3v3h3V1h3v6h2" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  const fmtC = (c, d = 1) => (c == null || !isFinite(c)) ? "–" : c.toFixed(d).replace(".", ",").replace("-", "−");
  let pricePopMode = "spot"; // "spot" = toteutunut pörssihinta, "fc" = hintaennuste
  function seriesSlots(rows, stepMin, fromMs, toMs) {
    const step = (stepMin || 15) * 60000, out = [];
    for (const x of rows || []) {
      const a = Date.parse(x.alku);
      if (Number.isFinite(a) && Number.isFinite(x.c) && a >= fromMs && a < toMs) out.push({ a, b: a + step, c: x.c });
    }
    return out.sort((p, q) => p.a - q.a);
  }
  const dayStart = (key) => midnight(key).getTime(), dayEnd = (key) => midnight(addDays(key, 1)).getTime();
  const spotSlots = (key) => seriesSlots(PRICES?.hinnat, PRICES?.jakso_min || 15, dayStart(key), dayEnd(key));
  const fcSlots = (key) => seriesSlots(FORECAST?.tunnit, FORECAST?.jakso_min || 60, dayStart(key), dayEnd(key));
  const slotsExpected = (key, stepMin) => (dayEnd(key) - dayStart(key)) / (stepMin * 60000);
  const spotReady = (key) => spotSlots(key).length >= 0.9 * slotsExpected(key, PRICES?.jakso_min || 15);
  function niceStep(range) {
    for (const st of [1, 2, 5, 10, 20, 25, 50, 100, 200, 500]) if (range / st <= 6) return st;
    return 1000;
  }
  function priceDayStats(slots) {
    if (!slots.length) return null;
    let mn = slots[0], mx = slots[0], sum = 0;
    for (const x of slots) { if (x.c < mn.c) mn = x; if (x.c > mx.c) mx = x; sum += x.c; }
    return { min: mn, max: mx, avg: sum / slots.length, n: slots.length };
  }
  function dayLabel(key, long) {
    const info = hk(new Date(dayStart(key) + 12 * 3600e3));
    return long ? `${WD_LONG[info.wd].replace(/^./, (c) => c.toUpperCase())} ${info.d}.${info.m}.` : `${WD[info.wd]} ${info.d}.${info.m}.`;
  }
  // days: [{key, slots, pending?: {title, sub}}]; opts.fc = ennuste (kursiivi, ~)
  function priceChartSvg(days, n, opts = {}) {
    const W = 940, H = 340, L = 50, R = 14, T = 30, B = 30;
    const fc = !!opts.fc, tl = fc ? "~" : "";
    const t0 = dayStart(days[0].key), t1 = dayEnd(days[days.length - 1].key);
    const all = days.flatMap((d) => d.slots);
    const vmax = Math.max(5, ...all.map((x) => x.c)), vmin = Math.min(0, ...all.map((x) => x.c));
    const st = niceStep(vmax - vmin);
    const yTop = Math.ceil(vmax / st) * st, yBot = Math.floor(vmin / st) * st;
    const X = (t) => L + (t - t0) / (t1 - t0) * (W - L - R);
    const Y = (c) => T + (yTop - c) / (yTop - yBot) * (H - T - B);
    const nowMs = n.getTime();
    let g = "";
    for (let v = yBot; v <= yTop + 1e-9; v += st) {
      g += `<line class="pc-grid${v === 0 ? " zero" : ""}" x1="${L}" x2="${W - R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"/>`;
      g += `<text class="pc-ylab" x="${L - 8}" y="${(Y(v) + 5).toFixed(1)}" text-anchor="end">${fmtC(v, 0)}</text>`;
    }
    g += `<text class="pc-unit" x="${L - 8}" y="${T - 14}" text-anchor="end">${tl}c/kWh</text>`;
    for (const [v, cls] of [[5, "p-yellow"], [15, "p-orange"], [30, "p-red"]]) {
      if (v < yTop) g += `<line class="pc-thr ${cls}" x1="${L}" x2="${W - R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"/>`;
    }
    for (const x of all) {
      const x0 = X(x.a), x1 = X(x.b), w = Math.max(1, x1 - x0 - (x1 - x0 > 3 ? (fc ? 2 : 0.8) : 0));
      const ya = Y(Math.max(x.c, 0)), yb = Y(Math.min(x.c, 0));
      const cur = x.a <= nowMs && nowMs < x.b, past = x.b <= nowMs;
      g += `<rect class="pc-bar ${priceClass(x.c)}${past ? " past" : ""}${cur ? " cur" : ""}" x="${(x0 + (fc ? 1 : 0)).toFixed(1)}" y="${ya.toFixed(1)}" width="${w.toFixed(2)}" height="${Math.max(1, yb - ya).toFixed(1)}" rx="${fc ? 2 : 0.8}"/>`;
    }
    days.forEach((d, i) => {
      const ds = dayStart(d.key), de = dayEnd(d.key);
      const every = days.length > 2 ? 6 : 3;
      for (let h = 0; h < 24; h += every) {
        const t = ds + h * 3600e3; if (t >= de) break;
        const x = X(t);
        g += `<line class="pc-tick" x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${H - B}" y2="${H - B + 5}"/>`;
        g += `<text class="pc-xlab" x="${x.toFixed(1)}" y="${H - B + 21}" text-anchor="${x < L + 6 ? "start" : "middle"}">${String(h).padStart(2, "0")}</text>`;
      }
      g += `<text class="pc-day${d.key === hk(n).key ? " today" : ""}" x="${((X(ds) + X(de)) / 2).toFixed(1)}" y="${T - 12}" text-anchor="middle">${esc(dayLabel(d.key, true))}</text>`;
      if (i > 0) g += `<line class="pc-daysep" x1="${X(ds).toFixed(1)}" x2="${X(ds).toFixed(1)}" y1="${T - 30}" y2="${H - B + 6}"/>`;
      if (d.pending) {
        const known = d.slots.reduce((m, x) => Math.max(m, x.b), ds);
        const cx = (X(known) + X(de)) / 2, cy = (T + H - B) / 2;
        g += `<rect class="pc-pending" x="${(X(known) + 4).toFixed(1)}" y="${T + 34}" width="${Math.max(0, X(de) - X(known) - 8).toFixed(1)}" height="${(H - B - T - 40).toFixed(1)}" rx="12"/>`;
        g += `<text class="pc-pendtxt" x="${cx.toFixed(1)}" y="${(cy + 4).toFixed(1)}" text-anchor="middle">${esc(d.pending.title)}</text>`;
        if (d.pending.sub) g += `<text class="pc-pendtxt sub" x="${cx.toFixed(1)}" y="${(cy + 26).toFixed(1)}" text-anchor="middle">${esc(d.pending.sub)}</text>`;
      }
    });
    g += `<text class="pc-xlab" x="${X(t1).toFixed(1)}" y="${H - B + 21}" text-anchor="end">24</text>`;
    g += `<line class="pc-axis" x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}"/>`;
    if (nowMs >= t0 && nowMs < t1) {
      const x = X(nowMs);
      const cur = all.find((s) => s.a <= nowMs && nowMs < s.b);
      g += `<line class="pc-now" x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${T - 2}" y2="${H - B}"/>`;
      const txt = `nyt ${hm(n)}${cur ? ` · ${tl}${fmtC(cur.c, 2)} c` : ""}`;
      const tw = txt.length * 8.2 + 18, anchorLeft = x + tw + 8 > W - R;
      const bx = anchorLeft ? x - tw - 6 : x + 6;
      g += `<rect class="pc-nowbox" x="${bx.toFixed(1)}" y="${T + 2}" width="${tw.toFixed(0)}" height="24" rx="12"/>`;
      g += `<text class="pc-nowtxt" x="${(bx + tw / 2).toFixed(1)}" y="${T + 19}" text-anchor="middle">${esc(txt)}</text>`;
      g += `<circle class="pc-nowdot" cx="${x.toFixed(1)}" cy="${T - 2}" r="5"/>`;
    }
    return `<svg class="pc-svg${fc ? " fc-chart" : ""}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${fc ? "Pörssisähkön hintaennuste tunneittain" : "Pörssisähkön hinta 15 minuutin jaksoissa"}">${g}</svg>`;
  }
  function statsCard(name, s, fc, missingText) {
    const tl = fc ? "~" : "";
    if (!s) return `<div class="pp-day missing"><div class="pp-name">${name}</div><div class="pp-miss">${esc(missingText)}</div></div>`;
    return `<div class="pp-day${fc ? " fc" : ""}"><div class="pp-name">${name}</div><div class="pp-vals">
        <span class="pp-v"><i class="${priceClass(s.min.c)}"></i>min <b>${tl}${fmtC(s.min.c)}</b> <small>klo ${hm(new Date(s.min.a))}</small></span>
        <span class="pp-v"><i class="${priceClass(s.avg)}"></i>ka <b>${tl}${fmtC(s.avg)}</b></span>
        <span class="pp-v"><i class="${priceClass(s.max.c)}"></i>max <b>${tl}${fmtC(s.max.c)}</b> <small>klo ${hm(new Date(s.max.a))}</small></span>
      </div></div>`;
  }
  const LEGEND = (src) => `<div class="pp-legend"><span><i class="p-green"></i>alle 5</span><span><i class="p-yellow"></i>5–15</span><span><i class="p-orange"></i>15–30</span><span><i class="p-red"></i>yli 30 c/kWh</span><span class="pp-src">${src}</span></div>`;
  function renderSpotPop(n, body, meta) {
    const today = hk(n).key, tomorrow = addDays(today, 1);
    const dT = { key: today, slots: spotSlots(today) }, dN = { key: tomorrow, slots: spotSlots(tomorrow) };
    const tomorrowReady = spotReady(tomorrow);
    if (!tomorrowReady) dN.pending = { title: "Huomisen hinnat", sub: "tulevat iltapäivällä (n. klo 14–16)" };
    const cur = dT.slots.find((s) => s.a <= n.getTime() && n.getTime() < s.b);
    const step = PRICES?.jakso_min || 15;
    meta.innerHTML = (cur ? `<span class="pp-now ${priceClass(cur.c)}">Nyt ${fmtC(cur.c, 2)} c/kWh <small>${hm(new Date(cur.a))}–${hm(new Date(cur.b))}</small></span>` : "")
      + `<span>sis. alv 25,5 % · ${step} min jaksot</span>`;
    if (!dT.slots.length && !dN.slots.length) { body.innerHTML = `<div class="empty">Hintatietoja ei ole juuri nyt saatavilla.</div>`; return; }
    body.innerHTML = `<div class="pc-wrap">${priceChartSvg([dT, dN], n)}</div><div class="pp-stats">`
      + statsCard(`Tänään <small>${dayLabel(today)}</small>`, priceDayStats(dT.slots), false, "Hintatietoja ei saatavilla.")
      + statsCard(`Huomenna <small>${dayLabel(tomorrow)}</small>`, tomorrowReady ? priceDayStats(dN.slots) : null, false, "Huomisen hinnat julkaistaan iltapäivällä (n. klo 14–16).")
      + `</div>` + LEGEND("Lähde: api.porssisahko.net");
  }
  function forecastDays(n) {
    let k = hk(n).key;
    for (let i = 0; i < 3 && spotReady(k); i++) k = addDays(k, 1); // ensimmäinen päivä ilman toteutunutta hintaa
    return [k, addDays(k, 1), addDays(k, 2)];
  }
  function renderFcPop(n, body, meta) {
    const keys = forecastDays(n);
    const days = keys.map((key) => {
      const d = { key, slots: fcSlots(key) };
      if (d.slots.length < 0.9 * slotsExpected(key, FORECAST?.jakso_min || 60)) d.pending = { title: "Ei ennustetta", sub: d.slots.length ? "vain osa tunneista" : "" };
      return d;
    });
    const haettu = FORECAST?.haettu ? new Date(FORECAST.haettu) : null;
    meta.innerHTML = `<span class="pp-fc">Ennuste · ${esc(dayLabel(keys[0]))}–${esc(dayLabel(keys[2]))}</span>`
      + `<span>sis. alv 25,5 % · tunneittain${haettu && !isNaN(haettu) ? ` · päivitetty ${haettu.getDate()}.${haettu.getMonth() + 1}. klo ${hm(haettu)}` : ""}</span>`;
    if (!days.some((d) => d.slots.length)) { body.innerHTML = `<div class="empty">Hintaennustetta ei ole juuri nyt saatavilla.</div>`; return; }
    const rel = (key) => { const diff = Math.round((dayStart(key) - dayStart(hk(n).key)) / 864e5); return diff === 1 ? "Huomenna" : diff === 2 ? "Ylihuomenna" : dayLabel(key, true).split(" ")[0]; };
    const sub = (key) => { const diff = Math.round((dayStart(key) - dayStart(hk(n).key)) / 864e5); return diff <= 2 ? dayLabel(key) : dayLabel(key).split(" ")[1]; };
    body.innerHTML = `<div class="pc-wrap fc">${priceChartSvg(days, n, { fc: true })}</div><div class="pp-stats three">`
      + days.map((d) => statsCard(`${rel(d.key)} <small>${sub(d.key)}</small>`, d.pending ? null : priceDayStats(d.slots), true, "Ennustetta ei saatavilla.")).join("")
      + `</div>` + LEGEND("Ennuste: sahkovatkain.web.app · suuntaa-antava");
  }
  function renderPricePop() {
    const body = $("pricePopBody"), meta = $("pricePopMeta");
    if (!body) return;
    document.querySelectorAll("#pricePop .pp-tab").forEach((t) => {
      const on = t.dataset.pmode === pricePopMode;
      t.classList.toggle("is-active", on);
      if (on) t.setAttribute("aria-current", "page"); else t.removeAttribute("aria-current");
    });
    $("pricePop").classList.toggle("is-fc", pricePopMode === "fc");
    const n = now();
    if (pricePopMode === "fc") renderFcPop(n, body, meta); else renderSpotPop(n, body, meta);
    enhanceScrollAll();
  }
  function openPricePop(mode) {
    if (openDayKey) closeDayPop();
    pricePopMode = mode === "fc" ? "fc" : "spot";
    pricePopOpen = true;
    renderPricePop();
    const pop = $("pricePop"); if (pop) pop.hidden = false;
    enhanceScrollAll();
    startIdleTimer();
  }
  function closePricePop() {
    if (!pricePopOpen) return;
    pricePopOpen = false;
    const pop = $("pricePop"); if (pop) pop.hidden = true;
    if (currentView === "paiva" && !infoPopMode) stopIdleTimer();
  }

  /* ---------- Tänään / Muistutukset / Muistilista / Ruokalista: koko sisältö leijuvaan ikkunaan ---------- */
  const CARD_LINK = (txt) => `<span class="card-link" aria-hidden="true"><span class="cl-txt">${esc(txt)}</span><span class="cl-arr">›</span></span>`;
  const INFO_CARDS = { today: "tanaan", reminders: "muistutukset", todo: "muistilista", menu: "ruokalista" };
  function daysFrom(todayKey, key) { return Math.round((midnight(key) - midnight(todayKey)) / 864e5); }
  function relDay(days) {
    if (days === 0) return "tänään"; if (days === 1) return "huomenna"; if (days === -1) return "eilen";
    return days > 0 ? `${days} pv päästä` : `${-days} pv sitten`;
  }
  function renderTodayPop(n) {
    const key = hk(n).key, info = keyInfo(key);
    const evs = eventsForDay(key);
    const holidays = evs.filter(isHolidayEv);
    const hol = holidays.map((e) => esc(e.otsikko)).join(" · ");
    const dateStr = `${WD_LONG[info.wd].replace(/^./, (x) => x.toUpperCase())} ${info.d}. ${MON[info.m - 1]}`;
    const fc = dayPriceBadge(key, key, "today");
    const meta = `<span>${esc(dateStr)} · Viikko ${isoWeek(key)}</span>`
      + (hol ? `<span class="holiday">${hol}</span>` : "")
      + `<span>${evs.length ? `${evs.length} ${evs.length === 1 ? "merkintä" : "merkintää"}` : "ei merkintöjä"}</span>`
      + fc;
    if (!evs.length) return { title: "Tänään", meta, body: `<div class="ip-empty">Ei merkintöjä tälle päivälle.</div>` };
    const longs = evs.filter((e) => e.long), timed = evs.filter((e) => !e.long);
    let body = `<div class="dp-list">`;
    for (const e of longs) {
      const who = evWho(e);
      const sub = [e.sub || "koko päivä", who, e.paikka, e.alustava ? "alustava" : ""].filter(Boolean).join(" · ");
      body += `<div class="dp-banner${e.alustava ? " tent" : ""}" style="background:${evColor(e)}22;border-left:6px solid ${evColor(e)}">${esc(e.otsikko)}<span class="sub">${esc(sub)}</span></div>`;
    }
    let nowShown = false;
    for (const e of timed) {
      const past = e.b <= n, cur = e.a <= n && e.b > n;
      if (!nowShown && !past) { body += `<div class="nowline">nyt ${hm(n)}</div>`; nowShown = true; }
      const who = evWho(e);
      const extra = [who, e.paikka, e.alustava ? "alustava" : ""].filter(Boolean).join(" · ");
      body += `<div class="dp-ev${past ? " past" : ""}${cur ? " now" : ""}${e.alustava ? " tent" : ""}"><div class="t">${esc(evRange(e))}</div>
        <div class="body" style="border-color:${evColor(e)}"><div class="title">${badges(e)}${esc(e.otsikko)}${puokkari(e)}</div>
        ${extra ? `<div class="who">${esc(extra)}</div>` : ""}</div></div>`;
    }
    if (!nowShown && timed.length) body += `<div class="nowline">nyt ${hm(n)}</div>`;
    body += `</div>`;
    return { title: "Tänään", meta, body };
  }
  function remRowHtml(x, todayKey) {
    let d = "–", sm = "";
    if (x.pvm) { d = shortDate(x.pvm); sm = relDay(daysFrom(todayKey, x.pvm)); }
    const kid = x.lapsi ? member(String(x.lapsi).toLowerCase()) : null;
    const kidTag = kid ? `<span class="ip-kid" style="background:${kid.vari}">${esc(kid.tunnus)}</span><span>${esc(kid.nimi)}</span>` : "";
    return `<div class="ip-rem${x.pvm === todayKey ? " today" : ""}"><div class="d">${esc(d)}${sm ? `<small>${esc(sm)}</small>` : ""}</div>
      <div class="b"><div class="x">${esc(x.otsikko)}</div><div class="src">${kidTag}${kid && x.lahde ? "<span>·</span>" : ""}${x.lahde ? `<span>${esc(x.lahde)}</span>` : ""}${!kid && !x.lahde ? "<span>muistutus</span>" : ""}</div></div></div>`;
  }
  function renderRemindersPop(n) {
    const r = DATA?.muistutukset, todayKey = hk(n).key;
    if (!r || r.tila !== "ok") return { title: "Muistutukset", meta: "", body: `<div class="empty">Muistutukset eivät ole juuri nyt saatavilla.</div>` };
    const all = (r.kohteet || []).slice().sort((a, b) => (a.pvm || "9999") < (b.pvm || "9999") ? -1 : (a.pvm || "9999") > (b.pvm || "9999") ? 1 : 0);
    const upcoming = all.filter((x) => !x.pvm || x.pvm >= todayKey);
    const past = all.filter((x) => x.pvm && x.pvm < todayKey).reverse(); // uusin mennyt ensin
    const meta = `<span>${upcoming.length} tulossa</span>${past.length ? `<span>${past.length} mennyttä</span>` : ""}`;
    if (!all.length) return { title: "Muistutukset", meta: "", body: `<div class="ip-empty">Ei muistutuksia.</div>` };
    let body = `<div class="dp-sec-title">Tulossa</div>`;
    body += upcoming.length ? `<div class="ip-list">${upcoming.map((x) => remRowHtml(x, todayKey)).join("")}</div>` : `<div class="ip-empty">Ei avoimia muistutuksia.</div>`;
    if (past.length) body += `<div class="dp-sec-title ip-past-title">Menneet</div><div class="ip-list past">${past.map((x) => remRowHtml(x, todayKey)).join("")}</div>`;
    return { title: "Muistutukset", meta, body };
  }
  function renderTodoPop() {
    const t = DATA?.muistilista;
    if (!t || t.tila !== "ok") return { title: "Muistilista", meta: "", body: `<div class="empty">Muistilista ei ole juuri nyt saatavilla.</div>` };
    const open = (t.kohteet || []).filter((x) => !x.tehty), done = (t.kohteet || []).filter((x) => x.tehty);
    const meta = `<span>${open.length} tekemättä</span><span>${done.length} tehty</span><span class="ip-ro">vain luku · muokkaus Google Keepissä</span>`;
    if (!open.length && !done.length) return { title: "Muistilista", meta, body: `<div class="ip-empty">Lista on tyhjä.</div>` };
    const row = (x) => `<div class="ip-todo${x.tehty ? " done" : ""}"><span class="box">${x.tehty ? "✓" : ""}</span><span class="txt">${esc(x.teksti)}</span></div>`;
    let body = open.length ? `<div class="ip-list">${open.map(row).join("")}</div>` : `<div class="ip-empty">Kaikki tehty!</div>`;
    if (done.length) body += `<div class="dp-sec-title ip-past-title">Tehdyt</div><div class="ip-list">${done.map(row).join("")}</div>`;
    return { title: "Muistilista", meta, body };
  }
  function renderMenuPop(n) {
    const todayKey = hk(n).key, mon = mondayOfIsoWeek(todayKey), sun = addDays(mon, 6);
    const a = keyInfo(mon), b = keyInfo(sun);
    const lists = DATA?.ruokalistat || [];
    const meta = `<span>Viikko ${isoWeek(todayKey)} · ${a.d}.${a.m}.–${b.d}.${b.m}.</span><span>ateriat hoitoaikojen mukaan</span>`;
    if (!lists.length) return { title: "Ruokalista", meta, body: `<div class="empty">Ruokalistoja ei saatu.</div>` };
    let body = `<div class="ip-week">`;
    for (let i = 0; i < 7; i++) {
      const key = addDays(mon, i), info = keyInfo(key), menu = dayMenu(key);
      const isToday = key === todayKey, past = key < todayKey;
      const holiday = isHolidayKey(key), weekend = info.wd === 0 || info.wd === 6;
      const shifts = careShiftsOn(key);
      const shiftHtml = shifts.map((e) => `<span class="ip-shift">${badges(e)}<b>${esc(hm(e.a))}–${esc(hm(e.b))}</b>${puokkari(e)}</span>`).join("");
      let right;
      if (!menu.care) right = `<div class="ip-nocare">Ei hoitopäivä</div>`;
      else if (!menu.meals.length) right = `<div class="ip-nocare">Ei ruokalistaa tälle päivälle</div>`;
      else {
        const multi = menu.sources.length > 1;
        right = menu.meals.map((m) => {
          const row = mealRowHtml(m, "dp-meal ip-meal");
          return multi ? row.replace(/<\/div><\/div>$/, `<span class="ip-msrc">${esc(m.otsikko)}</span></div></div>`) : row;
        }).join("");
      }
      body += `<div class="ip-day${menu.care ? "" : " nocare"}${isToday ? " today" : ""}${past ? " past" : ""}${weekend || holiday ? " weekend" : ""}" ${isToday ? 'id="ipToday"' : ""}>
        <div class="ip-dl"><b>${esc(WD_LONG[info.wd].replace(/^./, (c) => c.toUpperCase()))}</b><span>${info.d}.${info.m}.${isToday ? " · tänään" : ""}</span>
          ${shiftHtml ? `<div class="ip-shifts">${shiftHtml}</div>` : ""}
          ${menu.sources.length ? `<div class="ip-src">${esc(menu.sources.join(" · "))}</div>` : ""}</div>
        <div class="ip-meals">${right}</div></div>`;
    }
    body += `</div>`;
    return { title: "Ruokalista", meta, body };
  }
  function renderInfoPop() {
    if (!infoPopMode) return;
    const n = now();
    const r = infoPopMode === "tanaan" ? renderTodayPop(n)
      : infoPopMode === "muistutukset" ? renderRemindersPop(n)
      : infoPopMode === "muistilista" ? renderTodoPop()
      : renderMenuPop(n);
    $("infoPopTitle").textContent = r.title;
    $("infoPopMeta").innerHTML = r.meta;
    const body = $("infoPopBody"), keep = body.scrollTop;
    body.innerHTML = r.body;
    body.scrollTop = keep;
    $("infoPop").dataset.mode = infoPopMode;
    enhanceScrollAll();
  }
  function openInfoPop(mode) {
    if (openDayKey) closeDayPop();
    closePricePop();
    infoPopMode = mode;
    $("infoPopBody").scrollTop = 0;
    renderInfoPop();
    $("infoPop").hidden = false;
    enhanceScrollAll();
    if (mode === "ruokalista") { // vieritä tähän päivään (kuluvan viikon loppu korostettuna)
      const t = $("ipToday"), body = $("infoPopBody");
      if (t && t.offsetTop > body.clientHeight * 0.5) body.scrollTop = t.offsetTop - 8;
    }
    startIdleTimer();
  }
  function closeInfoPop() {
    if (!infoPopMode) return;
    infoPopMode = null;
    $("infoPop").hidden = true;
    if (currentView === "paiva" && !pricePopOpen) stopIdleTimer();
  }
  async function loadForecast() {
    try { const r = await fetch(`forecast.json?t=${Date.now()}`, { cache: "no-store" }); if (r.ok) FORECAST = await r.json(); } catch (e) {}
    if (pricePopOpen && pricePopMode === "fc") renderPricePop();
  }
  function realizedDayAvg(key) {
    const slots = PRICES?.hinnat || [];
    if (!slots.length) return null;
    const step = (PRICES.jakso_min || 15) * 60000;
    const s = midnight(key).getTime(), e = midnight(addDays(key, 1)).getTime();
    const vals = [];
    for (const x of slots) {
      const a = Date.parse(x.alku);
      if (Number.isFinite(a) && a >= s && a < e && Number.isFinite(x.c)) vals.push(x.c);
    }
    const expect = Math.max(1, Math.round((e - s) / step));
    if (vals.length < expect * 0.9) return null;
    return vals.reduce((a, b) => a + b, 0) / vals.length;
  }
  function forecastDayAvg(key) {
    const row = (FORECAST?.paivat || []).find((d) => d.pvm === key);
    return (row && Number.isFinite(row.ka)) ? row.ka : null;
  }
  function dayPriceBadge(key, todayKey, mode) {
    if (!key || key < todayKey) return "";
    const real = realizedDayAvg(key);
    const c = (real != null) ? real : forecastDayAvg(key);
    if (c == null || !Number.isFinite(c)) return "";
    const tilde = (real == null) ? "~" : "";
    const txt = (mode === "today")
      ? `Sähkö ka ${tilde}${c.toFixed(2).replace(".", ",")} c`
      : `${tilde}${c.toFixed(1).replace(".", ",")} c`;
    return `<span class="fc ${priceClass(c)}${real != null ? " spot" : ""}${mode === "today" ? " ka" : ""}">${esc(txt)}</span>`;
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
    let html = `<div class="card-title">Tänään <small>${esc(shortDate(key))}</small>${dayPriceBadge(key, key, "today")}${CARD_LINK("kaikki")}</div><div class="ev-list">`;
    for (const e of longs) html += `<div class="banner${e.alustava ? " tent" : ""}" style="background:${evColor(e)}22;border-left:6px solid ${evColor(e)}">${esc(e.otsikko)}<span class="sub">${esc(e.sub || "koko päivä")} · ${esc(evWho(e))}</span></div>`;
    let nowShown = false, shown = 0;
    const MAX = Math.max(2, 7 - longs.length);
    for (const e of timed) {
      const past = e.b <= n, cur = e.a <= n && e.b > n;
      if (!nowShown && !past) { html += `<div class="nowline">nyt ${hm(n)}</div>`; nowShown = true; }
      if (shown >= MAX) continue;
      const end = e.endsAfter ? "" : (e.startsBefore ? "" : `<small>– ${hm(e.b)}</small>`);
      html += `<div class="ev${past ? " past" : ""}${cur ? " now" : ""}${e.alustava ? " tent" : ""}"><div class="t">${esc(e.time)}${end}</div>
        <div class="body" style="border-color:${evColor(e)}"><div class="title">${badges(e)}${esc(e.otsikko)}${puokkari(e)}</div><div class="who">${esc(evWho(e))}${e.paikka ? " · " + esc(e.paikka) : ""}${e.alustava ? " · alustava" : ""}</div></div></div>`;
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
      // Hoitovuorot yhdeksi tiiviiksi pilleriksi heti monipäiväisten jälkeen.
      const shifts = evs.filter((e) => e.hoitovuoro), rest = evs.filter((e) => !e.hoitovuoro);
      const items = [...rest.filter((e) => e.long), ...(shifts.length ? [{ shiftGroup: shifts }] : []), ...rest.filter((e) => !e.long)];
      const pills = items.slice(0, MAXP).map((e) => e.shiftGroup
        ? `<span class="pill" style="border-color:${evColor(e.shiftGroup[0])}">${e.shiftGroup.map((s) => `${badges(s)}<span class="pt">${esc(hm(s.a))}–${esc(hm(s.b))}</span>${puokkari(s)}`).join("&nbsp;&nbsp;")}</span>`
        : e.long
        ? `<span class="pill span${e.alustava ? " tent" : ""}" style="background:${evColor(e)}"><span class="pl">${esc(e.otsikko)}${e.sub ? ` <small style="opacity:.85;font-weight:700">· ${esc(e.sub)}</small>` : ""}</span></span>`
        : `<span class="pill${e.alustava ? " tent" : ""}" style="border-color:${evColor(e)}"><span class="pt">${esc(e.time)}</span><span class="pl">${esc(e.otsikko)}</span></span>`).join("");
      const extra = items.length - MAXP;
      const wx = w ? `${wIcon(w.koodi, 1)}<span>${deg(w.max)}</span>` : "";
      const fc = dayPriceBadge(key, todayKey);
      html += `<div class="day${info.wd === 0 || info.wd === 6 ? " weekend" : ""}"><div class="dl"><b>${label}</b><span class="dd">${info.d}.${info.m}.${wk}</span>${(wx || fc) ? `<span class="dw">${wx}${fc}</span>` : ""}</div>
        <div class="pills">${pills || '<span class="none">Ei merkintöjä</span>'}${extra > 0 ? `<span class="more">+${extra}</span>` : ""}</div></div>`;
    }
    $("upcoming").innerHTML = html + "</div>";
  }

  function renderMenu(n) {
    const lists = DATA?.ruokalistat || [];
    const p = hk(n);
    const todayKey = p.key;
    // Ennen klo 13 tämän päivän lista, sen jälkeen seuraava hoitopäivä. Ateriat suodatetaan hoitoajan mukaan.
    const target = p.hh < 13 ? todayKey : (nextCareDay(todayKey, false) || todayKey);
    const lbl = !target ? "" : target === todayKey ? "tänään" : target === addDays(todayKey, 1) ? `huomenna ${shortDate(target)}` : shortDate(target);
    const menu = dayMenu(target);
    const sub = menu.sources.join(" · ");
    let html = `<div class="card-title">Ruokalista <small>${esc(lbl)}</small>${CARD_LINK("koko viikko")}</div>`;
    if (sub) html += `<div class="menu-place">${esc(sub)}</div>`;
    if (!lists.length) html += `<div class="empty">Ruokalistoja ei saatu.</div>`;
    else if (!menu.care) html += `<div class="empty">Ei hoitopäivä</div>`;
    else if (!menu.meals.length) html += `<div class="empty">Ei ruokalistaa tälle päivälle.</div>`;
    else html += `<div class="meals">` + menu.meals.map((m) => mealRowHtml(m, "meal")).join("") + `</div>`;
    $("menu").innerHTML = html;
  }

  function renderReminders(n) {
    const r = DATA?.muistutukset;
    const todayKey = hk(n).key;
    let html = `<div class="card-title">Muistutukset${CARD_LINK("kaikki")}</div>`;
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
    let html = `<div class="card-title">Muistilista${CARD_LINK("kaikki")}</div>`;
    if (!t || t.tila !== "ok") html += `<div class="tulossa"><b>Tulossa</b>Google Keepin ”Muistilista” näkyy tässä, kun yhteys on valmis.</div>`;
    else {
      const open = t.kohteet.filter((x) => !x.tehty), done = t.kohteet.filter((x) => x.tehty);
      const items = [...open, ...done].slice(0, 6);
      if (!items.length) html += `<div class="empty">Lista on tyhjä.</div>`;
      html += items.map((x) => `<div class="todo-item${x.tehty ? " done" : ""}"><span class="box"></span><span class="txt">${esc(x.teksti)}</span></div>`).join("");
      if (t.kohteet.length > items.length) html += `<div class="more">+${t.kohteet.length - items.length} muuta</div>`;
    }
    $("todo").innerHTML = html;
  }

  function renderFoot() {
    const errs = (DATA?.virheet || []).map((e) => e.lahde);
    $("foot").innerHTML = `<span>Lähteet: Google-kalenteri · Open-Meteo (sää) · Kouvolan Aromi14 (ruokalistat) · eVaka (Arjen apuri)${errs.length ? " · virhe: " + esc(errs.join(", ")) : ""}</span><span>Yötila klo ${NIGHT_FROM}–0${NIGHT_TO} · <a href="#" id="forgetLink">unohda salasana</a></span>`;
  }

  function renderWeek(n) {
    const el = $("weekGrid"), title = $("weekTitle");
    if (!el || !title) return;
    const todayKey = hk(n).key;
    const mon = mondayOfIsoWeek(todayKey);
    const sun = addDays(mon, 6);
    const a = keyInfo(mon), b = keyInfo(sun);
    title.textContent = `Viikko ${isoWeek(todayKey)} · ${a.d}.${a.m}.–${b.d}.${b.m}.${b.y}`;
    const weather = Object.fromEntries((DATA?.saa?.paivat || []).map((d) => [d.pvm, d]));
    const MAX = 6;
    let html = "";
    for (let i = 0; i < 7; i++) {
      const key = addDays(mon, i), info = keyInfo(key), evs = eventsForDay(key), w = weather[key];
      const cls = ["week-day", key === todayKey ? "is-today" : "", key < todayKey ? "is-past" : "",
        (info.wd === 0 || info.wd === 6) ? "is-weekend" : "", evs.some(isHolidayEv) ? "is-holiday" : ""].filter(Boolean).join(" ");
      const fc = dayPriceBadge(key, todayKey);
      const wx = (w || fc) ? `<div class="wd-wx">${w ? `${wIcon(w.koodi, 1)}<span>${deg(w.max)}</span>` : ""}${fc}</div>` : "";
      const longs = evs.filter((e) => e.long), timed = evs.filter((e) => !e.long);
      const items = [...longs, ...timed];
      const menu = dayMenu(key);
      const lim = menu.meals.length ? Math.min(MAX, 4) : MAX;
      let list = "";
      for (const e of items.slice(0, lim)) {
        if (e.long) {
          const sub = e.sub && String(e.sub).includes("päättyy") ? ` <small style="opacity:.8">· ${esc(e.sub)}</small>` : "";
          list += `<div class="wv-banner${e.alustava ? " tent" : ""}" style="background:${evColor(e)}22;border-left:5px solid ${evColor(e)}">${esc(e.otsikko)}${sub}</div>`;
        } else {
          const past = e.b <= n, cur = e.a <= n && e.b > n;
          const end = (!e.endsAfter && !e.startsBefore) ? `–${hm(e.b)}` : "";
          list += `<div class="wv-ev${past ? " past" : ""}${cur ? " now" : ""}${e.alustava ? " tent" : ""}"><div class="t">${esc(e.time)}${esc(end)}</div>
            <div class="body" style="border-color:${evColor(e)}"><span class="title">${badges(e)}${esc(e.otsikko)}</span>${puokkari(e)}<div class="who">${esc(evWho(e))}</div></div></div>`;
        }
      }
      const extra = items.length - lim;
      if (extra > 0) list += `<div class="more">+${extra}</div>`;
      if (!items.length) list += `<div class="none">Ei merkintöjä</div>`;
      let meals = "";
      if (menu.care && menu.meals.length) {
        meals = `<div class="wd-meals">${menu.sources.length ? `<div class="wd-msrc">${esc(menu.sources.join(" · "))}</div>` : ""}` +
          menu.meals.map((m) => {
            const main = m.item.ruoat[0]?.nimi || "";
            const short = ({Aamupala:"Aamu",Lounas:"Lounas",Välipala:"Väli",Päivällinen:"Päivä",Iltapala:"Ilta"})[m.name] || m.name;
            const differ = m.kids.length !== m.allKids.length;
            const av = differ ? m.kids.map((k) => { const x = member(k); return `<span class="mini" style="background:${x.vari}">${esc(x.tunnus)}</span>`; }).join("") : "";
            return `<div class="wd-meal"><span class="mn">${esc(short)}</span><span class="tx">${av}${esc(main)}</span></div>`;
          }).join("") + `</div>`;
      } else if (!menu.care) {
        meals = `<div class="wd-meals"><div class="wd-nocare">Ei hoitopäivä</div></div>`;
      }
      html += `<div class="${cls}" data-day="${key}"><div class="wd-head"><span class="wd-name">${esc(WD[info.wd])}</span><span class="wd-num">${info.d}.</span></div>${wx}<div class="wv-list">${list}</div>${meals}</div>`;
    }
    el.innerHTML = html;
    enhanceScrollAll();
  }

  function renderMonth(n) {
    const el = $("monthGrid"), title = $("monthTitle");
    if (!el || !title) return;
    const p = hk(n), todayKey = p.key, y = p.y, m = p.m;
    title.textContent = `${MON_NOM[m - 1].replace(/^./, (x) => x.toUpperCase())} ${y}`;
    const start = mondayOfIsoWeek(`${y}-${String(m).padStart(2, "0")}-01`);
    const weather = Object.fromEntries((DATA?.saa?.paivat || []).map((d) => [d.pvm, d]));
    const MAXP = 3;
    let html = `<div></div>` + ["ma", "ti", "ke", "to", "pe", "la", "su"].map((s, i) =>
      `<div class="month-hd${i >= 5 ? " weekend" : ""}">${s}</div>`).join("");
    for (let r = 0; r < 6; r++) {
      const rowKey = addDays(start, r * 7);
      html += `<div class="month-wk">${isoWeek(rowKey)}</div>`;
      for (let c = 0; c < 7; c++) {
        const key = addDays(start, r * 7 + c), info = keyInfo(key), evs = eventsForDay(key), w = weather[key];
        const inMonth = info.m === m;
        const cls = ["month-cell", inMonth ? "" : "out", key === todayKey ? "is-today" : "",
          inMonth && key < todayKey ? "is-past" : "", (info.wd === 0 || info.wd === 6) ? "weekend" : "",
          evs.some(isHolidayEv) ? "is-holiday" : ""].filter(Boolean).join(" ");
        const wx = w ? `<span class="m-wx">${wIcon(w.koodi, 1)}</span>` : "";
        const items = [...evs.filter((e) => e.long), ...evs.filter((e) => !e.long && e.hoitovuoro), ...evs.filter((e) => !e.long && !e.hoitovuoro)];
        const pills = items.slice(0, MAXP).map((e) => {
          if (e.long) return `<span class="mpill span${e.alustava ? " tent" : ""}" style="background:${evColor(e)}">${esc(e.otsikko)}</span>`;
          if (e.hoitovuoro) {
            const mark = e.puokkari === true ? "Puokkari" : e.puokkari === false ? "Ei-puokkari" : esc(e.otsikko);
            return `<span class="mpill${e.alustava ? " tent" : ""}" style="border-color:${evColor(e)}">${badges(e)}${esc(e.time)} ${mark}</span>`;
          }
          return `<span class="mpill${e.alustava ? " tent" : ""}" style="border-color:${evColor(e)}">${esc(e.time)} ${esc(e.otsikko)}</span>`;
        }).join("");
        const extra = items.length - MAXP;
        html += `<div class="${cls}" data-day="${key}"><div class="m-top"><span class="m-date">${info.d}</span>${wx}</div><div class="m-pills">${pills}${extra > 0 ? `<span class="more">+${extra}</span>` : ""}</div></div>`;
      }
    }
    el.innerHTML = html;
    enhanceScrollAll();
  }

  /* ---------- haetun dataikkunan rajat (ei keksitä tapahtumia) ---------- */
  function coverageEnd() {
    const today = hk(now()).key;
    const keys = [today];
    for (const d of DATA?.saa?.paivat || []) if (d.pvm) keys.push(d.pvm);
    for (const e of DATA?.tapahtumat || []) {
      keys.push(hk(new Date(e.alku)).key);
      const b = new Date(e.loppu), bk = hk(b).key;
      keys.push(e.kokopaiva ? addDays(bk, -1) : bk);
    }
    for (const l of DATA?.ruokalistat || []) {
      for (const d of l.paivat || []) if (d.pvm) keys.push(d.pvm);
    }
    return keys.sort().at(-1);
  }
  function dayHasCoverage(key) {
    const today = hk(now()).key, end = coverageEnd();
    if (key >= today && key <= end) return true;
    if (key < today && eventsForDay(key).length) return true;
    return false;
  }

  /* ---------- päivän tarkempi ikkuna ---------- */
  function evRange(e) {
    if (e.long) return "";
    if (e.startsBefore && e.endsAfter) return "koko päivän";
    if (e.startsBefore) return `→ ${hm(e.b)}`;
    if (e.endsAfter) return `${hm(e.a)} →`;
    return `${hm(e.a)}–${hm(e.b)}`;
  }
  function renderDayPop(key) {
    const pop = $("dayPop"), title = $("dayPopTitle"), meta = $("dayPopMeta"), body = $("dayPopBody");
    if (!pop || !title || !meta || !body) return;
    const info = keyInfo(key);
    title.textContent = `${WD_LONG[info.wd].replace(/^./, (x) => x.toUpperCase())} ${info.d}. ${MON[info.m - 1]}`;
    const evs = eventsForDay(key);
    const holidays = evs.filter(isHolidayEv);
    const hol = holidays.map((e) => esc(e.otsikko)).join(" · ");
    meta.innerHTML = `<span>Viikko ${isoWeek(key)}</span>${hol ? `<span class="holiday">${hol}</span>` : ""}`;

    const w = (DATA?.saa?.paivat || []).find((d) => d.pvm === key);
    let html = "";
    const fcPop = dayPriceBadge(key, hk(now()).key);
    if (w || fcPop) {
      const rain = (w && w.sade_tn >= 30 && w.sade_mm >= 0.2) ? `<span class="rain">${w.sade_mm.toFixed(1).replace(".", ",")} mm</span>` : "";
      const wxbit = w ? `${wIcon(w.koodi, 1)}<div><div class="rng">${deg(w.max)} <span>/ ${deg(w.min)}</span></div>
        <div class="desc">${wText(w.koodi)} ${rain}</div></div>` : "";
      html += `<div class="dp-wx">${wxbit}${fcPop}</div>`;
    }

    const items = evs;
    html += `<div><div class="dp-sec-title">Tapahtumat</div>`;
    if (!items.length) {
      html += dayHasCoverage(key)
        ? `<div class="empty">Ei merkintöjä</div>`
        : `<div class="empty">Tapahtumia ei vielä haettu tälle päivälle</div>`;
    } else {
      html += `<div class="dp-list">`;
      for (const e of items) {
        const who = evWho(e);
        const extra = [who, e.paikka, e.alustava ? "alustava" : ""].filter(Boolean).join(" · ");
        if (e.long) {
          html += `<div class="dp-banner${e.alustava ? " tent" : ""}" style="background:${evColor(e)}22;border-left:6px solid ${evColor(e)}">${esc(e.otsikko)}<span class="sub">${esc(e.sub || "koko päivä")}${who ? " · " + esc(who) : ""}</span></div>`;
        } else {
          html += `<div class="dp-ev${e.alustava ? " tent" : ""}"><div class="t">${esc(evRange(e))}</div>
            <div class="body" style="border-color:${evColor(e)}"><div class="title">${badges(e)}${esc(e.otsikko)}${puokkari(e)}</div>
            <div class="who">${esc(extra)}</div></div></div>`;
        }
      }
      html += `</div>`;
    }
    html += `</div>`;

    const menu = dayMenu(key);
    html += `<div><div class="dp-sec-title">Ruokalista</div>`;
    if (menu.sources.length) html += `<div class="dp-menu-head"><span>${esc(menu.sources.join(" · "))}</span></div>`;
    if (!menu.care) html += `<div class="empty">Ei hoitopäivä</div>`;
    else if (!menu.meals.length) html += `<div class="empty">Ei ruokalistaa tälle päivälle.</div>`;
    else html += menu.meals.map((m) => mealRowHtml(m, "dp-meal")).join("");
    html += `</div>`;

    const r = DATA?.muistutukset;
    const rems = (r && r.tila === "ok") ? (r.kohteet || []).filter((x) => x.pvm === key) : [];
    if (rems.length) {
      html += `<div><div class="dp-sec-title">Muistutukset</div>`;
      for (const x of rems) {
        const kid = x.lapsi ? member(x.lapsi.toLowerCase()) : null;
        html += `<div class="rem"><div class="d">${esc(shortDate(key))}</div>
          <div><div class="x">${esc(x.otsikko)}</div><div class="src"><i style="background:${kid ? kid.vari : "var(--ink-3)"}"></i>${esc(x.lahde || "")}${kid ? " · " + esc(kid.nimi) : ""}</div></div></div>`;
      }
      html += `</div>`;
    }

    body.innerHTML = html;
    enhanceScrollAll();
  }
  function openDayPop(key) {
    if (!key) return;
    openDayKey = key;
    renderDayPop(key);
    const pop = $("dayPop");
    if (pop) pop.hidden = false;
    enhanceScrollAll();
    bumpIdle();
  }
  function closeDayPop() {
    openDayKey = null;
    const pop = $("dayPop");
    if (pop) pop.hidden = true;
  }

  /* ---------- näkymät (päivä / viikko / kuukausi) ja 30 s paluu ---------- */
  function viewFromHash() {
    const h = (location.hash || "").replace(/^#/, "").toLowerCase();
    return (h === "viikko" || h === "kuukausi") ? h : "paiva";
  }
  function stopIdleTimer() { if (idleTimer) { clearTimeout(idleTimer); idleTimer = null; } }
  function startIdleTimer() { stopIdleTimer(); idleTimer = setTimeout(() => { closePricePop(); closeInfoPop(); setView("paiva"); }, VIEW_IDLE_MS); }
  function bumpIdle() { if (currentView !== "paiva" || pricePopOpen || infoPopMode) startIdleTimer(); }
  function setView(view, fromHash) {
    if (view !== "viikko" && view !== "kuukausi") view = "paiva";
    if (view === "paiva") closeDayPop();
    if (view !== currentView) { closePricePop(); closeInfoPop(); }
    currentView = view;
    const want = view === "paiva" ? "" : "#" + view;
    if (!fromHash && (location.hash || "") !== want) {
      history.replaceState(null, "", location.pathname + location.search + want);
    }
    const day = $("dayView"), week = $("weekView"), month = $("monthView"), foot = $("foot");
    if (day) day.hidden = view !== "paiva";
    if (week) week.hidden = view !== "viikko";
    if (month) month.hidden = view !== "kuukausi";
    if (foot) foot.hidden = view !== "paiva";
    document.querySelectorAll(".view-link").forEach((a) => {
      const on = a.dataset.view === view;
      a.classList.toggle("is-active", on);
      if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    if (view !== "paiva" || pricePopOpen || infoPopMode) startIdleTimer(); else stopIdleTimer();
    if (DATA) {
      const nowV = now();
      if (view === "viikko") renderWeek(nowV);
      if (view === "kuukausi") renderMonth(nowV);
      if (openDayKey) renderDayPop(openDayKey);
    }
  }

  function renderAll() {
    const n = now();
    renderHeader(n); renderMembers(); renderStatus(n);
    if (!DATA) return;
    renderWeather(n); renderToday(n); renderUpcoming(n); renderMenu(n); renderReminders(n); renderTodo(); renderFoot();
    if (currentView === "viikko") renderWeek(n);
    if (currentView === "kuukausi") renderMonth(n);
    if (openDayKey) renderDayPop(openDayKey);
    if (pricePopOpen) renderPricePop();
    if (infoPopMode) renderInfoPop();
    enhanceScrollAll();
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

  // Uusi sivuversio julkaistu -> lataa sivu uudelleen välimuistin ohi.
  const APP_VERSION = document.querySelector('meta[name="app-version"]')?.content || "";
  async function checkVersion() {
    if (LOCAL_DEV || !APP_VERSION || APP_VERSION.startsWith("__")) return;
    try {
      const r = await fetch(`version.json?t=${Date.now()}`, { cache: "no-store" });
      if (!r.ok) return;
      const v = (await r.json()).v;
      if (v && v !== APP_VERSION) location.replace(`${location.pathname}?v=${v}${location.hash}`);
    } catch (e) {}
  }
  async function load() {
    checkVersion();
    const meta = Promise.all([loadPrices(), loadForecast()]);
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
    await meta;
    renderAll();
  }
  $("lockForm").addEventListener("submit", unlock);
  document.addEventListener("click", (e) => {
    if (e.target && e.target.id === "forgetLink") { e.preventDefault(); if (confirm("Unohdetaanko tallennettu salasana tältä laitteelta?")) forget(); return; }
    if (e.target && e.target.closest && e.target.closest("[data-daypop-close]")) { e.preventDefault(); closeDayPop(); return; }
    if (e.target && e.target.id === "dayPop") { closeDayPop(); return; }
    if (e.target && e.target.closest && e.target.closest("#dayPop")) return;
    if (e.target && e.target.closest && e.target.closest("[data-pricepop-close]")) { e.preventDefault(); closePricePop(); return; }
    if (e.target && e.target.id === "pricePop") { closePricePop(); return; }
    const tab = e.target && e.target.closest && e.target.closest("#pricePop .pp-tab");
    if (tab) { e.preventDefault(); pricePopMode = tab.dataset.pmode; renderPricePop(); startIdleTimer(); return; }
    if (e.target && e.target.closest && e.target.closest("#pricePop")) return;
    if (e.target && e.target.closest && e.target.closest("[data-infopop-close]")) { e.preventDefault(); closeInfoPop(); return; }
    if (e.target && e.target.id === "infoPop") { closeInfoPop(); return; }
    if (e.target && e.target.closest && e.target.closest("#infoPop")) return;
    const infoCard = currentView === "paiva" && e.target && e.target.closest && e.target.closest("#today, #reminders, #todo, #menu");
    if (infoCard && DATA) { if (_ptrDragged) return; e.preventDefault(); openInfoPop(INFO_CARDS[infoCard.id]); return; }
    if (e.target && e.target.closest && e.target.closest("#price")) { if (_ptrDragged) return; e.preventDefault(); const pl = e.target.closest("[data-pmode]"); openPricePop(pl ? pl.dataset.pmode : "spot"); return; }
    const cell = e.target.closest && e.target.closest("[data-day]");
    if (cell && (currentView === "viikko" || currentView === "kuukausi")) { if (_ptrDragged) return; openDayPop(cell.dataset.day); return; }
    if (e.target && e.target.closest && e.target.closest("[data-back]")) { e.preventDefault(); setView("paiva"); }
  });
  document.querySelector(".view-nav")?.addEventListener("click", (e) => {
    const a = e.target.closest(".view-link");
    if (!a) return;
    e.preventDefault();
    setView(a.dataset.view);
  });
  window.addEventListener("hashchange", () => setView(viewFromHash(), true));
  document.addEventListener("pointerdown", bumpIdle, true);
  document.addEventListener("keydown", (e) => {
    bumpIdle();
    if (e.key === "Escape" && openDayKey) { e.preventDefault(); closeDayPop(); }
    else if (e.key === "Escape" && pricePopOpen) { e.preventDefault(); closePricePop(); }
    else if (e.key === "Escape" && infoPopMode) { e.preventDefault(); closeInfoPop(); }
    else if ((e.key === "Enter" || e.key === " ") && e.target && INFO_CARDS[e.target.id] && DATA) { e.preventDefault(); openInfoPop(INFO_CARDS[e.target.id]); }
    else if ((e.key === "Enter" || e.key === " ") && e.target && e.target.id === "price") { e.preventDefault(); openPricePop(); }
  }, true);

  /* ---------- Näkymätön, dynaaminen scrollaus + reunahäive (t38u) ----------
     Kiinteäkokoisten laatikoiden sisältö scrollaa, kun se ei mahdu: ei scrollbaria,
     kosketus-/hiirirullatuki, ja pehmeä reunahäive kertoo, että sisältöä on lisää.
     Toimii dynaamisesti: ajetaan jokaisen renderöinnin jälkeen + ResizeObserver. */
  const SCROLL_CARDS = ["weather", "today", "menu", "upcoming", "reminders", "todo"];
  const _scrollRO = ("ResizeObserver" in window)
    ? new ResizeObserver(() => { for (const r of _scrollRegs) updateScrollHint(r.el, r.fade); })
    : null;
  function updateScrollHint(el, fade) {
    if (!el || !fade) return;
    const over = el.scrollHeight - el.clientHeight > 2;
    const atEnd = el.scrollTop + el.clientHeight >= el.scrollHeight - 2;
    fade.classList.toggle("has-more", over && !atEnd);
  }
  function makeScroll(el, fade) {
    if (!el) return;
    el.classList.add("scroll-hide");
    if (!el.dataset.scrollInit) {
      el.dataset.scrollInit = "1";
      el.addEventListener("scroll", () => updateScrollHint(el, el._fade), { passive: true });
    }
    el._fade = fade || null;
    _scrollRegs.push({ el, fade: fade || null });
    if (_scrollRO) { try { _scrollRO.observe(el); if (el.firstElementChild) _scrollRO.observe(el.firstElementChild); } catch (e) {} }
    updateScrollHint(el, fade || null);
  }
  function enhanceScrollAll() {
    if (_scrollRO) _scrollRO.disconnect();
    _scrollRegs = [];
    // 1) Päivänäkymän kortit: kääri otsikon jälkeinen sisältö scrollialueeseen.
    for (const id of SCROLL_CARDS) {
      const card = $(id);
      if (!card) continue;
      const title = card.querySelector(":scope > .card-title");
      let sc = card.querySelector(":scope > .card-scroll");
      if (!sc) {
        sc = document.createElement("div");
        sc.className = "card-scroll";
        const rest = Array.from(card.childNodes).filter((nd) => nd !== title);
        rest.forEach((nd) => sc.appendChild(nd));
        if (title) title.after(sc); else card.appendChild(sc);
      }
      card.classList.add("has-scroll");
      makeScroll(sc, card);
    }
    // 2) Popup-rungot: reunahäive itse korttiin, scrollbar piiloon.
    for (const sel of ["#dayPop", "#infoPop", "#pricePop"]) {
      const pop = document.querySelector(sel);
      if (!pop || pop.hidden) continue;
      const body = pop.querySelector(".daypop-body");
      if (body) makeScroll(body, pop.querySelector(".daypop-card"));
    }
    // 3) Viikko-/kuukausisolut: listat scrollattaviksi (ilman reunahäivettä, tilaa niukasti).
    document.querySelectorAll("#weekGrid .wv-list").forEach((el) => makeScroll(el, null));
    document.querySelectorAll("#monthGrid .m-pills").forEach((el) => makeScroll(el, null));
  }
  // Veto (scroll) ei saa avata popupia: erota napautus vedosta.
  document.addEventListener("pointerdown", (e) => { _ptrDown = { x: e.clientX, y: e.clientY }; _ptrDragged = false; }, true);
  document.addEventListener("pointermove", (e) => {
    if (!_ptrDown) return;
    if (Math.abs(e.clientX - _ptrDown.x) > 10 || Math.abs(e.clientY - _ptrDown.y) > 10) _ptrDragged = true;
  }, true);
  window.addEventListener("resize", () => { for (const r of _scrollRegs) updateScrollHint(r.el, r.fade); });

  // Kello tikittää sekunnin välein, muu näkymä päivittyy minuutin välein, data 5 min välein.
  renderHeader(now());
  setView(viewFromHash(), true);
  load();
  setInterval(() => renderHeader(now()), 1000);
  setInterval(renderAll, 60 * 1000);
  setInterval(load, REFRESH_MS);
  setTimeout(() => location.reload(), HARD_RELOAD_MS);
  // Pidä näyttö hereillä, jos selain tukee (Android Chrome).
  if ("wakeLock" in navigator) { const lock = () => navigator.wakeLock.request("screen").catch(() => {}); lock(); document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && lock()); }
})();
