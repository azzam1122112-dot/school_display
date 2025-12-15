(function () {
  "use strict";

  // ===== Helpers =====
  const $ = (id) => document.getElementById(id);
  const root = document.documentElement;

  const safeText = (x) => (x === null || x === undefined ? "" : String(x));
  const fmt2 = (n) => {
    n = Number(n) || 0;
    return n < 10 ? "0" + n : String(n);
  };
  const clamp = (n, a, b) => {
    n = Number(n) || 0;
    return Math.max(a, Math.min(b, n));
  };

  function setTextIfChanged(el, next) {
    if (!el) return false;
    const v = safeText(next);
    if (el.textContent !== v) {
      el.textContent = v;
      return true;
    }
    return false;
  }

  function toggleHidden(el, hidden) {
    if (!el) return;
    if (hidden) el.classList.add("hidden");
    else el.classList.remove("hidden");
  }

  function toArabicDigits(v) {
    if (v === null || v === undefined) return "";
    return String(v).replace(/\d/g, (d) => "٠١٢٣٤٥٦٧٨٩"[Number(d)]);
  }

  function normSpeed(x, def) {
    const v = Number(x);
    if (!isFinite(v) || v <= 0) return def;
    return clamp(v, 0.15, 4);
  }

  function isDebug() {
    try {
      return new URLSearchParams(window.location.search).get("debug") === "1";
    } catch (e) {
      return false;
    }
  }

  // ===== DOM =====
  const dom = {};
  function bindDom() {
    dom.schoolLogo = $("schoolLogo");
    dom.schoolLogoFallback = $("schoolLogoFallback");
    dom.schoolName = $("schoolName");
    dom.dateG = $("dateGregorian");
    dom.dateH = $("dateHijri");
    dom.clock = $("clock");

    dom.alertTitle = $("alertTitle");
    dom.alertDetails = $("alertDetails");

    dom.badgeKind = $("badgeKind");
    dom.heroRange = $("heroRange");
    dom.heroTitle = $("heroTitle");
    dom.currentScheduleList = $("currentScheduleList");

    dom.circleProgress = $("circleProgress");
    dom.countdown = $("countdown");
    dom.progressBar = $("progressBar");

    dom.miniSchedule = $("miniSchedule");
    dom.nextLabel = $("nextLabel");

    dom.exSlot = $("exSlot");
    dom.exIndex = $("exIndex");
    dom.exTotal = $("exTotal");

    dom.pcCount = $("pcCount");
    dom.periodClassesTrack = $("periodClassesTrack");

    dom.sbCount = $("sbCount");
    dom.standbyTrack = $("standbyTrack");

    dom.fsBtn = $("fsBtn");
  }

  // ===== Viewport var =====
  function setVhVar() {
    try {
      const vh = (window.innerHeight || 0) * 0.01;
      if (vh > 0) root.style.setProperty("--vh", vh + "px");
    } catch (e) {}
  }

  // ===== Debug overlay =====
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
  function setDebugText(txt) {
    if (dbgEl) dbgEl.textContent = safeText(txt);
  }

  // ===== Config =====
  const cfg = {
    REFRESH_EVERY: 10,
    STANDBY_SPEED: 0.8,
    PERIODS_SPEED: 0.5,
    MEDIA_PREFIX: "/media/",
    SNAPSHOT_URL: "",
    SERVER_TOKEN: "",
  };

  function pickTokenFromUrl() {
    try {
      const qs = new URLSearchParams(window.location.search);
      return (qs.get("token") || qs.get("t") || "").trim();
    } catch (e) {
      return "";
    }
  }

  function getToken() {
    return (cfg.SERVER_TOKEN || pickTokenFromUrl() || "").trim();
  }

  function resolveSnapshotUrl() {
    if (cfg.SNAPSHOT_URL) return cfg.SNAPSHOT_URL;
    const t = getToken();
    if (t) return "/api/display/snapshot/" + encodeURIComponent(t) + "/";
    return "/api/display/snapshot/";
  }

  function resolveImageURL(raw) {
    if (!raw) return "";
    let s = String(raw).trim();
    if (!s) return "";
    if (/^data:image\//i.test(s) || /^blob:/i.test(s)) return s;
    if (/^https?:\/\//i.test(s)) return s.replace(/^https?:\/\//i, "//");
    if (s.charAt(0) === "/") return s;
    let pref = cfg.MEDIA_PREFIX || "/media/";
    if (pref.charAt(pref.length - 1) !== "/") pref += "/";
    return pref + s.replace(/^\.?\/*/, "");
  }

  // ===== Time helpers =====
  let serverOffsetMs = 0;
  function nowMs() {
    return Date.now() + serverOffsetMs;
  }

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

  // ===== Period index/title =====
  function getPeriodIndex(periodObj) {
    if (!periodObj || typeof periodObj !== "object") return null;
    const raw =
      periodObj.index ??
      periodObj.period_index ??
      periodObj.idx ??
      periodObj.period ??
      periodObj.period_no ??
      periodObj.period_number ??
      periodObj.periodNum ??
      periodObj.slot_index ??
      periodObj.order;

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

  function getCurrentPeriodIdxFromPayload(payload) {
    if (!payload) return null;
    const cur = payload.current_period || null;
    const n = getPeriodIndex(cur);
    if (n) return n;
    const st = payload.state || {};
    // أحيانًا يجي رقم الحصة داخل state
    const maybe = getPeriodIndex(st);
    return maybe || null;
  }

  // ===== Render: Alert =====
  function renderAlert(title, details) {
    setTextIfChanged(dom.alertTitle, title || "تنبيه");
    setTextIfChanged(dom.alertDetails, details || "—");
  }

  // ===== Render: Brand/Theme =====
  function applyTheme(name) {
    let n = (name || "").toString().trim().toLowerCase();
    if (!n) n = "indigo";
    document.body.setAttribute("data-theme", n);
  }

  const last = {
    brandSig: "",
    stateSig: "",
    currentSig: "",
    miniSig: "",
    annSig: "",
    exSig: "",
    pcSig: "",
    sbSig: "",
    nextSig: "",
  };

  function hydrateBrand(payload) {
    const settings = (payload && payload.settings) || {};
    const name = safeText(settings.name || payload.school_name || "");
    const logo = resolveImageURL(settings.logo_url || payload.logo_url || "");
    const theme = safeText(settings.theme || "");

    const sig = name + "||" + logo + "||" + theme;
    if (sig === last.brandSig) return;
    last.brandSig = sig;

    if (theme) applyTheme(theme);

    if (name) {
      document.title = name + " — لوحة العرض الذكية";
      setTextIfChanged(dom.schoolName, name);
    }

    if (dom.schoolLogo) {
      if (logo) {
        if (dom.schoolLogo.src !== logo) dom.schoolLogo.src = logo;
        toggleHidden(dom.schoolLogo, false);
        toggleHidden(dom.schoolLogoFallback, true);
      } else {
        toggleHidden(dom.schoolLogo, true);
        toggleHidden(dom.schoolLogoFallback, false);
      }
    }
  }

  // ===== Clock / Date =====
  let cachedDateInfo = null;
  function tickClock(dateInfo) {
    const now = new Date(nowMs());
    if (dom.clock) {
      setTextIfChanged(
        dom.clock,
        fmt2(now.getHours()) + ":" + fmt2(now.getMinutes()) + ":" + fmt2(now.getSeconds())
      );
    }
    if (dateInfo) cachedDateInfo = dateInfo;

    try {
      const arWeek = new Intl.DateTimeFormat("ar-SA", { weekday: "long" }).format(now);
      if (cachedDateInfo && (dom.dateG || dom.dateH)) {
        const g = cachedDateInfo.gregorian || {};
        const h = cachedDateInfo.hijri || {};
        if (dom.dateG) {
          setTextIfChanged(
            dom.dateG,
            arWeek +
              " ، " +
              (g.day || now.getDate()) +
              " " +
              (g.month_name || g.month || "") +
              " " +
              (g.year || now.getFullYear()) +
              "م"
          );
        }
        if (dom.dateH) {
          setTextIfChanged(
            dom.dateH,
            arWeek +
              " ، " +
              (h.day || "") +
              " " +
              (h.month_name || h.month || "") +
              " " +
              (h.year || "") +
              "هـ"
          );
        }
        return;
      }
      if (dom.dateG)
        setTextIfChanged(dom.dateG, arWeek + " ، " + now.getDate() + " / " + (now.getMonth() + 1) + " / " + now.getFullYear() + "م");
    } catch (e) {
      if (dom.dateG) setTextIfChanged(dom.dateG, now.toLocaleDateString("ar-SA"));
    }
  }

  // ===== Progress ring / bar =====
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

  // ===== Current chips =====
  function clearNode(el) {
    if (!el) return;
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function makeChip(text, extraClass) {
    const s = document.createElement("span");
    s.className = "chip" + (extraClass ? " " + extraClass : "");
    s.textContent = safeText(text || "—");
    return s;
  }

  function renderCurrentChips(stType, stateObj, currentObj) {
    if (!dom.currentScheduleList) return;

    const cur = currentObj || {};
    const cls = safeText(cur["class"] || cur.class_name || cur.classroom || "");
    const subj = stType === "period" ? formatPeriodTitle(cur) : safeText(cur.label || stateObj.label || "");
    const range = toTimeStr(cur.from || stateObj.from) + " → " + toTimeStr(cur.to || stateObj.to);

    const sig = cls + "||" + subj + "||" + range + "||" + stType;
    if (sig === last.currentSig) return;
    last.currentSig = sig;

    clearNode(dom.currentScheduleList);

    if (!cls && !subj && range.indexOf("--:--") >= 0) {
      const msg = document.createElement("div");
      msg.style.textAlign = "center";
      msg.style.opacity = "0.75";
      msg.style.padding = "10px 12px";
      msg.textContent = "لا توجد حصص حالية الآن";
      dom.currentScheduleList.appendChild(msg);
      return;
    }

    if (cls) dom.currentScheduleList.appendChild(makeChip(cls));
    if (subj) dom.currentScheduleList.appendChild(makeChip(subj));
    dom.currentScheduleList.appendChild(makeChip(range, "num-font"));
  }

  // ===== Mini schedule =====
  let miniItems = [];
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

    const sig = JSON.stringify(shown.map((x) => [x.start, x.end, x.label]));
    if (sig !== last.miniSig) {
      last.miniSig = sig;
      miniItems = [];
      clearNode(dom.miniSchedule);

      if (!shown.length) {
        const msg = document.createElement("div");
        msg.style.opacity = "0.75";
        msg.textContent = "لا يوجد جدول اليوم";
        dom.miniSchedule.appendChild(msg);
      } else {
        shown.forEach((x) => {
          const box = document.createElement("div");
          box.style.flex = "0 0 auto";
          box.style.borderRadius = "14px";
          box.style.border = "1px solid rgba(255,255,255,0.10)";
          box.style.background = "rgba(255,255,255,0.05)";
          box.style.padding = "10px 12px";
          box.style.minWidth = "74px";
          box.style.display = "flex";
          box.style.flexDirection = "column";
          box.style.alignItems = "center";
          box.style.justifyContent = "center";
          box.style.gap = "6px";
          box.style.transition = "opacity .2s ease";

          const t = document.createElement("span");
          t.className = "num-font";
          t.style.fontSize = "12px";
          t.style.opacity = "0.75";
          t.textContent = toTimeStr(x.start);

          const l = document.createElement("span");
          l.style.fontWeight = "1000";
          l.style.fontSize = "16px";
          l.style.lineHeight = "1";
          l.textContent = safeText(x.label || "—");

          box.appendChild(t);
          box.appendChild(l);
          dom.miniSchedule.appendChild(box);
          miniItems.push({ start: x.start, end: x.end, label: x.label, el: box });
        });
      }
    }

    miniItems.forEach((it) => {
      if (!it.el) return;
      it.el.style.opacity = isNowBetween(it.start, it.end, baseMs) ? "1" : "0.65";
    });
  }

  // ===== Announcements =====
  let annTimer = null;
  let annPtr = 0;
  let annList = [];
  const ANN_INT = 6500;

  function annSignature(arr) {
    const a = Array.isArray(arr) ? arr : [];
    return JSON.stringify(
      a.map((x) => {
        x = x || {};
        const title = safeText(x.title || x.heading || "");
        const body = safeText(x.body || x.details || x.text || x.message || "");
        const id = safeText(x.id || x.pk || "");
        return [id, title, body];
      })
    );
  }

  function showAnnouncement(i) {
    if (!annList.length) return;
    annPtr = (i + annList.length) % annList.length;
    const a = annList[annPtr] || {};
    renderAlert(safeText(a.title || a.heading || "تنبيه"), safeText(a.body || a.details || a.text || a.message || "—"));
  }

  function renderAnnouncements(arr) {
    const sig = annSignature(arr);
    if (sig && sig === last.annSig) return;
    last.annSig = sig;

    annList = Array.isArray(arr) ? arr.slice() : [];
    if (annTimer) {
      clearInterval(annTimer);
      annTimer = null;
    }

    if (!annList.length) {
      annPtr = 0;
      renderAlert("لا توجد تنبيهات حالياً", "—");
      return;
    }

    annPtr = clamp(annPtr, 0, Math.max(0, annList.length - 1));
    showAnnouncement(annPtr);
    if (annList.length > 1) annTimer = setInterval(() => showAnnouncement(annPtr + 1), ANN_INT);
  }

  // ===== Independent Auto-Scroller (لكل كرت لوحده) =====
  function findViewportForTrack(trackEl) {
    if (!trackEl) return null;
    let vp = trackEl.parentElement;
    while (vp && !(vp.classList && (vp.classList.contains("standby-viewport") || vp.classList.contains("list-viewport")))) {
      vp = vp.parentElement;
    }
    return vp || trackEl.parentElement || null;
  }

  function createScroller(trackEl, getSpeed) {
    const st = {
      raf: null,
      y: 0,
      lastTs: 0,
      contentH: 0,
      viewH: 0,
      hasClone: false,
      lastSig: "",
      running: false,
    };

    function stop() {
      if (st.raf) cancelAnimationFrame(st.raf);
      st.raf = null;
      st.running = false;
      st.lastTs = 0;
    }

    function ensureSingleContentNode() {
      // track children: [content, clone?]
      while (trackEl.children.length > 2) trackEl.removeChild(trackEl.lastElementChild);
      if (trackEl.children.length === 2 && !st.hasClone) {
        // لو صار لسبب ما
        trackEl.removeChild(trackEl.lastElementChild);
      }
    }

    function removeClone() {
      if (trackEl.children.length > 1) {
        trackEl.removeChild(trackEl.lastElementChild);
      }
      st.hasClone = false;
    }

    function needScroll() {
      // الشرط المتفق عليه: التمرير فقط إذا امتلأ الكرت (المحتوى أطول من مساحة العرض)
      return st.contentH > st.viewH + 4;
    }

    function recalc() {
      const vp = findViewportForTrack(trackEl);
      const content = trackEl.firstElementChild;
      if (!vp || !content) return;

      st.viewH = vp.offsetHeight || 0;
      st.contentH = content.offsetHeight || 0;

      if (!needScroll()) {
        stop();
        removeClone();
        st.y = 0;
        trackEl.style.transform = "translateY(0)";
        return;
      }

      // احتاج scroll: تأكد وجود clone
      if (!st.hasClone) {
        const clone = content.cloneNode(true);
        clone.setAttribute("aria-hidden", "true");
        trackEl.appendChild(clone);
        st.hasClone = true;
      }

      // اضبط y داخل مدى المحتوى
      if (st.contentH > 0) st.y = st.y % st.contentH;

      if (!st.running) start();
    }

    function loop(ts) {
      if (document.hidden) {
        st.raf = requestAnimationFrame(loop);
        return;
      }

      if (!st.lastTs) st.lastTs = ts;
      const dt = Math.min(40, ts - st.lastTs); // ms
      st.lastTs = ts;

      // speed عندك قيمة 0.15..4 (كانت px/frame تقريبًا) نخليها px/sec = v*60
      const v = Number(getSpeed()) || 0.5;
      const pxPerSec = clamp(v, 0.15, 4) * 60;
      const step = (pxPerSec * dt) / 1000;

      st.y += step;
      if (st.contentH > 0 && st.y >= st.contentH) st.y = st.y % st.contentH;

      trackEl.style.transform = "translateY(-" + st.y.toFixed(2) + "px)";
      st.raf = requestAnimationFrame(loop);
    }

    function start() {
      if (st.running) return;
      st.running = true;
      st.lastTs = 0;
      if (st.raf) cancelAnimationFrame(st.raf);
      st.raf = requestAnimationFrame(loop);
    }

    function render(signature, contentBuilderFn) {
      // لو ما تغيّر المحتوى: فقط حدّث القياسات والسرعة (بدون تصفير y)
      if (signature && signature === st.lastSig) {
        recalc();
        return;
      }

      st.lastSig = signature || "";

      // تغيير محتوى: ابقِ y كما هو (لن نعيده للصفر)، فقط نعيد بناء القائمة
      stop();
      st.hasClone = false;
      trackEl.style.transform = "translateY(-" + st.y.toFixed(2) + "px)";

      // rebuild
      while (trackEl.firstChild) trackEl.removeChild(trackEl.firstChild);
      const content = contentBuilderFn();
      trackEl.appendChild(content);

      // بعد البناء احسب وقرر هل نمرر أم لا
      requestAnimationFrame(() => {
        ensureSingleContentNode();
        recalc();
      });
    }

    return {
      render,
      recalc,
      stop,
      getState: () => ({ y: st.y, running: st.running, contentH: st.contentH, viewH: st.viewH }),
    };
  }

  // ===== Slot builder =====
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

  function listSignature(items, kind) {
    const arr = Array.isArray(items) ? items : [];
    return JSON.stringify(
      arr.map((x) => {
        x = x || {};
        const cls = safeText(x.class_name || x["class"] || x.classroom || "");
        const subj = safeText(x.subject_name || x.subject || x.label || "");
        const teacher = safeText(x.teacher_name || x.teacher || x.teacher_full_name || "");
        const pidx = getPeriodIndex(x) || "";
        const extra = kind === "standby" ? safeText(x.reason || x.note || "") : "";
        return [cls, subj, teacher, pidx, extra];
      })
    );
  }

  // ===== Scrollers instances =====
  let periodsScroller = null;
  let standbyScroller = null;

  // caches
  let periodItemsCache = [];
  let standbyItemsCache = [];
  let lastPayloadForFiltering = null;

  function filterByCurrentPeriodIndex(items, currentIdx) {
    if (!currentIdx) return items;
    return items.filter((x) => {
      const idx = getPeriodIndex(x);
      if (!idx) return true; // لو ما فيه رقم نخليه
      return idx >= currentIdx;
    });
  }

  function renderPeriodClasses(items) {
    const raw = Array.isArray(items) ? items.slice() : [];
    const currentIdx = getCurrentPeriodIdxFromPayload(lastPayloadForFiltering);
    const arr = filterByCurrentPeriodIndex(raw, currentIdx);

    periodItemsCache = arr.slice();
    if (dom.pcCount) setTextIfChanged(dom.pcCount, String(arr.length));

    if (!dom.periodClassesTrack || !periodsScroller) return;

    const sig = listSignature(arr, "periods");
    periodsScroller.render(sig, () => {
      if (!arr.length) {
        const msg = document.createElement("div");
        msg.style.textAlign = "center";
        msg.style.opacity = "0.75";
        msg.style.padding = "30px 12px";
        msg.textContent = "لا توجد حصص جارية";
        return msg;
      }

      const list = document.createElement("div");
      list.style.display = "flex";
      list.style.flexDirection = "column";
      list.style.gap = "10px";
      list.style.paddingBottom = "10px";

      arr.forEach((x) => {
        x = x || {};
        list.appendChild(
          buildSlotItem({
            clsName: x.class_name || x["class"] || x.classroom || "—",
            subj: x.subject_name || x.subject || x.label || "—",
            teacher: x.teacher_name || x.teacher || "",
            badgeText: formatPeriodTitle(x),
            badgeKind: "ok",
          })
        );
      });

      return list;
    });
  }

  function renderStandby(items) {
    const raw = Array.isArray(items) ? items.slice() : [];
    const currentIdx = getCurrentPeriodIdxFromPayload(lastPayloadForFiltering);

    // المطلوب: اخفاء أي حصة قبل الحصة الحالية (في الانتظار)
    const arr = filterByCurrentPeriodIndex(raw, currentIdx);

    standbyItemsCache = arr.slice();
    if (dom.sbCount) setTextIfChanged(dom.sbCount, String(arr.length));

    if (!dom.standbyTrack || !standbyScroller) return;

    const sig = listSignature(arr, "standby");
    standbyScroller.render(sig, () => {
      if (!arr.length) {
        const msg = document.createElement("div");
        msg.style.textAlign = "center";
        msg.style.opacity = "0.75";
        msg.style.padding = "30px 12px";
        msg.textContent = "لا توجد حصص انتظار";
        return msg;
      }

      const list = document.createElement("div");
      list.style.display = "flex";
      list.style.flexDirection = "column";
      list.style.gap = "10px";
      list.style.paddingBottom = "10px";

      arr.forEach((x) => {
        x = x || {};
        list.appendChild(
          buildSlotItem({
            clsName: x.class_name || x["class"] || x.classroom || "—",
            subj: x.subject_name || x.subject || x.label || "—",
            teacher: x.teacher_name || x.teacher || x.teacher_full_name || "—",
            badgeText: formatPeriodTitle(x),
            badgeKind: "warn",
          })
        );
      });

      return list;
    });
  }

  // ===== Excellence =====
  let exTimer = null;
  let exPtr = 0;
  let exList = [];
  const EX_INT = 7000;

  function exSignature(arr) {
    const a = Array.isArray(arr) ? arr : [];
    return JSON.stringify(
      a.map((e) => {
        e = e || {};
        const student = e.student || {};
        const teacher = e.teacher || {};
        const name = safeText(
          e.name ||
            e.student_name ||
            e.teacher_name ||
            student.name ||
            teacher.name ||
            e.full_name ||
            e.display_name ||
            ""
        );
        const reason = safeText(e.reason || e.note || e.message || e.title || "");
        const img = safeText(
          e.image_src ||
            e.photo_url ||
            e.image_url ||
            e.photo ||
            e.image ||
            e.avatar ||
            student.photo_url ||
            student.image_url ||
            student.photo ||
            student.image ||
            teacher.photo_url ||
            teacher.image_url ||
            teacher.photo ||
            teacher.image ||
            ""
        );
        return [name, reason, img];
      })
    );
  }

  function showExcellence(i) {
    if (!exList.length || !dom.exSlot) return;

    exPtr = (i + exList.length) % exList.length;
    if (dom.exIndex) setTextIfChanged(dom.exIndex, String(exPtr + 1));

    const e = exList[exPtr] || {};
    const student = e.student || {};
    const teacher = e.teacher || {};

    const name =
      e.name ||
      e.student_name ||
      e.teacher_name ||
      student.name ||
      teacher.name ||
      e.full_name ||
      e.display_name ||
      "—";

    let reason = safeText(e.reason || e.note || e.message || e.title || "");
    if (reason.length > 180) reason = reason.slice(0, 177) + "…";

    const rawSrc =
      e.image_src ||
      e.photo_url ||
      e.image_url ||
      e.photo ||
      e.image ||
      e.avatar ||
      student.photo_url ||
      student.image_url ||
      student.photo ||
      student.image ||
      teacher.photo_url ||
      teacher.image_url ||
      teacher.photo ||
      teacher.image;

    const src = resolveImageURL(rawSrc);

    dom.exSlot.style.opacity = "0";
    setTimeout(() => {
      clearNode(dom.exSlot);

      const wrap = document.createElement("div");
      wrap.className = "honor-wrap";

      const img = document.createElement("img");
      img.alt = name;
      img.src =
        src ||
        "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Crect width='100%25' height='100%25' fill='%23222'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' fill='%23fff' font-size='28'%3E%F0%9F%8F%86%3C/text%3E%3C/svg%3E";

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

  function renderExcellence(items) {
    const sig = exSignature(items);
    if (sig && sig === last.exSig) return;
    last.exSig = sig;

    const nextList = Array.isArray(items) ? items.slice() : [];
    exList = nextList.filter(
      (x) =>
        x &&
        (x.name ||
          x.student_name ||
          x.teacher_name ||
          x.full_name ||
          x.display_name ||
          (x.student && x.student.name) ||
          (x.teacher && x.teacher.name))
    );

    if (dom.exTotal) setTextIfChanged(dom.exTotal, String(exList.length || 0));

    if (exTimer) {
      clearInterval(exTimer);
      exTimer = null;
    }
    if (!dom.exSlot) return;

    if (!exList.length) {
      if (dom.exIndex) setTextIfChanged(dom.exIndex, "0");
      dom.exSlot.innerHTML = "";
      const msg = document.createElement("div");
      msg.style.textAlign = "center";
      msg.style.opacity = "0.85";
      msg.textContent = "لا يوجد متميزون حالياً";
      dom.exSlot.appendChild(msg);
      return;
    }

    exPtr = clamp(exPtr, 0, Math.max(0, exList.length - 1));
    showExcellence(exPtr);
    if (exList.length > 1) exTimer = setInterval(() => showExcellence(exPtr + 1), EX_INT);
  }

  // ===== Main state render =====
  function renderState(payload) {
    if (!payload) return;

    lastPayloadForFiltering = payload;

    if (payload.now) {
      const serverMs = new Date(payload.now).getTime();
      if (!isNaN(serverMs)) serverOffsetMs = serverMs - Date.now();
    }

    const baseMs = nowMs();
    hydrateBrand(payload);

    const settings = payload.settings || {};

    if (typeof settings.refresh_interval_sec === "number" && settings.refresh_interval_sec > 0) {
      const nInt = clamp(settings.refresh_interval_sec, 5, 120);
      if (Math.abs(nInt - cfg.REFRESH_EVERY) > 0.001) cfg.REFRESH_EVERY = nInt;
    }

    // السرعات تتحدث فورًا (والسكروول يقرأها لحظيًا)
    if (typeof settings.standby_scroll_speed === "number" && settings.standby_scroll_speed > 0) {
      cfg.STANDBY_SPEED = normSpeed(settings.standby_scroll_speed, cfg.STANDBY_SPEED);
    }
    if (typeof settings.periods_scroll_speed === "number" && settings.periods_scroll_speed > 0) {
      cfg.PERIODS_SPEED = normSpeed(settings.periods_scroll_speed, cfg.PERIODS_SPEED);
    }

    // أعِد حساب قرار التمرير فورًا عند تغيير القياس/السرعة بدون إعادة بناء
    if (periodsScroller) periodsScroller.recalc();
    if (standbyScroller) standbyScroller.recalc();

    tickClock(payload.date_info || null);

    const s = payload.state || {};
    const stType = safeText(s.type || "");
    const current = payload.current_period || null;
    const nextP = payload.next_period || null;

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

    let title = safeText(s.label || "لوحة العرض المدرسية");
    let range = (s.from || s.to) ? (toTimeStr(s.from) + " → " + toTimeStr(s.to)) : "--:-- → --:--";
    let badge = "حالة اليوم";

    if (stType === "period") {
      badge = "درس";
      title = formatPeriodTitle(current);
    } else if (stType === "break") {
      badge = "استراحة";
      title = safeText(s.label || "استراحة");
    } else if (stType === "off") {
      badge = "عطلة";
      title = safeText(s.label || "يوم إجازة");
      range = "--:--";
    }

    const stateSig =
      stType +
      "||" +
      title +
      "||" +
      range +
      "||" +
      safeText(s.from) +
      "||" +
      safeText(s.to) +
      "||" +
      safeText(s.remaining_seconds);

    if (stateSig !== last.stateSig) {
      last.stateSig = stateSig;
      setTextIfChanged(dom.heroTitle, title);
      setTextIfChanged(dom.heroRange, range);
      setTextIfChanged(dom.badgeKind, badge);
    }

    if (dom.nextLabel) {
      const nextSig =
        nextP && (nextP.from || nextP.to || nextP.label || nextP.index || nextP.period_index)
          ? safeText(nextP.from) +
            "||" +
            safeText(nextP.to) +
            "||" +
            safeText(nextP.label) +
            "||" +
            safeText(getPeriodIndex(nextP) || "")
          : "none";

      if (nextSig !== last.nextSig) {
        last.nextSig = nextSig;
        if (nextSig === "none") {
          setTextIfChanged(dom.nextLabel, "—");
        } else {
          const nextTitle = formatPeriodTitle(nextP);
          const from = toTimeStr(nextP.from);
          setTextIfChanged(dom.nextLabel, from !== "--:--" ? nextTitle + " (" + from + ")" : nextTitle);
        }
      }
    }

    renderCurrentChips(stType, s, current);
    renderMiniSchedule(payload, baseMs);
  }

  // ===== Ticker 1s =====
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
          setTextIfChanged(dom.countdown, fmt2(mm) + ":" + fmt2(ss));
        } else {
          setTextIfChanged(dom.countdown, "--:--");
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

  // ===== Fetch with timeout + ETag/304 =====
  let inflight = null;
  let ctrl = null;
  const etagKey = "display_etag_" + (location.pathname || "/");

  function withTimeout(promise, ms, onTimeout) {
    let t = null;
    const timeout = new Promise((_, rej) => {
      t = setTimeout(() => {
        try {
          if (onTimeout) onTimeout();
        } catch (e) {}
        rej(new Error("timeout"));
      }, ms);
    });
    return Promise.race([promise, timeout]).finally(() => {
      if (t) clearTimeout(t);
    });
  }

  async function safeFetchSnapshot() {
    if (inflight) return inflight;

    const token = getToken();
    const baseUrl = resolveSnapshotUrl();

    const u = new URL(baseUrl, window.location.origin);
    u.searchParams.set("_t", String(Date.now())); // bust cache لو ما فيه ETag

    if (ctrl) {
      try {
        ctrl.abort();
      } catch (e) {}
    }
    ctrl = window.AbortController ? new AbortController() : null;

    const headers = { Accept: "application/json", "X-Display-Token": token || "" };

    try {
      const prev = localStorage.getItem(etagKey) || "";
      if (prev) headers["If-None-Match"] = prev;
    } catch (e) {}

    const fetchPromise = fetch(u.toString(), {
      method: "GET",
      headers,
      cache: "no-store",
      signal: ctrl ? ctrl.signal : undefined,
    }).then(async (r) => {
      if (r.status === 304) return { _notModified: true };
      if (!r.ok) throw new Error("HTTP " + r.status);

      const et = r.headers && r.headers.get ? (r.headers.get("ETag") || "") : "";
      if (et) {
        try {
          localStorage.setItem(etagKey, et);
        } catch (e) {}
      }

      return r.json();
    });

    inflight = withTimeout(fetchPromise, 9000, () => {
      if (ctrl) {
        try {
          ctrl.abort();
        } catch (e) {}
      }
    })
      .catch((e) => {
        renderAlert("تعذر جلب البيانات", "تأكد من token ومن مسار snapshot.");
        ensureDebugOverlay();
        if (isDebug()) setDebugText("fetch error: " + (e && e.message ? e.message : String(e)));
        return null;
      })
      .finally(() => {
        inflight = null;
      });

    return await inflight;
  }

  // ===== Refresh loop =====
  let pollTimer = null;
  let failStreak = 0;

  function scheduleNext(sec) {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(refreshLoop, Math.max(0.2, sec) * 1000);
  }

  async function refreshLoop() {
    if (document.hidden) {
      scheduleNext(cfg.REFRESH_EVERY);
      return;
    }

    const snap = await safeFetchSnapshot();
    if (!snap) {
      failStreak += 1;
      const backoff = Math.min(60, cfg.REFRESH_EVERY + failStreak * 5);
      scheduleNext(backoff);
      return;
    }

    if (snap && snap._notModified) {
      failStreak = 0;
      scheduleNext(cfg.REFRESH_EVERY);
      if (isDebug()) {
        ensureDebugOverlay();
        setDebugText("304 not-modified | " + new Date().toLocaleTimeString());
      }
      return;
    }

    try {
      failStreak = 0;

      renderState(snap);
      renderAnnouncements(snap.announcements || []);
      renderExcellence(snap.excellence || []);

      // القوائم: مستقلة + لا تعيد التمرير إذا نفس البيانات
      renderStandby(snap.standby || []);
      renderPeriodClasses(snap.period_classes || []);

      ensureDebugOverlay();
      if (isDebug()) {
        const pS = periodsScroller ? periodsScroller.getState() : {};
        const sS = standbyScroller ? standbyScroller.getState() : {};
        setDebugText(
          "ok " +
            new Date().toLocaleTimeString() +
            " | sb=" +
            (Array.isArray(snap.standby) ? snap.standby.length : 0) +
            " pc=" +
            (Array.isArray(snap.period_classes) ? snap.period_classes.length : 0) +
            " | spd(sb)=" +
            cfg.STANDBY_SPEED +
            " spd(pc)=" +
            cfg.PERIODS_SPEED +
            " | run(sb)=" +
            (sS.running ? 1 : 0) +
            " run(pc)=" +
            (pS.running ? 1 : 0)
        );
      }
    } catch (e) {
      renderAlert("حدث خطأ أثناء العرض", "افتح ?debug=1 لمزيد من التفاصيل.");
      ensureDebugOverlay();
      if (isDebug()) setDebugText("render error: " + (e && e.message ? e.message : String(e)));
    }

    scheduleNext(cfg.REFRESH_EVERY);
  }

  // ===== Fullscreen compat =====
  function requestFullscreenCompat(el) {
    if (!el) return Promise.reject();
    const fn = el.requestFullscreen || el.webkitRequestFullscreen || el.mozRequestFullScreen || el.msRequestFullscreen;
    if (!fn) return Promise.reject();
    try {
      const res = fn.call(el);
      return res && typeof res.then === "function" ? res : Promise.resolve();
    } catch (e) {
      return Promise.reject(e);
    }
  }

  function exitFullscreenCompat() {
    const d = document;
    const fn = d.exitFullscreen || d.webkitExitFullscreen || d.mozCancelFullScreen || d.msExitFullscreen;
    if (!fn) return Promise.reject();
    try {
      const res = fn.call(d);
      return res && typeof res.then === "function" ? res : Promise.resolve();
    } catch (e) {
      return Promise.reject(e);
    }
  }

  function isFullscreen() {
    const d = document;
    return !!(d.fullscreenElement || d.webkitFullscreenElement || d.mozFullScreenElement || d.msFullscreenElement);
  }

  function bindFullscreen() {
    if (!dom.fsBtn) return;
    dom.fsBtn.addEventListener(
      "click",
      () => {
        if (!isFullscreen()) requestFullscreenCompat(document.documentElement).catch(() => {});
        else exitFullscreenCompat().catch(() => {});
      },
      { passive: true }
    );
  }

  // ===== Resize: فقط إعادة القياس (بدون مسح التوقيعات) =====
  let resizeT = null;
  window.addEventListener(
    "resize",
    () => {
      if (resizeT) clearTimeout(resizeT);
      resizeT = setTimeout(() => {
        setVhVar();
        if (periodsScroller) periodsScroller.recalc();
        if (standbyScroller) standbyScroller.recalc();
      }, 160);
    },
    { passive: true }
  );

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      // عند الرجوع: أعِد القياس ثم اسحب تحديث سريع
      if (periodsScroller) periodsScroller.recalc();
      if (standbyScroller) standbyScroller.recalc();
      scheduleNext(0.25);
    }
  });

  // ===== Global errors =====
  window.addEventListener("error", (ev) => {
    ensureDebugOverlay();
    if (isDebug()) setDebugText("window error: " + safeText(ev && ev.message));
  });
  window.addEventListener("unhandledrejection", (ev) => {
    ensureDebugOverlay();
    if (isDebug())
      setDebugText(
        "promise rej: " + safeText(ev && ev.reason && ev.reason.message ? ev.reason.message : ev.reason)
      );
  });

  // ===== Boot =====
  document.addEventListener("DOMContentLoaded", () => {
    bindDom();
    setVhVar();

    const body = document.body || document.documentElement;

    cfg.REFRESH_EVERY = clamp(parseFloat(body.dataset.refresh || "10") || 10, 5, 120);
    cfg.STANDBY_SPEED = normSpeed(body.dataset.standby || "0.8", 0.8);
    cfg.PERIODS_SPEED = normSpeed(body.dataset.periodsSpeed || "0.5", 0.5);

    cfg.MEDIA_PREFIX = (body.dataset.mediaPrefix || "/media/").toString().trim();
    cfg.SNAPSHOT_URL = (body.dataset.snapshotUrl || "").toString().trim();
    cfg.SERVER_TOKEN = (body.dataset.apiToken || body.dataset.token || "").toString().trim();

    try {
      const initTheme = (body.dataset.theme || "").trim();
      if (initTheme) applyTheme(initTheme);
    } catch (e) {}

    ensureDebugOverlay();
    tickClock();
    startTicker();
    bindFullscreen();

    // init scrollers (مستقلين)
    periodsScroller = dom.periodClassesTrack
      ? createScroller(dom.periodClassesTrack, () => cfg.PERIODS_SPEED)
      : null;

    standbyScroller = dom.standbyTrack
      ? createScroller(dom.standbyTrack, () => cfg.STANDBY_SPEED)
      : null;

    renderAlert("جاري التحميل…", "يتم الآن جلب البيانات من الخادم.");
    scheduleNext(0.2);
  });
})();
