(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const body = document.body || document.documentElement;
  const root = document.documentElement;

  const dom = {
    schoolLogo: $("schoolLogo"),
    schoolLogoFallback: $("schoolLogoFallback"),
    schoolName: $("schoolName"),
    dateG: $("dateGregorian"),
    dateH: $("dateHijri"),
    clock: $("clock"),
    alertContainer: $("alertContainer"),
    alertTitle: $("alertTitle"),
    alertDetails: $("alertDetails"),
    alertText: $("alertText"),
    badgeKind: $("badgeKind"),
    heroRange: $("heroRange"),
    heroTitle: $("heroTitle"),
    currentScheduleList: $("currentScheduleList"),
    circleProgress: $("circleProgress"),
    countdown: $("countdown"),
    progressBar: $("progressBar"),
    miniSchedule: $("miniSchedule"),
    nextLabel: $("nextLabel"),
    exSlot: $("exSlot"),
    exIndex: $("exIndex"),
    exTotal: $("exTotal"),
    pcCount: $("pcCount"),
    periodClassesTrack: $("periodClassesTrack"),
    sbCount: $("sbCount"),
    standbyTrack: $("standbyTrack"),
    fsBtn: $("fsBtn"),
  };

  function setVhVar() {
    try {
      const vh = (window.innerHeight || 0) * 0.01;
      if (vh > 0) root.style.setProperty("--vh", vh + "px");
    } catch (e) {}
  }
  setVhVar();
  window.addEventListener("resize", setVhVar, { passive: true });

  let REFRESH_EVERY = parseFloat(body.dataset.refresh || "10") || 10;
  let STANDBY_SPEED = parseFloat(body.dataset.standby || "0.8") || 0.8;
  let PERIODS_SPEED = parseFloat(body.dataset.periodsSpeed || "0.5") || 0.5;

  const MEDIA_PREFIX = (body.dataset.mediaPrefix || "/media/").toString().trim();
  const SNAPSHOT_URL = (body.dataset.snapshotUrl || "").toString().trim();
  const SERVER_TOKEN = ((body.dataset.apiToken || body.dataset.token || "").trim());

  function pickTokenFromUrl() {
    try {
      const qs = new URLSearchParams(window.location.search);
      return (qs.get("token") || qs.get("t") || "").trim();
    } catch (e) { return ""; }
  }

  function isDebug() {
    try { return new URLSearchParams(window.location.search).get("debug") === "1"; }
    catch (e) { return false; }
  }

  function getToken() {
    let t = SERVER_TOKEN;
    if (!t) t = pickTokenFromUrl();
    return (t || "").trim();
  }

  function resolveSnapshotUrl() {
    if (SNAPSHOT_URL) return SNAPSHOT_URL;
    const t = getToken();
    if (t) return "/api/display/snapshot/" + encodeURIComponent(t) + "/";
    return "/api/display/snapshot/";
  }

  function safeText(x) { return (x === null || x === undefined) ? "" : String(x); }
  function fmt2(n) { n = Number(n) || 0; return n < 10 ? "0" + n : String(n); }
  function clamp(n, a, b) { n = Number(n) || 0; return Math.max(a, Math.min(b, n)); }

  function normSpeed(x, def) {
    const v = Number(x);
    if (!isFinite(v) || v <= 0) return def;
    return clamp(v, 0.15, 4);
  }

  REFRESH_EVERY = clamp(REFRESH_EVERY, 5, 120);
  STANDBY_SPEED = normSpeed(STANDBY_SPEED, 0.8);
  PERIODS_SPEED = normSpeed(PERIODS_SPEED, 0.5);

  function resolveImageURL(raw) {
    if (!raw) return "";
    let s = String(raw).trim();
    if (!s) return "";
    if (/^data:image\//i.test(s) || /^blob:/i.test(s)) return s;
    if (/^https?:\/\//i.test(s)) return s.replace(/^http:\/\//i, "//").replace(/^https:\/\//i, "//");
    if (s.charAt(0) === "/") return s;
    let pref = MEDIA_PREFIX || "/media/";
    if (pref.charAt(pref.length - 1) !== "/") pref += "/";
    return pref + s.replace(/^\.?\/*/, "");
  }

  function toArabicDigits(v) {
    if (v === null || v === undefined) return "";
    return String(v).replace(/\d/g, (d) => "٠١٢٣٤٥٦٧٨٩"[Number(d)]);
  }

  function getPeriodIndex(periodObj) {
    if (!periodObj || typeof periodObj !== "object") return null;
    const raw = (periodObj.index ?? periodObj.period_index ?? periodObj.idx ?? periodObj.period
      ?? periodObj.period_no ?? periodObj.period_number ?? periodObj.periodNum ?? periodObj.slot_index ?? periodObj.order);
    if (raw === null || raw === undefined || raw === "") return null;
    const n = parseInt(String(raw), 10);
    if (isNaN(n) || n <= 0) return null;
    return n;
  }

  function formatPeriodTitle(p) {
    const idx = getPeriodIndex(p);
    if (!idx) return "حصة";
    return "حصة (" + toArabicDigits(idx) + ")";
  }

  let dbgEl = null;
  function ensureDebugOverlay() {
    if (!isDebug()) return;
    if (dbgEl) return;
    dbgEl = document.createElement("div");
    dbgEl.style.position = "fixed";
    dbgEl.style.bottom = "12px";
    dbgEl.style.right = "12px";
    dbgEl.style.zIndex = "99999";
    dbgEl.style.padding = "10px 12px";
    dbgEl.style.borderRadius = "12px";
    dbgEl.style.background = "rgba(0,0,0,0.55)";
    dbgEl.style.border = "1px solid rgba(255,255,255,0.18)";
    dbgEl.style.backdropFilter = "blur(8px)";
    dbgEl.style.fontFamily = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace";
    dbgEl.style.fontSize = "12px";
    dbgEl.style.direction = "ltr";
    dbgEl.style.color = "#fff";
    dbgEl.textContent = "debug…";
    document.body.appendChild(dbgEl);
  }
  function setDebugText(txt) { if (dbgEl) dbgEl.textContent = txt; }

  let serverOffsetMs = 0;
  function nowMs() { return Date.now() + serverOffsetMs; }

  function toTimeStr(t) {
    if (!t) return "--:--";
    const parts = String(t).split(":");
    if (parts.length < 2) return "--:--";
    return fmt2(parts[0]) + ":" + fmt2(parts[1]);
  }

  function hmToMs(hm, baseMs) {
    if (!hm) return null;
    const parts = String(hm).split(":");
    if (parts.length < 2) return null;
    const h = parseInt(parts[0], 10);
    const m = parseInt(parts[1], 10);
    if (isNaN(h) || isNaN(m)) return null;
    const d = new Date(baseMs || nowMs());
    return new Date(d.getFullYear(), d.getMonth(), d.getDate(), h, m, 0).getTime();
  }

  function isEnded(endHM, baseMs) {
    const end = hmToMs(endHM, baseMs);
    if (!end) return false;
    return (baseMs || nowMs()) >= end;
  }

  function isNowBetween(startHM, endHM, baseMs) {
    const s = hmToMs(startHM, baseMs);
    const e = hmToMs(endHM, baseMs);
    if (!s || !e) return false;
    const n = baseMs || nowMs();
    return n >= s && n < e;
  }

  function applyTheme(name) {
    let n = (name || "").toString().trim().toLowerCase();
    if (!n) n = "indigo";
    document.body.setAttribute("data-theme", n);
  }

  function hydrateBrand(payload) {
    try {
      const settings = (payload && payload.settings) || {};
      const name = safeText(settings.name || payload.school_name || "");
      const logo = resolveImageURL(settings.logo_url || payload.logo_url || "");
      if (name) document.title = name + " — لوحة العرض الذكية";
      if (dom.schoolName && name) dom.schoolName.textContent = name;

      if (dom.schoolLogo) {
        if (logo) {
          dom.schoolLogo.src = logo;
          dom.schoolLogo.classList.remove("hidden");
          if (dom.schoolLogoFallback) dom.schoolLogoFallback.classList.add("hidden");
        } else {
          dom.schoolLogo.classList.add("hidden");
          if (dom.schoolLogoFallback) dom.schoolLogoFallback.classList.remove("hidden");
        }
      }
    } catch (e) {}
  }

  let cachedDateInfo = null;

  function tickClock(dateInfo) {
    const now = new Date(nowMs());
    if (dom.clock) dom.clock.textContent = fmt2(now.getHours()) + ":" + fmt2(now.getMinutes()) + ":" + fmt2(now.getSeconds());
    if (dateInfo) cachedDateInfo = dateInfo;

    try {
      const arWeek = new Intl.DateTimeFormat("ar-SA", { weekday: "long" }).format(now);
      if (cachedDateInfo && (dom.dateG || dom.dateH)) {
        const g = cachedDateInfo.gregorian || {};
        const h = cachedDateInfo.hijri || {};
        if (dom.dateG) dom.dateG.textContent = arWeek + " ، " + (g.day || now.getDate()) + " " + (g.month_name || g.month || "") + " " + (g.year || now.getFullYear()) + "م";
        if (dom.dateH) dom.dateH.textContent = arWeek + " ، " + (h.day || "") + " " + (h.month_name || h.month || "") + " " + (h.year || "") + "هـ";
        return;
      }
      if (dom.dateG) dom.dateG.textContent = arWeek + " ، " + now.getDate() + " / " + (now.getMonth() + 1) + " / " + now.getFullYear() + "م";
    } catch (e) {
      if (dom.dateG) dom.dateG.textContent = now.toLocaleDateString("ar-SA");
    }
  }

  const CIRC_TOTAL = 339.292;
  let countdownSeconds = null;
  let progressRange = { start: null, end: null };
  let hasActiveCountdown = false;

  function setRing(pct) {
    if (!dom.circleProgress) return;
    const clamped = clamp(pct, 0, 100);
    const off = CIRC_TOTAL * (1 - clamped / 100);
    dom.circleProgress.style.strokeDashoffset = String(off);
  }

  let inflight = null;
  let ctrl = null;

  function withTimeout(promise, ms, onTimeout) {
    let t = null;
    const timeout = new Promise((_, rej) => {
      t = setTimeout(() => {
        try { if (onTimeout) onTimeout(); } catch (e) {}
        rej(new Error("timeout"));
      }, ms);
    });
    return Promise.race([promise, timeout]).finally(() => { if (t) clearTimeout(t); });
  }

  async function safeFetchSnapshot() {
    if (inflight) return inflight;

    const token = getToken();
    const baseUrl = resolveSnapshotUrl();

    const u = new URL(baseUrl, window.location.origin);
    u.searchParams.set("_t", String(Date.now()));

    if (ctrl) { try { ctrl.abort(); } catch (e) {} }
    ctrl = (window.AbortController ? new AbortController() : null);

    const fetchPromise = fetch(u.toString(), {
      method: "GET",
      headers: { "Accept": "application/json", "X-Display-Token": token || "" },
      cache: "no-store",
      signal: ctrl ? ctrl.signal : undefined,
    }).then(async (r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });

    inflight = withTimeout(fetchPromise, 9000, () => {
      if (ctrl) { try { ctrl.abort(); } catch (e) {} }
    }).catch((e) => {
      renderAlert("تعذر جلب البيانات", "تأكد من token ومن مسار snapshot.");
      ensureDebugOverlay();
      if (isDebug()) setDebugText("fetch error: " + (e && e.message ? e.message : String(e)));
      return null;
    }).finally(() => { inflight = null; });

    return await inflight;
  }

  function renderAlert(title, details) {
    const t = safeText(title || "");
    const d = safeText(details || "");
    if (dom.alertTitle) dom.alertTitle.textContent = t || "تنبيه";
    if (dom.alertDetails) dom.alertDetails.textContent = d || "—";
    if (dom.alertText && !dom.alertTitle && !dom.alertDetails) {
      dom.alertText.textContent = (t && d) ? (t + " — " + d) : (t || d || "");
    }
  }

  let annTimer = null;
  let annPtr = 0;
  let annList = [];
  let annSig = "";
  const ANN_INT = 6500;

  function annSignature(arr) {
    const a = Array.isArray(arr) ? arr : [];
    return JSON.stringify(a.map(x => {
      x = x || {};
      const title = safeText(x.title || x.heading || "");
      const body = safeText(x.body || x.details || x.text || x.message || "");
      const id = safeText(x.id || x.pk || "");
      return [id, title, body];
    }));
  }

  function renderAnnouncements(arr) {
    const nextSig = annSignature(arr);
    const nextList = Array.isArray(arr) ? arr.slice() : [];

    if (nextSig && nextSig === annSig && nextList.length) return;

    annSig = nextSig;
    annList = nextList;
    if (annTimer) { clearInterval(annTimer); annTimer = null; }

    if (!annList.length) {
      annPtr = 0;
      renderAlert("لا توجد تنبيهات حالياً", "—");
      return;
    }

    const current = annList[annPtr] || {};
    const curKey = safeText(current.title || current.heading || "") + "||" + safeText(current.body || current.details || current.text || current.message || "");
    let keepIndex = -1;

    for (let i = 0; i < annList.length; i++) {
      const x = annList[i] || {};
      const key = safeText(x.title || x.heading || "") + "||" + safeText(x.body || x.details || x.text || x.message || "");
      if (key && key === curKey) { keepIndex = i; break; }
    }

    annPtr = keepIndex >= 0 ? keepIndex : 0;
    showAnnouncement(annPtr);

    if (annList.length > 1) annTimer = setInterval(() => showAnnouncement(annPtr + 1), ANN_INT);
  }

  function showAnnouncement(i) {
    if (!annList.length) return;
    annPtr = (i + annList.length) % annList.length;
    const a = annList[annPtr] || {};
    const title = safeText(a.title || a.heading || "تنبيه");
    const body = safeText(a.body || a.details || a.text || a.message || "—");
    renderAlert(title, body);
  }

  let lastScheduleJSON = "";
  function renderMiniSchedule(payload, baseMs) {
    if (!dom.miniSchedule) return;

    const timeline = [];
    if (Array.isArray(payload.day_path)) {
      payload.day_path.forEach((x) => {
        if (!x) return;
        timeline.push({ start: x.from, end: x.to, label: x.label || "" });
      });
    }

    timeline.sort((a, b) => (hmToMs(a.start, baseMs) || 0) - (hmToMs(b.start, baseMs) || 0));

    const shown = timeline.filter((x) => !isEnded(x.end, baseMs));
    const json = JSON.stringify(shown);

    if (json !== lastScheduleJSON) {
      lastScheduleJSON = json;
      dom.miniSchedule.innerHTML = "";

      if (!shown.length) {
        dom.miniSchedule.innerHTML = '<div class="text-xs md:text-sm text-slate-400">لا يوجد جدول اليوم</div>';
      } else {
        shown.forEach((x, i) => {
          const chip = document.createElement("div");
          chip.id = "sched-item-" + i;
          chip.className = "flex-shrink-0 rounded-xl p-3 flex flex-col items-center justify-center min-w-[4.5rem] transition-all duration-300 bg-white/5 text-slate-300 border border-white/10";

          const timeSpan = document.createElement("span");
          timeSpan.className = "text-[10px] opacity-70 mb-1";
          timeSpan.textContent = toTimeStr(x.start);

          const labelSpan = document.createElement("span");
          labelSpan.className = "font-black text-base md:text-lg leading-none";
          labelSpan.textContent = safeText(x.label || "—");

          chip.appendChild(timeSpan);
          chip.appendChild(labelSpan);
          dom.miniSchedule.appendChild(chip);
        });
      }
    }

    shown.forEach((x, i) => {
      const el = document.getElementById("sched-item-" + i);
      if (!el) return;
      el.style.opacity = isNowBetween(x.start, x.end, baseMs) ? "1" : "0.65";
    });
  }

  const PERIODS_MIN_ITEMS_FOR_SCROLL = 4;
  const STANDBY_MIN_ITEMS_FOR_SCROLL = 4;

  let periodItemsCache = [];
  let standbyItemsCache = [];
  let periodAnimFrame = null;
  let sbAnimFrame = null;

  let lastPeriodSig = "";
  let lastStandbySig = "";

  function listSignature(items, kind) {
    const arr = Array.isArray(items) ? items : [];
    return JSON.stringify(arr.map((x) => {
      x = x || {};
      const cls = safeText(x.class_name || x["class"] || x.classroom || "");
      const subj = safeText(x.subject_name || x.subject || x.label || "");
      const teacher = safeText(x.teacher_name || x.teacher || x.teacher_full_name || "");
      const pidx = getPeriodIndex(x) || "";
      const extra = (kind === "standby") ? safeText(x.reason || x.note || "") : "";
      return [cls, subj, teacher, pidx, extra];
    }));
  }

  function findViewportForTrack(trackEl) {
    if (!trackEl) return null;
    let vp = trackEl.parentElement;
    while (vp && !vp.classList.contains("standby-viewport")) vp = vp.parentElement;
    return vp || null;
  }

  function startAutoScroll(trackEl, viewportEl, speed, minItems, itemsCache, frameRefSetter) {
    if (!trackEl || !viewportEl) return;

    trackEl.style.transform = "translateY(0)";
    while (trackEl.children.length > 1) trackEl.removeChild(trackEl.lastElementChild);

    const contentDiv = trackEl.firstElementChild;
    if (!contentDiv) return;

    const contentHeight = contentDiv.offsetHeight;
    const viewHeight = viewportEl.offsetHeight;

    const forceScroll = itemsCache && itemsCache.length >= minItems;
    if (!forceScroll && contentHeight <= viewHeight + 4) return;

    const clone = contentDiv.cloneNode(true);
    clone.setAttribute("aria-hidden", "true");
    trackEl.appendChild(clone);

    let y = 0;
    const maxStep = clamp(speed, 0.15, 4);

    function loop() {
      y += maxStep;
      if (y >= contentHeight) y = 0;
      trackEl.style.transform = "translateY(-" + y + "px)";
      frameRefSetter(requestAnimationFrame(loop));
    }

    frameRefSetter(requestAnimationFrame(loop));
  }

  function buildSlotItem({ clsName, subj, teacher, badgeText, badgeKind }) {
    const item = document.createElement("div");
    item.className = "slot-item";

    const top = document.createElement("div");
    top.className = "slot-top";

    const badges = document.createElement("div");
    badges.className = "slot-badges";

    const cls = document.createElement("span");
    cls.className = "slot-class";
    cls.textContent = safeText(clsName || "—");

    const subject = document.createElement("span");
    subject.className = "slot-subject";
    subject.textContent = safeText(subj || "—");

    badges.appendChild(cls);
    badges.appendChild(subject);

    const chip = document.createElement("span");
    chip.className = "chip num-font " + (badgeKind === "warn" ? "chip-warn" : "chip-ok");
    chip.textContent = safeText(badgeText || "حصة");

    top.appendChild(badges);
    top.appendChild(chip);

    const teacherRow = document.createElement("div");
    teacherRow.className = "slot-teacher";

    const lbl = document.createElement("span");
    lbl.className = "label";
    lbl.textContent = "المعلم/ـة:";

    const name = document.createElement("span");
    name.className = "name";
    name.textContent = safeText(teacher || "—");

    teacherRow.appendChild(lbl);
    teacherRow.appendChild(name);

    item.appendChild(top);
    item.appendChild(teacherRow);

    return item;
  }

  function renderPeriodClasses(items) {
    const arr = Array.isArray(items) ? items.slice() : [];
    const sig = listSignature(arr, "periods");

    if (sig && sig === lastPeriodSig) {
      periodItemsCache = arr.slice();
      if (dom.pcCount) dom.pcCount.textContent = String(arr.length);
      return;
    }

    lastPeriodSig = sig;
    periodItemsCache = arr.slice();

    if (dom.pcCount) dom.pcCount.textContent = String(arr.length);
    if (!dom.periodClassesTrack) return;

    if (periodAnimFrame) { cancelAnimationFrame(periodAnimFrame); periodAnimFrame = null; }
    dom.periodClassesTrack.innerHTML = "";
    dom.periodClassesTrack.style.transform = "translateY(0)";

    if (!arr.length) {
      dom.periodClassesTrack.innerHTML = '<div class="text-center text-xs md:text-sm text-slate-400 py-12">لا توجد حصص جارية</div>';
      return;
    }

    const list = document.createElement("div");
    list.className = "flex flex-col gap-3 pb-4";

    arr.forEach((x) => {
      x = x || {};
      const clsName = x.class_name || x["class"] || x.classroom || "—";
      const subj = x.subject_name || x.subject || x.label || "—";
      const teacher = x.teacher_name || x.teacher || "";
      const badgeText = formatPeriodTitle(x);

      list.appendChild(buildSlotItem({
        clsName,
        subj,
        teacher,
        badgeText,
        badgeKind: "ok",
      }));
    });

    dom.periodClassesTrack.appendChild(list);

    setTimeout(() => {
      const vp = findViewportForTrack(dom.periodClassesTrack);
      startAutoScroll(dom.periodClassesTrack, vp, PERIODS_SPEED, PERIODS_MIN_ITEMS_FOR_SCROLL, periodItemsCache, (id) => { periodAnimFrame = id; });
    }, 120);
  }

  function renderStandby(items) {
    const arr = Array.isArray(items) ? items.slice() : [];
    const sig = listSignature(arr, "standby");

    if (sig && sig === lastStandbySig) {
      standbyItemsCache = arr.slice();
      if (dom.sbCount) dom.sbCount.textContent = String(arr.length);
      return;
    }

    lastStandbySig = sig;
    standbyItemsCache = arr.slice();

    if (dom.sbCount) dom.sbCount.textContent = String(arr.length);
    if (!dom.standbyTrack) return;

    if (sbAnimFrame) { cancelAnimationFrame(sbAnimFrame); sbAnimFrame = null; }
    dom.standbyTrack.innerHTML = "";
    dom.standbyTrack.style.transform = "translateY(0)";

    if (!arr.length) {
      dom.standbyTrack.innerHTML = '<div class="text-center text-xs md:text-sm text-slate-400 py-12">لا توجد حصص انتظار</div>';
      return;
    }

    const contentDiv = document.createElement("div");
    contentDiv.className = "flex flex-col gap-3 pb-4";

    arr.forEach((x) => {
      x = x || {};
      const clsName = x.class_name || x["class"] || x.classroom || "—";
      const subj = x.subject_name || x.subject || x.label || "—";
      const teacher = x.teacher_name || x.teacher || x.teacher_full_name || "—";
      const badgeText = formatPeriodTitle(x);

      contentDiv.appendChild(buildSlotItem({
        clsName,
        subj,
        teacher,
        badgeText,
        badgeKind: "warn",
      }));
    });

    dom.standbyTrack.appendChild(contentDiv);

    setTimeout(() => {
      const vp = findViewportForTrack(dom.standbyTrack);
      startAutoScroll(dom.standbyTrack, vp, STANDBY_SPEED, STANDBY_MIN_ITEMS_FOR_SCROLL, standbyItemsCache, (id) => { sbAnimFrame = id; });
    }, 120);
  }

  let exTimer = null;
  let exPtr = 0;
  let exList = [];
  let exSig = "";
  const EX_INT = 7000;

  function exSignature(arr) {
    const a = Array.isArray(arr) ? arr : [];
    return JSON.stringify(a.map((e) => {
      e = e || {};
      const student = e.student || {};
      const teacher = e.teacher || {};
      const name = safeText(e.name || e.student_name || e.teacher_name || student.name || teacher.name || e.full_name || e.display_name || "");
      const reason = safeText(e.reason || e.note || e.message || e.title || "");
      const img = safeText(e.image_src || e.photo_url || e.image_url || e.photo || e.image || e.avatar ||
        student.photo_url || student.image_url || student.photo || student.image ||
        teacher.photo_url || teacher.image_url || teacher.photo || teacher.image || "");
      return [name, reason, img];
    }));
  }

  function renderExcellence(items) {
    const nextSig = exSignature(items);
    const nextList = Array.isArray(items) ? items.slice() : [];
    const filtered = nextList.filter((x) => x && (x.name || x.student_name || x.teacher_name || x.full_name || x.display_name || (x.student && x.student.name) || (x.teacher && x.teacher.name)));

    if (nextSig && nextSig === exSig && filtered.length) return;

    exSig = nextSig;
    exList = filtered;

    if (dom.exTotal) dom.exTotal.textContent = String(exList.length || 0);

    if (exTimer) { clearInterval(exTimer); exTimer = null; }
    if (!dom.exSlot) return;

    if (!exList.length) {
      if (dom.exIndex) dom.exIndex.textContent = "0";
      dom.exSlot.innerHTML = '<div class="h-full w-full flex items-center justify-center text-xs md:text-sm text-slate-300">لا يوجد متميزون حالياً</div>';
      return;
    }

    showExcellence(exPtr);
    if (exList.length > 1) exTimer = setInterval(() => showExcellence(exPtr + 1), EX_INT);
  }

  function showExcellence(i) {
    if (!exList.length || !dom.exSlot) return;

    exPtr = (i + exList.length) % exList.length;
    if (dom.exIndex) dom.exIndex.textContent = String(exPtr + 1);

    const e = exList[exPtr] || {};
    const student = e.student || {};
    const teacher = e.teacher || {};

    const name =
      e.name || e.student_name || e.teacher_name ||
      student.name || teacher.name ||
      e.full_name || e.display_name || "—";

    let reason = safeText(e.reason || e.note || e.message || e.title || "");
    if (reason.length > 180) reason = reason.slice(0, 177) + "…";

    const rawSrc =
      e.image_src || e.photo_url || e.image_url || e.photo || e.image || e.avatar ||
      student.photo_url || student.image_url || student.photo || student.image ||
      teacher.photo_url || teacher.image_url || teacher.photo || teacher.image;

    const src = resolveImageURL(rawSrc);

    dom.exSlot.style.opacity = "0";
    setTimeout(() => {
      dom.exSlot.innerHTML = "";

      const wrap = document.createElement("div");
      wrap.className = "honor-wrap";

      const img = document.createElement("img");
      img.alt = name;

      if (src) img.src = src;
      else img.src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Crect width='100%25' height='100%25' fill='%23222'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' fill='%23fff' font-size='28'%3E%F0%9F%8F%86%3C/text%3E%3C/svg%3E";

      const meta = document.createElement("div");
      meta.className = "honor-meta";

      const nm = document.createElement("div");
      nm.className = "honor-name";
      nm.textContent = name;

      const rs = document.createElement("div");
      rs.className = "honor-reason";
      rs.textContent = reason || "—";

      meta.appendChild(nm);
      meta.appendChild(rs);

      wrap.appendChild(img);
      wrap.appendChild(meta);

      dom.exSlot.appendChild(wrap);
      dom.exSlot.style.opacity = "1";
    }, 220);
  }

  function renderState(payload) {
    if (!payload) return;

    if (payload.now) {
      const serverMs = new Date(payload.now).getTime();
      if (!isNaN(serverMs)) serverOffsetMs = serverMs - Date.now();
    }

    const baseMs = nowMs();

    const settings = payload.settings || {};
    if (settings.theme) applyTheme(settings.theme);

    if (typeof settings.refresh_interval_sec === "number" && settings.refresh_interval_sec > 0) {
      const nInt = clamp(settings.refresh_interval_sec, 5, 120);
      if (Math.abs(nInt - REFRESH_EVERY) > 0.001) {
        REFRESH_EVERY = nInt;
        resetMainTimer();
      }
    }

    if (typeof settings.standby_scroll_speed === "number" && settings.standby_scroll_speed > 0) STANDBY_SPEED = normSpeed(settings.standby_scroll_speed, STANDBY_SPEED);
    if (typeof settings.periods_scroll_speed === "number" && settings.periods_scroll_speed > 0) PERIODS_SPEED = normSpeed(settings.periods_scroll_speed, PERIODS_SPEED);

    hydrateBrand(payload);
    tickClock(payload.date_info || null);

    const s = payload.state || {};
    const stType = s.type || "";

    let title = s.label || "لوحة العرض المدرسية";
    let range = (s.from || s.to) ? (toTimeStr(s.from) + " → " + toTimeStr(s.to)) : "--:-- → --:--";
    let badge = "حالة اليوم";

    countdownSeconds = null;
    progressRange = { start: null, end: null };
    hasActiveCountdown = false;

    if (typeof s.remaining_seconds === "number" && (stType === "period" || stType === "break" || stType === "before")) {
      countdownSeconds = Math.max(0, Math.floor(s.remaining_seconds));
      hasActiveCountdown = true;
    }

    if ((stType === "period" || stType === "break") && s.from && s.to) {
      const start = hmToMs(s.from, baseMs);
      const end = hmToMs(s.to, baseMs);
      if (start && end && end > start) {
        progressRange.start = start;
        progressRange.end = end;
      }
    }

    const current = payload.current_period || null;
    const nextP = payload.next_period || null;

    if (stType === "period") {
      badge = "درس";
      title = formatPeriodTitle(current);
    } else if (stType === "break") {
      badge = "استراحة";
      title = s.label || "استراحة";
    } else if (stType === "off") {
      badge = "عطلة";
      title = s.label || "يوم إجازة";
      range = "--:--";
    }

    if (dom.heroTitle) dom.heroTitle.textContent = safeText(title);
    if (dom.heroRange) dom.heroRange.textContent = safeText(range);
    if (dom.badgeKind) dom.badgeKind.textContent = safeText(badge);

    if (dom.nextLabel) {
      if (nextP && (nextP.from || nextP.to || nextP.label || nextP.index || nextP.period_index)) {
        const nextTitle = formatPeriodTitle(nextP);
        const from = toTimeStr(nextP.from);
        dom.nextLabel.textContent = from !== "--:--" ? (nextTitle + " (" + from + ")") : nextTitle;
      } else {
        dom.nextLabel.textContent = "—";
      }
    }

    if (dom.currentScheduleList) {
      dom.currentScheduleList.innerHTML = "";
      if (current && (current.label || current.from || current.to || current.index || current.period_index)) {
        const cls = safeText(current["class"] || current.class_name || "—");
        const subj = (stType === "period") ? formatPeriodTitle(current) : safeText(current.label || s.label || "—");
        const tRange = toTimeStr(current.from || s.from) + " → " + toTimeStr(current.to || s.to);

        const chip1 = document.createElement("span");
        chip1.className = "chip";
        chip1.textContent = cls;

        const chip2 = document.createElement("span");
        chip2.className = "chip";
        chip2.textContent = subj;

        const chip3 = document.createElement("span");
        chip3.className = "chip num-font";
        chip3.textContent = tRange;

        dom.currentScheduleList.appendChild(chip1);
        dom.currentScheduleList.appendChild(chip2);
        dom.currentScheduleList.appendChild(chip3);

        const t = document.createElement("div");
        t.className = "mt-2 text-white/90 font-black";
        t.style.fontSize = "var(--sub)";
        dom.currentScheduleList.appendChild(t);
      } else {
        dom.currentScheduleList.innerHTML = '<div class="w-full rounded-xl border border-slate-600/40 bg-slate-900/40 px-3 py-3 text-center text-slate-400 text-xs md:text-sm">لا توجد حصص حالية الآن</div>';
      }
    }

    renderMiniSchedule(payload, baseMs);
  }

  let tickerId = null;
  function startTicker() {
    if (tickerId) return;
    tickerId = setInterval(() => {
      tickClock();

      if (hasActiveCountdown && typeof countdownSeconds === "number") {
        if (countdownSeconds > 0) countdownSeconds -= 1;
      }

      if (dom.countdown) {
        if (hasActiveCountdown && typeof countdownSeconds === "number") {
          const mm = Math.floor(countdownSeconds / 60);
          const ss = countdownSeconds % 60;
          dom.countdown.textContent = fmt2(mm) + ":" + fmt2(ss);
        } else {
          dom.countdown.textContent = "--:--";
        }
      }

      if (dom.progressBar) {
        if (progressRange.start && progressRange.end && progressRange.end > progressRange.start) {
          const n = nowMs();
          let pct = ((n - progressRange.start) / (progressRange.end - progressRange.start)) * 100;
          pct = clamp(pct, 0, 100);
          dom.progressBar.style.width = pct.toFixed(1) + "%";
          setRing(pct);
        } else {
          dom.progressBar.style.width = "0%";
          setRing(0);
        }
      }
    }, 1000);
  }

  let mainTimer = null;
  function resetMainTimer() {
    if (mainTimer) clearInterval(mainTimer);
    mainTimer = setInterval(refreshAll, Math.max(5, REFRESH_EVERY) * 1000);
  }

  async function refreshAll() {
    const snap = await safeFetchSnapshot();
    if (!snap) return;

    try {
      renderState(snap);
      renderAnnouncements(snap.announcements || []);
      renderExcellence(snap.excellence || []);
      renderStandby(snap.standby || []);
      renderPeriodClasses(snap.period_classes || []);

      ensureDebugOverlay();
      if (isDebug()) {
        setDebugText(
          "ok " + new Date().toLocaleTimeString() +
          " | ann=" + (Array.isArray(snap.announcements) ? snap.announcements.length : 0) +
          " ex=" + (Array.isArray(snap.excellence) ? snap.excellence.length : 0) +
          " sb=" + (Array.isArray(snap.standby) ? snap.standby.length : 0) +
          " pc=" + (Array.isArray(snap.period_classes) ? snap.period_classes.length : 0)
        );
      }
    } catch (e) {
      renderAlert("حدث خطأ أثناء العرض", "افتح ?debug=1 لمزيد من التفاصيل.");
      ensureDebugOverlay();
      if (isDebug()) setDebugText("render error: " + (e && e.message ? e.message : String(e)));
    }
  }

  function requestFullscreenCompat(el) {
    if (!el) return Promise.reject();
    const fn = el.requestFullscreen || el.webkitRequestFullscreen || el.mozRequestFullScreen || el.msRequestFullscreen;
    if (!fn) return Promise.reject();
    try {
      const res = fn.call(el);
      return res && typeof res.then === "function" ? res : Promise.resolve();
    } catch (e) { return Promise.reject(e); }
  }

  function exitFullscreenCompat() {
    const d = document;
    const fn = d.exitFullscreen || d.webkitExitFullscreen || d.mozCancelFullScreen || d.msExitFullscreen;
    if (!fn) return Promise.reject();
    try {
      const res = fn.call(d);
      return res && typeof res.then === "function" ? res : Promise.resolve();
    } catch (e) { return Promise.reject(e); }
  }

  function isFullscreen() {
    const d = document;
    return !!(d.fullscreenElement || d.webkitFullscreenElement || d.mozFullScreenElement || d.msFullscreenElement);
  }

  function bindFullscreen() {
    if (!dom.fsBtn) return;
    dom.fsBtn.addEventListener("click", () => {
      if (!isFullscreen()) {
        requestFullscreenCompat(document.documentElement).catch(() => {});
      } else {
        exitFullscreenCompat().catch(() => {});
      }
    }, { passive: true });
  }

  let resizeT = null;
  window.addEventListener("resize", () => {
    if (resizeT) clearTimeout(resizeT);
    resizeT = setTimeout(() => {
      lastStandbySig = "";
      lastPeriodSig = "";
      if (standbyItemsCache.length) renderStandby(standbyItemsCache);
      if (periodItemsCache.length) renderPeriodClasses(periodItemsCache);
    }, 120);
  }, { passive: true });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) return;
    refreshAll();
  });

  document.addEventListener("DOMContentLoaded", () => {
    try {
      const initTheme = (body.dataset.theme || "").trim();
      if (initTheme) applyTheme(initTheme);
    } catch (e) {}

    ensureDebugOverlay();
    tickClock();
    startTicker();
    refreshAll();
    resetMainTimer();
    bindFullscreen();
  });
})();
