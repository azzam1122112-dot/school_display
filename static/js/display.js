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
    // Use a dedicated hide utility to avoid CSS-lint conflicts with Tailwind display classes (e.g., flex).
    // Keep backward compatibility by toggling both.
    if (hidden) {
      el.classList.add("u-hidden");
      el.classList.add("hidden");
    } else {
      el.classList.remove("u-hidden");
      el.classList.remove("hidden");
    }
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

  function isLiteMode() {
    try {
      const qs = new URLSearchParams(window.location.search);
      const v = (qs.get("lite") || qs.get("liteMode") || "").trim().toLowerCase();
      if (v === "1" || v === "true" || v === "yes") return true;
      if (v === "0" || v === "false" || v === "no") return false;
    } catch (e) {}

    try {
      const ua = String(navigator.userAgent || "").toLowerCase();
      if (
        ua.includes("smarttv") ||
        ua.includes("hbbtv") ||
        ua.includes("tizen") ||
        ua.includes("web0s") ||
        ua.includes("netcast")
      ) {
        return true;
      }
    } catch (e) {}

    // Conservative heuristics for older/low-end devices
    try {
      const hc = Number(navigator.hardwareConcurrency || 0);
      if (hc && hc <= 2) return true;
    } catch (e) {}

    try {
      const mem = Number(navigator.deviceMemory || 0);
      if (mem && mem <= 2) return true;
    } catch (e) {}

    return false;
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

    dom.alertContainer = $("alertContainer");
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

    dom.exCard = $("exCard");
    dom.dutyCard = $("dutyCard");
    dom.dutySlot = $("dutySlot");
    dom.dutyTrack = $("dutyTrack");
    dom.dutyTotal = $("dutyTotal");

    dom.pcCount = $("pcCount");
    dom.periodClassesTrack = $("periodClassesTrack");

    dom.sbCount = $("sbCount");
    dom.standbyTrack = $("standbyTrack");

    dom.fsBtn = $("fsBtn");

    // Blocking overlay
    dom.blocker = $("blocker");
    dom.blockerTitle = $("blockerTitle");
    dom.blockerDetails = $("blockerDetails");
    dom.blockerLink = $("blockerLink");

    // Robust logo fallback (in case a provided logo URL 404s)
    if (dom.schoolLogo && !dom.schoolLogo.dataset._fallbackBound) {
      dom.schoolLogo.dataset._fallbackBound = "1";
      dom.schoolLogo.addEventListener(
        "error",
        () => {
          const fallback =
            safeText(dom.schoolLogo.getAttribute("data-fallback-src")) ||
            safeText(dom.schoolLogo.getAttribute("data-fallback")) ||
            "";
          if (!fallback) return;
          // avoid infinite loop if fallback also fails
          if (dom.schoolLogo.src && dom.schoolLogo.src.indexOf(fallback) >= 0) return;
          dom.schoolLogo.src = fallback;
        },
        { passive: true }
      );
    }
  }

  // ===== Blocking overlay helpers =====
  let isBlocked = false;
  function showBlocker(title, details) {
    isBlocked = true;
    if (dom.blockerTitle) dom.blockerTitle.textContent = safeText(title);
    if (dom.blockerDetails) dom.blockerDetails.textContent = safeText(details);
    if (dom.blockerLink) {
      try {
        const p = safeText(window.location && window.location.pathname ? window.location.pathname : "");
        const q = safeText(window.location && window.location.search ? window.location.search : "");
        const shown = (p + q).trim() || "—";
        dom.blockerLink.textContent = shown;
      } catch (e) {
        dom.blockerLink.textContent = "—";
      }
    }
    toggleHidden(dom.blocker, false);
  }
  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    if (ctrl) {
      try {
        ctrl.abort();
      } catch (e) {}
    }
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
    SCHOOL_TYPE: "",
  };

  function teacherLabelText() {
    const t = (cfg.SCHOOL_TYPE || "").toString().trim().toLowerCase();
    if (t === "boys") return "المعلم";
    if (t === "girls") return "المعلمة";
    return "المعلم/ـة";
  }

  // ===== Runtime (فلترة الانتظار/نهاية الدوام) =====
  const rt = {
    activePeriodIndex: null, // رقم الحصة الحالية/التالية
    activeFromHM: null, // وقت بداية النشاط الحالي/التالي
    dayOver: false, // انتهاء الدوام
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
      periodObj.current_period_index ??
      periodObj.current_idx ??
      periodObj.idx ??
      periodObj.period ??
      periodObj.period_no ??
      periodObj.current_period_no ??
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
    const n2 =
      getPeriodIndex(st) ||
      (st && typeof st.current_period_index !== "undefined" ? parseInt(st.current_period_index, 10) : NaN) ||
      (st && typeof st.period_index !== "undefined" ? parseInt(st.period_index, 10) : NaN);

    return isNaN(n2) ? null : n2;
  }

  // ===== Day over + standby filter =====
  function computeDayOver(payload, baseMs) {
    const s = (payload && payload.state) || {};
    const stType = safeText(s.type || "");

    if (stType === "off") return true;

    if (Array.isArray(payload && payload.day_path) && payload.day_path.length) {
      const anyNotEnded = payload.day_path.some((x) => x && !isEnded(x.to, baseMs));
      if (!anyNotEnded) return true;
    }

    if (!payload.next_period && s.to && isEnded(s.to, baseMs)) return true;

    return false;
  }

  function shouldKeepStandbyItem(x, baseMs) {
    if (!x) return false;

    // 1) فلترة بالأرقام (الأفضل)
    const idx = getPeriodIndex(x);
    if (rt.activePeriodIndex && idx) return idx >= rt.activePeriodIndex;

    // 2) fallback بالوقت إذا ما فيه رقم
    const from = x.from || x.start || x.starts_at;
    if (rt.activeFromHM && from) {
      const a = hmToMs(rt.activeFromHM, baseMs);
      const b = hmToMs(from, baseMs);
      if (a && b) return b >= a;
    }

    // إذا ما نقدر نحدد… نخليه
    return true;
  }

  // ===== Render: Alert =====
  function renderAlert(title, details) {
    toggleHidden(dom.alertContainer, false);
    setTextIfChanged(dom.alertTitle, title || "تنبيه");
    setTextIfChanged(dom.alertDetails, details || "—");
  }

  // ===== Render: Brand/Theme =====
  function applyTheme(name) {
    let n = (name || "").toString().trim().toLowerCase();
    if (!n) n = "indigo";
    document.body.setAttribute("data-theme", n);
  }

  // ===== Custom colors (optional) =====
  function hexToRgb(hex) {
    const s = (hex || "").toString().trim();
    const m = s.match(/^#([0-9a-fA-F]{6})$/);
    if (!m) return null;
    const v = m[1];
    return {
      r: parseInt(v.slice(0, 2), 16),
      g: parseInt(v.slice(2, 4), 16),
      b: parseInt(v.slice(4, 6), 16),
    };
  }

  function clamp01(x) {
    const n = Number(x);
    if (!isFinite(n)) return 0;
    return Math.max(0, Math.min(1, n));
  }

  function mixRgb(a, b, t) {
    const k = clamp01(t);
    return {
      r: Math.round(a.r + (b.r - a.r) * k),
      g: Math.round(a.g + (b.g - a.g) * k),
      b: Math.round(a.b + (b.b - a.b) * k),
    };
  }

  function rgbToHex(rgb) {
    const to2 = (n) => {
      const x = Math.max(0, Math.min(255, Number(n) || 0));
      return x.toString(16).padStart(2, "0").toUpperCase();
    };
    return "#" + to2(rgb.r) + to2(rgb.g) + to2(rgb.b);
  }

  function rgba(rgb, a) {
    return "rgba(" + [rgb.r, rgb.g, rgb.b, clamp01(a)].join(",") + ")";
  }

  function applyAccentColor(hex) {
    const rgb = hexToRgb(hex);
    if (!rgb) {
      // رجوع للألوان الافتراضية من app.css
      root.style.removeProperty("--accent-main");
      root.style.removeProperty("--accent-sub");
      root.style.removeProperty("--mesh1");
      root.style.removeProperty("--mesh2");
      return;
    }

    const sub = rgbToHex(mixRgb(rgb, { r: 255, g: 255, b: 255 }, 0.30));
    root.style.setProperty("--accent-main", rgbToHex(rgb));
    root.style.setProperty("--accent-sub", sub);
    // Mesh: لمسة خفيفة من نفس اللون
    root.style.setProperty("--mesh1", rgba(rgb, 0.18));
    root.style.setProperty("--mesh2", rgba(rgb, 0.12));
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
    const schoolType = safeText(settings.school_type || "");
    const accent = safeText(settings.display_accent_color || "");

    const previewLock = (document.body && document.body.dataset && document.body.dataset.previewLock === '1');

    const sig = name + "||" + logo + "||" + theme + "||" + schoolType + "||" + accent;
    if (sig === last.brandSig) return;
    last.brandSig = sig;

    if (!previewLock) {
      if (theme) applyTheme(theme);
      applyAccentColor(accent);
    }

    if (name) {
      document.title = name + " — لوحة العرض الذكية";
      setTextIfChanged(dom.schoolName, name);
    }

    if (dom.schoolLogo) {
      const fallback =
        safeText(dom.schoolLogo.getAttribute("data-fallback-src")) ||
        safeText(dom.schoolLogo.getAttribute("data-fallback")) ||
        "";

      const nextSrc = logo || fallback || dom.schoolLogo.src;
      if (nextSrc && dom.schoolLogo.src !== nextSrc) dom.schoolLogo.src = nextSrc;
      toggleHidden(dom.schoolLogo, false);
      if (dom.schoolLogoFallback) toggleHidden(dom.schoolLogoFallback, true);
    }

    if (schoolType) cfg.SCHOOL_TYPE = schoolType;
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
  let lastStateCoreSig = "";

  let lastZeroHandledCoreSig = "";

  let lastCountdownZeroAt = 0;
  function onCountdownZero() {
    if (isBlocked) return;
    const now = Date.now();
    if (now - lastCountdownZeroAt < 2000) return;
    lastCountdownZeroAt = now;

    // Optional (heavier) behavior: full page reload if explicitly requested.
    // Example: /display/<token>/?reload_on_zero=1
    try {
      const qs = new URLSearchParams(window.location.search);
      if ((qs.get("reload_on_zero") || "").trim() === "1") {
        try {
          const k = "display_reload_on_zero_ts";
          const prev = Number(sessionStorage.getItem(k) || 0);
          if (prev && now - prev < 3000) return;
          sessionStorage.setItem(k, String(now));
        } catch (e) {}
        try {
          window.location.reload();
        } catch (e) {}
        return;
      }
    } catch (e) {}

    // Default: force-refresh data ASAP (bypasses ETag + server-side snapshot cache).
    try {
      forceRefreshNow("countdown_zero");
    } catch (e) {
      try {
        scheduleNext(0.2);
      } catch (e2) {}
    }
  }

  let forceRefreshInProgress = false;
  let reloadFallbackTs = 0;
  async function forceRefreshNow(reason) {
    if (isBlocked) return;
    if (forceRefreshInProgress) return;
    forceRefreshInProgress = true;

    try {
      // Force a fresh snapshot build on the server to avoid waiting for the server cache TTL.
      const snap = await safeFetchSnapshot({
        force: true,
        bypassEtag: true,
        bypassServerCache: true,
        reason: reason || "manual",
      });

      if (!snap || (snap && snap._notModified)) {
        return;
      }

      try {
        // Same render path as refreshLoop
        failStreak = 0;
        renderState(snap);
        renderAnnouncements(snap.announcements || []);
        renderFeaturedPanel(snap);
        renderStandby(snap.standby || []);
        renderPeriodClasses(snap.period_classes || []);
      } catch (e) {
        renderAlert("حدث خطأ أثناء العرض", "افتح ?debug=1 لمزيد من التفاصيل.");
        ensureDebugOverlay();
        if (isDebug()) setDebugText("force render error: " + (e && e.message ? e.message : String(e)));
      }

      // If we forced a refresh at countdown==0 but the state still didn't advance,
      // do one bounded retry, then a bounded hard reload as a last resort.
      try {
        const s = (snap && snap.state) || {};
        const stType = safeText(s.type || "");
        const coreSig =
          stType + "||" + safeText(s.label || "") + "||" + safeText(s.from || "") + "||" + safeText(s.to || "");
        const rem = typeof s.remaining_seconds === "number" ? Math.max(0, Math.floor(s.remaining_seconds)) : null;

        if ((stType === "period" || stType === "break" || stType === "before") && rem === 0) {
          // One quick retry (server might still be computing the transition)
          setTimeout(() => {
            try {
              safeFetchSnapshot({ force: true, bypassEtag: true, bypassServerCache: true, reason: "countdown_zero_retry" })
                .then((snap2) => {
                  if (!snap2 || (snap2 && snap2._notModified)) return;
                  try {
                    renderState(snap2);
                    renderAnnouncements(snap2.announcements || []);
                    renderFeaturedPanel(snap2);
                    renderStandby(snap2.standby || []);
                    renderPeriodClasses(snap2.period_classes || []);
                  } catch (e) {}

                  try {
                    const s2 = (snap2 && snap2.state) || {};
                    const st2 = safeText(s2.type || "");
                    const core2 =
                      st2 + "||" + safeText(s2.label || "") + "||" + safeText(s2.from || "") + "||" + safeText(s2.to || "");
                    const rem2 = typeof s2.remaining_seconds === "number" ? Math.max(0, Math.floor(s2.remaining_seconds)) : null;
                    if ((st2 === "period" || st2 === "break" || st2 === "before") && rem2 === 0 && core2 === coreSig) {
                      const now2 = Date.now();
                      // Reduced timeout to 3s to ensure screen updates immediately if stuck at 00:00
                      if (now2 - reloadFallbackTs > 3000) {
                        reloadFallbackTs = now2;
                        try {
                          window.location.reload();
                        } catch (e) {}
                      }
                    }
                  } catch (e) {}
                })
                .catch(() => {});
            } catch (e) {}
          }, 800);
        }
      } catch (e) {}
    } catch (e) {
      // Fallback to normal loop on unexpected errors.
      try {
        scheduleNext(0.2);
      } catch (e2) {}
    } finally {
      forceRefreshInProgress = false;
      try {
        scheduleNext(cfg.REFRESH_EVERY);
      } catch (e) {}
    }
  }

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
    while (
      vp &&
      !(vp.classList && (vp.classList.contains("standby-viewport") || vp.classList.contains("list-viewport")))
    ) {
      vp = vp.parentElement;
    }
    return vp || trackEl.parentElement || null;
  }

  function createScroller(trackEl, getSpeed, opts) {
    const st = {
      raf: null,
      y: 0,
      lastTs: 0,
      contentH: 0,
      viewH: 0,
      cloneCount: 0,
      lastSig: "",
      running: false,
    };

    const maxFps = opts && opts.maxFps ? Number(opts.maxFps) : 0;
    const minFrameMs = maxFps > 0 ? 1000 / Math.max(1, maxFps) : 0;

    function stop() {
      if (st.raf) cancelAnimationFrame(st.raf);
      st.raf = null;
      st.running = false;
      st.lastTs = 0;
    }

    function trimClones(maxClones) {
      const maxChildren = 1 + Math.max(0, maxClones | 0);
      while (trackEl.children.length > maxChildren) trackEl.removeChild(trackEl.lastElementChild);
    }

    function removeClones() {
      while (trackEl.children.length > 1) trackEl.removeChild(trackEl.lastElementChild);
      st.cloneCount = 0;
    }

    function needScroll(forceScroll) {
      // ✅ افتراضيًا: التمرير فقط إذا امتلأ الكرت فعلاً
      if (forceScroll) return st.contentH > 0 && st.viewH > 0;
      return st.contentH > st.viewH + 4;
    }

    function recalc() {
      const vp = findViewportForTrack(trackEl);
      const content = trackEl.firstElementChild;
      if (!vp || !content) return;

      st.viewH = vp.offsetHeight || 0;
      st.contentH = content.offsetHeight || 0;

      const forceScroll =
        !!(content && content.dataset && content.dataset.forceScroll === "1");

      // لو ما عندنا قياسات صحيحة
      if (!st.viewH || !st.contentH) {
        stop();
        removeClones();
        st.y = 0;
        trackEl.style.transform = "translateY(0)";
        return;
      }

      if (!needScroll(forceScroll)) {
        stop();
        removeClones();
        st.y = 0;
        trackEl.style.transform = "translateY(0)";
        return;
      }

      // ✅ نضيف نسخ كافية حتى لا يظهر فراغ أثناء التمرير (خصوصًا عند forceScroll)
      // نحتاج إجمالي ارتفاع >= viewH + contentH لكي يظل هناك محتوى يغطي الشاشة أثناء الحركة
      const needTotal = st.viewH + st.contentH + 8;
      let guard = 0;
      while ((trackEl.offsetHeight || 0) < needTotal && guard < 8) {
        const clone = content.cloneNode(true);
        clone.setAttribute("aria-hidden", "true");
        trackEl.appendChild(clone);
        st.cloneCount += 1;
        guard += 1;
      }
      trimClones(Math.max(1, st.cloneCount));

      if (st.contentH > 0) st.y = st.y % st.contentH;
      if (!st.running) start();
    }

    function loop(ts) {
      if (document.hidden) {
        st.raf = requestAnimationFrame(loop);
        return;
      }

      if (!st.lastTs) st.lastTs = ts;
      let dt = ts - st.lastTs;
      if (minFrameMs > 0 && dt < minFrameMs) {
        st.raf = requestAnimationFrame(loop);
        return;
      }
      dt = Math.min(120, dt);
      st.lastTs = ts;

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
      if (signature && signature === st.lastSig) {
        recalc();
        return;
      }

      st.lastSig = signature || "";

      // لا نصفر y — نحافظ على موضع التمرير قدر الإمكان
      stop();
      st.cloneCount = 0;
      trackEl.style.transform = "translateY(-" + st.y.toFixed(2) + "px)";

      while (trackEl.firstChild) trackEl.removeChild(trackEl.firstChild);
      const content = contentBuilderFn();
      trackEl.appendChild(content);

      requestAnimationFrame(() => {
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
    lbl.textContent = teacherLabelText() + ":";

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
  let dutyScroller = null;

  let lastPayloadForFiltering = null;

  function renderPeriodClasses(items) {
    const raw = Array.isArray(items) ? items.slice() : [];
    const baseMs = nowMs();

    let arr = raw;

    // ✅ بعد نهاية الدوام: فاضي
    if (rt.dayOver) arr = [];

    // ✅ فلترة القديم (لو أرسل السيرفر عناصر أقل من الحصة الحالية)
    if (!rt.dayOver && rt.activePeriodIndex) {
      arr = arr.filter((x) => {
        const idx = getPeriodIndex(x);
        return !idx || idx >= rt.activePeriodIndex;
      });
    }

    if (dom.pcCount) setTextIfChanged(dom.pcCount, String(arr.length));
    if (!dom.periodClassesTrack || !periodsScroller) return;

    const sig = listSignature(arr, "periods");
    periodsScroller.render(sig, () => {
      if (!arr.length) {
        const msg = document.createElement("div");
        msg.style.textAlign = "center";
        msg.style.opacity = "0.75";
        msg.style.padding = "30px 12px";
        msg.textContent = rt.dayOver ? "انتهى الدوام" : "لا توجد حصص جارية";
        return msg;
      }

      const list = document.createElement("div");
      list.style.display = "flex";
      list.style.flexDirection = "column";
      list.style.gap = "10px";
      list.style.paddingBottom = "10px";
      list.dataset.forceScroll = arr.length >= 4 ? "1" : "0";

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
    const baseMs = nowMs();

    let arr = raw;

    // ✅ إذا انتهى الدوام: فاضي
    if (rt.dayOver) arr = [];

    // ✅ اخفاء أي انتظار قبل الحصة الحالية/التالية
    if (!rt.dayOver && (rt.activePeriodIndex || rt.activeFromHM)) {
      arr = arr.filter((x) => shouldKeepStandbyItem(x, baseMs));
    }

    if (dom.sbCount) setTextIfChanged(dom.sbCount, String(arr.length));
    if (!dom.standbyTrack || !standbyScroller) return;

    const sig = listSignature(arr, "standby");
    standbyScroller.render(sig, () => {
      if (!arr.length) {
        const msg = document.createElement("div");
        msg.style.textAlign = "center";
        msg.style.opacity = "0.75";
        msg.style.padding = "30px 12px";
        msg.textContent = rt.dayOver ? "انتهى الدوام" : "لا توجد حصص انتظار";
        return msg;
      }

      const list = document.createElement("div");
      list.style.display = "flex";
      list.style.flexDirection = "column";
      list.style.gap = "10px";
      list.style.paddingBottom = "10px";
      list.dataset.forceScroll = arr.length >= 4 ? "1" : "0";

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

  // ===== Duty / Supervision =====
  function dutySignature(list) {
    const arr = Array.isArray(list) ? list : [];
    return JSON.stringify(
      arr.map((x) => {
        x = x || {};
        return [
          safeText(x.teacher_name || ""),
          safeText(x.duty_type || ""),
          safeText(x.duty_label || ""),
          safeText(x.location || ""),
          safeText(x.priority || ""),
        ];
      })
    );
  }

  function buildDutyRow(it) {
    it = it || {};
    const teacher = safeText(it.teacher_name || "");
    const dutyType = safeText(it.duty_type || "");
    const dutyLabel = safeText(it.duty_label || (dutyType === "supervision" ? "إشراف" : "مناوبة"));
    const location = safeText(it.location || "");

    const row = document.createElement("div");
    row.className = "flex items-center justify-between gap-4 px-4 py-3 rounded-xl bg-white/5 border border-white/10 backdrop-blur-md";

    const left = document.createElement("div");
    left.className = "flex items-center gap-3 min-w-0";

    const avatar = document.createElement("div");
    avatar.className = "w-10 h-10 rounded-xl bg-black/20 border border-white/10 flex items-center justify-center text-slate-200 font-black";
    avatar.textContent = teacher ? teacher.slice(0, 1) : "—";

    const meta = document.createElement("div");
    meta.className = "min-w-0";

    const nm = document.createElement("div");
    nm.className = "text-lg font-extrabold text-white truncate";
    nm.textContent = teacher || "—";

    const sub = document.createElement("div");
    sub.className = "text-sm text-slate-400 truncate";
    sub.textContent = location ? "المكان: " + location : "المكان: —";

    meta.appendChild(nm);
    meta.appendChild(sub);
    left.appendChild(avatar);
    left.appendChild(meta);

    const badge = document.createElement("div");
    const isSup = dutyType === "supervision";
    badge.className =
      "shrink-0 px-3 py-1 rounded-full text-sm font-black border " +
      (isSup
        ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/25"
        : "bg-amber-500/15 text-amber-200 border-amber-500/25");
    badge.textContent = dutyLabel;

    row.appendChild(left);
    row.appendChild(badge);
    return row;
  }

  function renderDuty(items) {
    const raw = items && items.items ? items.items : Array.isArray(items) ? items : [];
    const list = Array.isArray(raw) ? raw : [];

    if (dom.dutyTotal) setTextIfChanged(dom.dutyTotal, String(list.length || 0));
    if (!dom.dutyTrack || !dutyScroller) return;

    const sig = dutySignature(list);
    dutyScroller.render(sig, () => {
      if (!list.length) {
        const msg = document.createElement("div");
        msg.style.textAlign = "center";
        msg.style.opacity = "0.75";
        msg.style.padding = "30px 12px";
        msg.textContent = "لا توجد تكليفات إشراف/مناوبة لليوم";
        return msg;
      }

      const wrap = document.createElement("div");
      wrap.style.display = "flex";
      wrap.style.flexDirection = "column";
      wrap.style.gap = "12px";
      wrap.style.paddingBottom = "12px";
      // نفس سلوك كرت الحصص الجارية
      wrap.dataset.forceScroll = list.length >= 4 ? "1" : "0";

      list.forEach((it) => {
        wrap.appendChild(buildDutyRow(it));
      });

      return wrap;
    });
  }

  // ===== Featured panel toggle =====
  function renderFeaturedPanel(snap) {
    const s = (snap && snap.settings) || {};
    const mode = safeText(s.featured_panel || "excellence");
    const showDuty = mode === "duty";

    toggleHidden(dom.exCard, showDuty);
    toggleHidden(dom.dutyCard, !showDuty);

    if (showDuty) {
      renderDuty(snap.duty || { items: [] });
    } else {
      renderExcellence(snap.excellence || []);
    }
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

    if (settings.school_type) {
      cfg.SCHOOL_TYPE = settings.school_type;
    }

    if (typeof settings.refresh_interval_sec === "number" && settings.refresh_interval_sec > 0) {
      const nInt = clamp(settings.refresh_interval_sec, 5, 120);
      if (Math.abs(nInt - cfg.REFRESH_EVERY) > 0.001) cfg.REFRESH_EVERY = nInt;
    }

    if (typeof settings.standby_scroll_speed === "number" && settings.standby_scroll_speed > 0) {
      cfg.STANDBY_SPEED = normSpeed(settings.standby_scroll_speed, cfg.STANDBY_SPEED);
    }
    if (typeof settings.periods_scroll_speed === "number" && settings.periods_scroll_speed > 0) {
      cfg.PERIODS_SPEED = normSpeed(settings.periods_scroll_speed, cfg.PERIODS_SPEED);
    }

    if (periodsScroller) periodsScroller.recalc();
    if (standbyScroller) standbyScroller.recalc();
    if (dutyScroller) dutyScroller.recalc();

    tickClock(payload.date_info || null);

    const s = payload.state || {};
    const stType = safeText(s.type || "");
    const current = payload.current_period || null;
    const nextP = payload.next_period || null;

    // Snapshot responses are server-cached for a few seconds; keep countdown monotonic for the same state.
    const prevCountdown = hasActiveCountdown && typeof countdownSeconds === "number" ? countdownSeconds : null;
    const prevCoreSig = lastStateCoreSig;
    const nextCoreSig =
      stType + "||" + safeText(s.label || "") + "||" + safeText(s.from || "") + "||" + safeText(s.to || "");
    lastStateCoreSig = nextCoreSig;

    // ===== تحديث runtime =====
    rt.activePeriodIndex = getPeriodIndex(current) || getPeriodIndex(nextP) || getCurrentPeriodIdxFromPayload(payload) || null;
    rt.activeFromHM =
      (stType === "period"
        ? (s.from || (current && current.from))
        : ((nextP && nextP.from) || s.from)) || null;
    rt.dayOver = computeDayOver(payload, baseMs);

    countdownSeconds = null;
    progressRange = { start: null, end: null };
    hasActiveCountdown = false;

    if (
      typeof s.remaining_seconds === "number" &&
      (stType === "period" || stType === "break" || stType === "before")
    ) {
      const serverRem = Math.max(0, Math.floor(s.remaining_seconds));
      // If we just reached 0 locally, and the server returns an older cached snapshot for the same state,
      // don't jump the countdown backwards (e.g., 00:00 -> 05:12). Wait until the state changes.
      if (
        prevCountdown !== null &&
        prevCountdown <= 1 &&
        nextCoreSig &&
        nextCoreSig === prevCoreSig &&
        serverRem > prevCountdown + 10
      ) {
        countdownSeconds = prevCountdown;
      } else {
        countdownSeconds = serverRem;
      }
      hasActiveCountdown = true;
    }

    // If the server says 0 (or we clamped to 0) and we haven't handled this core state yet,
    // trigger the countdown-zero refresh even if we didn't observe a local 1->0 transition.
    if (hasActiveCountdown && typeof countdownSeconds === "number" && countdownSeconds === 0) {
      if (nextCoreSig && nextCoreSig !== lastZeroHandledCoreSig) {
        lastZeroHandledCoreSig = nextCoreSig;
        onCountdownZero();
      }
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
        const prev = countdownSeconds;
        if (countdownSeconds > 0) countdownSeconds -= 1;
        if (prev > 0 && countdownSeconds === 0) onCountdownZero();

        // Handle cases where countdown starts at 0 (server rounding/caching) without a local 1->0 transition.
        if (countdownSeconds === 0 && lastStateCoreSig && lastStateCoreSig !== lastZeroHandledCoreSig) {
          lastZeroHandledCoreSig = lastStateCoreSig;
          onCountdownZero();
        }
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

  async function safeFetchSnapshot(opts) {
    opts = opts || {};
    if (inflight && !opts.force) return inflight;

    const token = getToken();
    const baseUrl = resolveSnapshotUrl();

    const u = new URL(baseUrl, window.location.origin);
    u.searchParams.set("_t", String(Date.now()));

    // If the display page itself has ?nocache=1, propagate it to the snapshot API.
    // This is useful for validating settings switches immediately.
    try {
      const qs = new URLSearchParams(window.location.search);
      if ((qs.get("nocache") || "").trim() === "1") {
        u.searchParams.set("nocache", "1");
      }
    } catch (e) {}

    if (opts.bypassServerCache) {
      u.searchParams.set("nocache", "1");
      u.searchParams.set("_cb", String(Date.now()));
    }

    if (ctrl) {
      try {
        ctrl.abort();
      } catch (e) {}
    }
    ctrl = window.AbortController ? new AbortController() : null;

    const headers = { Accept: "application/json", "X-Display-Token": token || "" };

    if (!opts.bypassEtag) {
      try {
        const prev = localStorage.getItem(etagKey) || "";
        if (prev) headers["If-None-Match"] = prev;
      } catch (e) {}
    } else {
      try {
        localStorage.removeItem(etagKey);
      } catch (e) {}
    }

    const fetchPromise = fetch(u.toString(), {
      method: "GET",
      headers,
      cache: "no-store",
      credentials: "same-origin",
      signal: ctrl ? ctrl.signal : undefined,
    }).then(async (r) => {
      if (r.status === 304) return { _notModified: true };

      if (!r.ok) {
        // 403 عادة تعني: الشاشة مرتبطة بجهاز آخر أو لا يوجد معرف جهاز
        if (r.status === 403) {
          let body = null;
          try {
            body = await r.json();
          } catch (e) {
            body = null;
          }

          const err = body && (body.error || body.code);
          const msg = body && (body.message || body.detail);

          if (err === "screen_bound") {
            showBlocker(
              "هذه الشاشة مرتبطة بجهاز آخر",
              msg || "لا يمكن استخدام نفس الرابط على أكثر من تلفاز. افصل الجهاز من لوحة التحكم لتفعيلها على جهاز جديد."
            );
            stopPolling();
            return null;
          }

          if (err === "missing_device_id") {
            showBlocker(
              "تعذر تعريف الجهاز",
              msg || "أعد فتح رابط الشاشة من المتصفح ثم انتظر ثوانٍ ليتم تفعيل العرض."
            );
            stopPolling();
            return null;
          }

          // 403 أخرى
          showBlocker(
            "لا يمكن عرض الشاشة",
            msg || "تم رفض الوصول. تحقق من الرابط أو راجع إدارة النظام."
          );
          stopPolling();
          return null;
        }

        throw new Error("HTTP " + r.status);
      }

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
        if (isBlocked) return null;
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
    if (isBlocked) return;
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
      renderFeaturedPanel(snap);

      renderStandby(snap.standby || []);
      renderPeriodClasses(snap.period_classes || []);

      ensureDebugOverlay();
      if (isDebug()) {
        const pS = periodsScroller ? periodsScroller.getState() : {};
        const sS = standbyScroller ? standbyScroller.getState() : {};
        setDebugText(
          "ok " +
            new Date().toLocaleTimeString() +
            " | idx=" +
            (rt.activePeriodIndex || "-") +
            " dayOver=" +
            (rt.dayOver ? 1 : 0) +
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

  // ===== Resize: فقط إعادة القياس =====
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
      if (periodsScroller) periodsScroller.recalc();
      if (standbyScroller) standbyScroller.recalc();
      if (dutyScroller) dutyScroller.recalc();
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

    const lite = isLiteMode();
    try {
      body.dataset.lite = lite ? "1" : "0";
    } catch (e) {}

    cfg.REFRESH_EVERY = clamp(parseFloat(body.dataset.refresh || "10") || 10, 5, 120);
    cfg.STANDBY_SPEED = normSpeed(body.dataset.standby || "0.8", 0.8);
    cfg.PERIODS_SPEED = normSpeed(body.dataset.periodsSpeed || "0.5", 0.5);

    cfg.MEDIA_PREFIX = (body.dataset.mediaPrefix || "/media/").toString().trim();
    cfg.SNAPSHOT_URL = (body.dataset.snapshotUrl || "").toString().trim();
    cfg.SERVER_TOKEN = (body.dataset.apiToken || body.dataset.token || "").toString().trim();
    cfg.SCHOOL_TYPE = (body.dataset.schoolType || "").toString().trim();

    try {
      const initTheme = (body.dataset.theme || "").trim();
      if (initTheme) applyTheme(initTheme);
    } catch (e) {}

    try {
      const initAccent = (body.dataset.accentColor || "").trim();
      if (initAccent) applyAccentColor(initAccent);
    } catch (e) {}

    ensureDebugOverlay();
    tickClock();
    startTicker();
    bindFullscreen();

    // init scrollers (مستقلين)
    // For low-end TVs: cap FPS to reduce paint cost.
    const scrollerOpts = lite ? { maxFps: 20 } : undefined;
    periodsScroller = dom.periodClassesTrack ? createScroller(dom.periodClassesTrack, () => cfg.PERIODS_SPEED, scrollerOpts) : null;
    standbyScroller = dom.standbyTrack ? createScroller(dom.standbyTrack, () => cfg.STANDBY_SPEED, scrollerOpts) : null;
    dutyScroller = dom.dutyTrack ? createScroller(dom.dutyTrack, () => cfg.PERIODS_SPEED, scrollerOpts) : null;

    renderAlert("جاري التحميل…", "يتم الآن جلب البيانات من الخادم.");
    scheduleNext(0.2);
  });
})();
