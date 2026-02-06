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
    // Prefer scaling the stage (if present) so fixed-position UI (e.g. fullscreen button)
    // remains truly fixed to the viewport.
    dom.fitRoot = document.getElementById("fitStage") || document.getElementById("fitRoot");

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
    // Not needed anymore - using native 100vh
    return;
  }

  // ===== Professional Auto-fit for TV displays =====
  function isFitDisabled() {
    try {
      const qs = new URLSearchParams(window.location.search);
      const v = (qs.get("fit") || qs.get("autofit") || "").trim().toLowerCase();
      if (v === "0" || v === "false" || v === "no") return true;
    } catch (e) {}
    return false;
  }

  function getFitMargin() {
    // Default: keep a safe border around the UI for TV overscan / browser chrome.
    // 0.95 means: fit inside 95% of the viewport (≈ 2.5% padding each side).
    let m = 0.95;
    try {
      const qs = new URLSearchParams(window.location.search);
      const raw = (qs.get("fitMargin") || qs.get("margin") || "").trim();
      if (raw) {
        const v = parseFloat(raw);
        if (isFinite(v)) m = v;
      }
    } catch (e) {}
    return clamp(m, 0.7, 1);
  }

  function getFitMaxScale() {
    // Allow scaling UP on large TVs (e.g., 4K) to keep UI readable.
    // Can be overridden via ?fitMax=1.6
    let mx = 2;
    try {
      const qs = new URLSearchParams(window.location.search);
      const raw = (qs.get("fitMax") || qs.get("maxScale") || "").trim();
      if (raw) {
        const v = parseFloat(raw);
        if (isFinite(v)) mx = v;
      }
    } catch (e) {}
    return clamp(mx, 1, 3);
  }

  function getFitMode() {
    // ✅ الحل 2: Parameter يدوي للتحكم في وضع الملء
    // ?fitMode=contain → show all content (للشاشات غير القياسية)
    // ?fitMode=cover → fill screen (الوضع الافتراضي)
    try {
      const qs = new URLSearchParams(window.location.search);
      const v = (qs.get("fitMode") || "").trim().toLowerCase();
      if (v === "contain") return "contain";
      if (v === "cover") return "cover";
    } catch (e) {}
    return "cover"; // الافتراضي - لا يتغير السلوك الحالي
  }

  function getAspectThreshold() {
    // ✅ الحل 3: threshold للكشف التلقائي عن الشاشات غير القياسية
    // ?aspectThreshold=0.2 → أكثر تساهلاً
    // الافتراضي: 0.15 (15% فرق)
    let threshold = 0.15;
    try {
      const qs = new URLSearchParams(window.location.search);
      const raw = (qs.get("aspectThreshold") || "").trim();
      if (raw) {
        const v = parseFloat(raw);
        if (isFinite(v) && v > 0) threshold = v;
      }
    } catch (e) {}
    return clamp(threshold, 0.05, 0.5);
  }

  let fitT = null;
  function scheduleFit(ms) {
    if (fitT) clearTimeout(fitT);
    fitT = setTimeout(() => {
      fitT = null;
      applyAutoFit();
    }, Math.max(0, Number(ms) || 0));
  }

  function applyAutoFit() {
    if (!dom.fitRoot) return;

    // allow disabling via ?fit=0 for troubleshooting
    if (isFitDisabled()) {
      try {
        dom.fitRoot.style.transform = "scale(1)";
      } catch (e) {}
      return;
    }

    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    
    if (viewportWidth <= 0 || viewportHeight <= 0) return;

    // Design canvas dimensions (what we designed for)
    const designWidth = 1920;
    const designHeight = 1080;

    // Calculate scale ratios
    const scaleX = viewportWidth / designWidth;
    const scaleY = viewportHeight / designHeight;
    
    // ✅ الحل 2 + 3: تحديد وضع الملء (cover أو contain)
    let fitMode = getFitMode(); // من الـ URL parameter
    
    // ✅ الحل 3: كشف تلقائي للشاشات غير القياسية
    if (fitMode === "cover") { // فقط إذا لم يحدد المستخدم contain يدوياً
      const aspectRatio = viewportWidth / viewportHeight;
      const designAspectRatio = designWidth / designHeight; // 1.778 (16:9)
      const aspectDiff = Math.abs(aspectRatio - designAspectRatio);
      const threshold = getAspectThreshold();
      
      if (aspectDiff > threshold) {
        // شاشة بنسبة مختلفة كثيراً عن 16:9 (مثل IQTouch)
        fitMode = "contain";
        console.log(`[Auto-fit] Non-standard aspect ratio detected (${aspectRatio.toFixed(3)} vs ${designAspectRatio.toFixed(3)}), switching to contain mode`);
      }
    }
    
    // تطبيق الوضع المناسب
    let scale;
    if (fitMode === "contain") {
      // CONTAIN: إظهار كل المحتوى (قد تظهر حواف سوداء)
      scale = Math.min(scaleX, scaleY);
    } else {
      // COVER: ملء الشاشة بالكامل (قد يتم قص الحواف)
      scale = Math.max(scaleX, scaleY);
    }
    
    // Allow scaling UP for large TVs, but cap at reasonable maximum
    const maxScale = getFitMaxScale();
    scale = clamp(scale, 0.5, maxScale);

    // ✅ FIX: Scale from top-left corner to fill screen completely (no centering)
    // transform-origin: top left in CSS ensures content starts from corner
    dom.fitRoot.style.transform = `scale(${scale.toFixed(4)})`;

    try {
      const body = document.body || document.documentElement;
      body.dataset.uiScale = scale.toFixed(4);
      body.dataset.fitMode = fitMode; // للـ debugging
      
      // ✅ FIX: تكبير الخطوط تلقائياً للشاشات الكبيرة
      // إذا كان scale أكبر من 1 (شاشات 4K, 8K, إلخ)
      // نزيد حجم الخط الأساسي لتحسين القراءة
      if (scale > 1) {
        // مثال: scale = 2 (4K) → font-size = 125%
        // مثال: scale = 1.5 (2K) → font-size = 112.5%
        const fontScale = 1 + (scale - 1) * 0.5; // نصف الزيادة
        body.style.fontSize = `${(fontScale * 100).toFixed(1)}%`;
      } else {
        // للشاشات الصغيرة، نبقي الحجم الافتراضي أو نزيده قليلاً
        body.style.fontSize = '100%';
      }
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
    REFRESH_EVERY: 20, // زيادة من 10 إلى 20 لتقليل الاستهلاك بنسبة 50%
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
    refreshJitterFrac: 0, // jitter نسبي ثابت لكل شاشة لتفريق الحمل
    statusEverySec: 0, // adaptive polling interval for status-first mode
    status304Streak: 0, // consecutive status 304 streak
    scheduleRevision: 0, // last known schedule_revision (numeric truth for /status?v=...)
    transitionUntilTs: 0, // while > Date.now(): force snapshot fetch to cross 00:00 boundaries
    transitionBackoffSec: 1.2, // bounded backoff during transition window
    pollStateLastLogTs: 0, // debug-only: last time we logged poll state
    
    // WebSocket state (Phase 2: Dark Launch)
    ws: null, // WebSocket instance
    wsRetryCount: 0, // consecutive connection failures
    wsReconnectTimer: null, // reconnect timer ID
    pendingRev: null, // revision received from WS but not yet fetched
    wsEnabled: false, // feature flag from server (TBD: read from snapshot meta)
    wsPingInterval: null, // keepalive ping timer
    wsMaxRetries: 10, // max reconnection attempts before giving up
  };


  function maybeLogPollState(activeWindow, nextPollSec) {
    if (!isDebug()) return;
    const now = Date.now();
    const last = Number(rt.pollStateLastLogTs) || 0;
    if (last && (now - last) < 10 * 60 * 1000) return; // 10 minutes
    rt.pollStateLastLogTs = now;
    try {
      console.log(
        "[display] poll-state",
        {
          activeWindow: !!activeWindow,
          nextPollSec: Number(nextPollSec) || 0,
          status304Streak: Number(rt.status304Streak) || 0,
          statusEverySec: Number(rt.statusEverySec) || 0,
          scheduleRevision: Number(rt.scheduleRevision) || 0,
          at: new Date().toISOString(),
        }
      );
    } catch (e) {}
  }

  function revStorageKey() {
    // Scope by token to avoid collisions when multiple screens are opened on the same browser.
    const t = (getToken() || "").toString();
    const safe = encodeURIComponent(t).slice(0, 80);
    return "display_rev:" + safe;
  }

  (function initRevision() {
    try {
      const raw = localStorage.getItem(revStorageKey()) || "";
      const n = parseInt(raw, 10);
      rt.scheduleRevision = isNaN(n) ? 0 : Math.max(0, n);
    } catch (e) {
      rt.scheduleRevision = 0;
    }
  })();

  // Pick a stable jitter per page load: ~±25% لتوزيع أفضل للحمل مع عدد كبير من الشاشات
  (function initRefreshJitter() {
    try {
      const v = (Math.random() * 0.5) - 0.25; // -0.25..+0.25 (زيادة من ±15% إلى ±25%)
      rt.refreshJitterFrac = Math.abs(v) < 0.01 ? 0.20 : v;
    } catch (e) {
      rt.refreshJitterFrac = 0.20;
    }
  })();

  function pickTokenFromUrl() {
    try {
      const qs = new URLSearchParams(window.location.search);
      return (qs.get("token") || qs.get("t") || "").trim();
    } catch (e) {
      return "";
    }
  }

  function pickTokenFromSnapshotUrl() {
    try {
      const raw = (cfg.SNAPSHOT_URL || "").toString().trim();
      if (!raw) return "";
      const u = new URL(raw, window.location.origin);
      const path = (u.pathname || "").toString();
      // Supports: /api/display/snapshot/<token>/  (and aliases today/live)
      const m = path.match(/\/api\/display\/(?:snapshot|today|live)\/([^\/]+)\/?$/i);
      if (!m || !m[1]) return "";
      return decodeURIComponent(m[1]).trim();
    } catch (e) {
      return "";
    }
  }

  function getToken() {
    return (cfg.SERVER_TOKEN || pickTokenFromUrl() || pickTokenFromSnapshotUrl() || "").trim();
  }

  function resolveSnapshotUrl() {
    if (cfg.SNAPSHOT_URL) return cfg.SNAPSHOT_URL;
    const t = getToken();
    if (t) return "/api/display/snapshot/" + encodeURIComponent(t) + "/";
    return "/api/display/snapshot/";
  }

  function resolveStatusUrl() {
    // Lightweight endpoint; prefer token in path when available (same pattern as snapshot).
    const t = getToken();
    if (t) return "/api/display/status/" + encodeURIComponent(t) + "/";
    return "/api/display/status/";
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
  // ✅ FIX: حفظ واستعادة serverOffset من localStorage لتجنب القفزة عند التحديث
  let serverOffsetMs = 0;
  try {
    const saved = localStorage.getItem("serverOffsetMs");
    if (saved) {
      const parsed = parseInt(saved, 10);
      if (isFinite(parsed)) {
        serverOffsetMs = parsed;
      }
    }
  } catch (e) {}
  
  // ✅ CLOCK DRIFT DETECTION: مراقبة تغيرات التوقيت المحلي
  let lastLocalTime = Date.now();
  let lastCheckTime = Date.now();
  let clockDriftDetected = false;
  
  // ✅ THROTTLING: منع الطلبات الزائدة على السيرفر
  let lastReSyncTime = 0;
  const RE_SYNC_COOLDOWN = 5000; // 5 ثوانٍ بين كل re-sync
  
  let serverTzOffsetMin = null;
  let serverLocalDateStr = null; // YYYY-MM-DD
  let serverDayStartMs = null; // epoch ms for server local day start
  
  function nowMs() {
    return Date.now() + serverOffsetMs;
  }

  function applyServerNowMs(serverNowMs) {
    const n = Number(serverNowMs);
    if (!isFinite(n) || n <= 0) return;
    const measured = n - Date.now();
    // Smooth small jitter; snap on large drift corrections.
    const delta = measured - serverOffsetMs;
    if (Math.abs(delta) > 30000) {
      serverOffsetMs = measured;
    } else {
      serverOffsetMs = Math.round(serverOffsetMs * 0.8 + measured * 0.2);
    }
    
    // ✅ FIX: حفظ القيمة الجديدة في localStorage
    try {
      localStorage.setItem("serverOffsetMs", String(serverOffsetMs));
    } catch (e) {}
    
    // ✅ تحديث آخر وقت معروف للمراقبة
    lastLocalTime = Date.now();
    lastCheckTime = Date.now();
    clockDriftDetected = false;
  }

  // ✅ CLOCK DRIFT DETECTION: كشف تغييرات التوقيت المحلي الفجائية
  // ⚠️ IMPORTANT: هذه الدالة لا ترسل أي request، فقط تكشف التغيير
  function detectClockDrift() {
    const now = Date.now();
    const expectedElapsed = now - lastCheckTime;
    
    // إذا مر أقل من 100ms، تجاهل (قريب جداً)
    if (expectedElapsed < 100) return false;
    
    // إذا مر أكثر من 3 ثواني، قد يكون tab sleep - تحقق بحذر
    if (expectedElapsed > 3000) {
      lastCheckTime = now;
      lastLocalTime = now;
      return true; // نطلب re-sync لأننا كنا inactive
    }
    
    // حساب الفرق بين الوقت الفعلي والمتوقع
    const actualElapsed = now - lastLocalTime;
    const drift = Math.abs(actualElapsed - expectedElapsed);
    
    // إذا كان الفرق أكثر من ثانية واحدة = تغيير في الوقت المحلي
    if (drift > 1000) {
      lastCheckTime = now;
      lastLocalTime = now;
      clockDriftDetected = true;
      return true;
    }
    
    lastCheckTime = now;
    lastLocalTime = now;
    return false;
  }

  // ✅ THROTTLED RE-SYNC: طلب re-sync مع حماية من الطلبات الزائدة
  // ⚠️ COST PROTECTION: لا يرسل أكثر من request واحد كل 5 ثوانٍ
  function requestReSyncIfNeeded() {
    const now = Date.now();
    const timeSinceLastSync = now - lastReSyncTime;
    
    // ✅ COOLDOWN: إذا كان آخر re-sync قبل أقل من 5 ثوانٍ، تجاهل
    if (timeSinceLastSync < RE_SYNC_COOLDOWN) {
      if (isDebug()) setDebugText(`Re-sync cooldown: ${(RE_SYNC_COOLDOWN - timeSinceLastSync) / 1000}s remaining`);
      return;
    }
    
    // ✅ UPDATE: نسجل وقت آخر re-sync
    lastReSyncTime = now;
    
    // ✅ SEND: الآن فقط نرسل الطلب
    if (isDebug()) setDebugText("Clock drift detected - re-syncing...");
    safeFetchStatus(true).catch(() => {});
  }

  function _parseTzOffsetMinFromIso(iso) {
    const s = (iso || "").toString().trim();
    if (!s) return null;
    // Match trailing timezone: Z or ±HH:MM
    const m = s.match(/(Z|[+-]\d{2}:?\d{2})\s*$/i);
    if (!m || !m[1]) return null;
    const z = m[1].toUpperCase();
    if (z === "Z") return 0;
    const mm = z.match(/^([+-])(\d{2}):?(\d{2})$/);
    if (!mm) return null;
    const sign = mm[1] === "-" ? -1 : 1;
    const hh = parseInt(mm[2], 10);
    const mn = parseInt(mm[3], 10);
    if (!isFinite(hh) || !isFinite(mn)) return null;
    return sign * (hh * 60 + mn);
  }

  function _computeDayStartMs(localDateStr, tzOffsetMin) {
    const ds = (localDateStr || "").toString().trim();
    if (!ds) return null;
    const m = ds.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!m) return null;
    const y = parseInt(m[1], 10);
    const mo = parseInt(m[2], 10);
    const d = parseInt(m[3], 10);
    if (!isFinite(y) || !isFinite(mo) || !isFinite(d)) return null;
    const off = Number(tzOffsetMin);
    if (!isFinite(off)) return null;
    // Day start in server timezone => UTC midnight minus offset.
    return Date.UTC(y, mo - 1, d, 0, 0, 0) - off * 60 * 1000;
  }

  function applyServerCalendar(localDateStr, tzOffsetMin) {
    if (!localDateStr) return;
    const off = Number(tzOffsetMin);
    if (!isFinite(off)) return;
    serverLocalDateStr = String(localDateStr);
    serverTzOffsetMin = off;
    serverDayStartMs = _computeDayStartMs(serverLocalDateStr, serverTzOffsetMin);
  }

  function _serverDayStartMsForBase(baseMs) {
    const off = Number(serverTzOffsetMin);
    if (!isFinite(off)) return null;
    const b = Number(baseMs || nowMs());
    if (!isFinite(b) || b <= 0) return null;
    // Convert to "server local wall clock" by shifting with offset, then use UTC getters.
    const wall = new Date(b + off * 60 * 1000);
    const y = wall.getUTCFullYear();
    const mo = wall.getUTCMonth();
    const d = wall.getUTCDate();
    // Day start in server timezone => UTC midnight minus offset.
    return Date.UTC(y, mo, d, 0, 0, 0) - off * 60 * 1000;
  }

  function serverWallNowDate() {
    // Shift by tz offset and interpret via UTC getters/formatting.
    const off = isFinite(Number(serverTzOffsetMin)) ? Number(serverTzOffsetMin) : 0;
    return new Date(nowMs() + off * 60 * 1000);
  }

  function fmtTimeRange(fromHM, toHM) {
    // Bidi-safe: isolate as LTR so times don't visually flip in RTL UI.
    // U+2066 LRI ... U+2069 PDI
    return "\u2066" + toTimeStr(fromHM) + " → " + toTimeStr(toHM) + "\u2069";
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

    // ✅ FIX: استخدام nowMs() مباشرة بدلاً من baseMs القديم
    // baseMs يتم حسابه مرة واحدة عند بداية معالجة البيانات، لكن serverOffsetMs
    // قد يتم تحديثه أثناء المعالجة، مما يسبب استخدام offset قديم
    // nowMs() تعطي دائماً الوقت الصحيح المتزامن مع السيرفر
    const b = nowMs();
    
    // Prefer server-derived day start to avoid relying on the device timezone.
    // We compute it from server tz offset + base time to stay correct across midnight
    // even if we don't fetch a new snapshot yet.
    const dayStart = _serverDayStartMsForBase(b) || (serverDayStartMs && isFinite(serverDayStartMs) ? Number(serverDayStartMs) : null);
    if (dayStart && isFinite(dayStart)) {
      let t = dayStart + (h * 60 + m) * 60 * 1000;
      // Handle midnight rollover (e.g., base near 23:55 and target 00:05 should be next day).
      const diff = t - b;
      const dayMs = 24 * 60 * 60 * 1000;
      if (diff < -18 * 60 * 60 * 1000) t += dayMs;
      else if (diff > 18 * 60 * 60 * 1000) t -= dayMs;
      return t;
    }

    // Fallback: device timezone (last resort).
    const d = new Date(b);
    return new Date(d.getFullYear(), d.getMonth(), d.getDate(), h, m, 0).getTime();
  }

  function isEnded(endHM, baseMs) {
    const end = hmToMs(endHM, baseMs);
    if (!end) return false;
    // ✅ FIX: استخدام nowMs() دائماً للحصول على الوقت الصحيح المتزامن
    return nowMs() >= end;
  }

  function isNowBetween(startHM, endHM, baseMs) {
    const s = hmToMs(startHM, baseMs);
    const e = hmToMs(endHM, baseMs);
    if (!s || !e) return false;
    // ✅ FIX: استخدام nowMs() دائماً للحصول على الوقت الصحيح المتزامن
    const n = nowMs();
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
    
    // محاولة تحويل لرقم مباشرة
    const n = parseInt(String(raw), 10);
    if (isFinite(n) && n > 0) return n;
    
    // ✅ FIX: استخراج الرقم من النص العربي (مثل "الحصة الثانية" → 2)
    const rawStr = String(raw).trim();
    const arabicMap = {
      "الأولى": 1, "الاولى": 1, "أولى": 1, "اولى": 1,
      "الثانية": 2, "ثانية": 2,
      "الثالثة": 3, "ثالثة": 3,
      "الرابعة": 4, "رابعة": 4,
      "الخامسة": 5, "خامسة": 5,
      "السادسة": 6, "سادسة": 6,
      "السابعة": 7, "سابعة": 7,
      "الثامنة": 8, "ثامنة": 8,
      "التاسعة": 9, "تاسعة": 9,
      "العاشرة": 10, "عاشرة": 10,
      "الحادية عشرة": 11, "حادية عشرة": 11,
      "الثانية عشرة": 12, "ثانية عشرة": 12,
      "الثالثة عشرة": 13, "ثالثة عشرة": 13,
      "الرابعة عشرة": 14, "رابعة عشرة": 14,
      "الخامسة عشرة": 15, "خامسة عشرة": 15,
    };
    
    // البحث عن الرقم في النص
    for (const [key, value] of Object.entries(arabicMap)) {
      if (rawStr.includes(key)) return value;
    }
    
    return null;
  }

  function arabicOrdinalFeminine(n) {
    const idx = parseInt(String(n), 10);
    if (!idx || isNaN(idx) || idx <= 0) return null;

    const ord = [
      "الأولى",
      "الثانية",
      "الثالثة",
      "الرابعة",
      "الخامسة",
      "السادسة",
      "السابعة",
      "الثامنة",
      "التاسعة",
      "العاشرة",
      "الحادية عشرة",
      "الثانية عشرة",
      "الثالثة عشرة",
      "الرابعة عشرة",
      "الخامسة عشرة",
    ];

    if (idx <= ord.length) return ord[idx - 1];
    return null;
  }

  function formatPeriodTitle(p) {
    const idx = getPeriodIndex(p);
    if (!idx) return "الحصة";

    const ord = arabicOrdinalFeminine(idx);
    if (ord) return "الحصة " + ord;

    // fallback for uncommon indices
    return "الحصة رقم " + toArabicDigits(idx);
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

    // ✅ FIX: إخفاء حصص الانتظار التي مضى وقتها
    // حصة الانتظار للحصة X تظهر طوال الحصة X وتختفي عند بداية الحصة X+1
    // مثال: حصة انتظار للحصة 2 تظهر أثناء الحصة 2، وتختفي عند بداية الحصة 3
    
    // 1) فلترة بالأرقام (الأفضل) - نبحث في جميع الحقول الممكنة
    const idx = getPeriodIndex(x);
    
    if (idx && rt.activePeriodIndex) {
      // نعرض الحصص التي >= الحصة الحالية (أي الحصة الحالية والحصص القادمة)
      // مثال: إذا الحصة الحالية = 2، نعرض حصة انتظار 2، 3، 4...
      // عند بداية الحصة 3، حصة انتظار الحصة 2 ستختفي
      const keep = idx >= rt.activePeriodIndex;
      return keep;
    }

    // 2) fallback بالوقت إذا ما فيه رقم (نادر لكن للتوافقية)
    const from = x.from || x.start || x.starts_at;
    if (rt.activeFromHM && from) {
      const a = hmToMs(rt.activeFromHM, baseMs);
      const b = hmToMs(from, baseMs);
      // نعرض فقط الحصص التي وقتها في المستقبل (> وليس >=)
      if (a && b) return b > a;
    }

    // 3) إذا ما نقدر نحدد بالرقم أو الوقت، نعرضه
    // (هذا احتياطي فقط - لا يجب الوصول له في الظروف العادية)
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
    const wall = serverWallNowDate();
    if (dom.clock) {
      setTextIfChanged(
        dom.clock,
        fmt2(wall.getUTCHours()) + ":" + fmt2(wall.getUTCMinutes()) + ":" + fmt2(wall.getUTCSeconds())
      );
    }
    if (dateInfo) cachedDateInfo = dateInfo;

    try {
      const arWeek = new Intl.DateTimeFormat("ar-SA", { weekday: "long", timeZone: "UTC" }).format(wall);
      if (cachedDateInfo && (dom.dateG || dom.dateH)) {
        const g = cachedDateInfo.gregorian || {};
        const h = cachedDateInfo.hijri || {};
        if (dom.dateG) {
          setTextIfChanged(
            dom.dateG,
            arWeek +
              " ، " +
              (g.day || wall.getUTCDate()) +
              " " +
              (g.month_name || g.month || "") +
              " " +
              (g.year || wall.getUTCFullYear()) +
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
        setTextIfChanged(dom.dateG, arWeek + " ، " + wall.getUTCDate() + " / " + (wall.getUTCMonth() + 1) + " / " + wall.getUTCFullYear() + "م");
    } catch (e) {
      try {
        if (dom.dateG) setTextIfChanged(dom.dateG, new Intl.DateTimeFormat("ar-SA", { timeZone: "UTC" }).format(wall));
      } catch (e2) {
        if (dom.dateG) setTextIfChanged(dom.dateG, new Date(nowMs()).toLocaleDateString("ar-SA"));
      }
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

  function optimisticAdvanceToNextBlock() {
    try {
      if (!lastPayloadForFiltering) return false;
      const snap = lastPayloadForFiltering;
      const nextP = snap.next_period || null;
      if (!nextP || typeof nextP !== "object") return false;

      const kind = safeText(nextP.kind || nextP.type || "").trim().toLowerCase();
      const fromHM = safeText(nextP.from || "");
      const toHM = safeText(nextP.to || "");
      if (!fromHM || !toHM) return false;

      const baseMs = nowMs();
      const startMs = hmToMs(fromHM, baseMs);
      const endMs = hmToMs(toHM, baseMs);
      if (!startMs || !endMs || endMs <= startMs) return false;

      const n = baseMs;
      const isBefore = n < startMs;
      const isActive = n >= startMs && n < endMs;

      let stType = kind || "period";
      if (isBefore) stType = "before";

      let badge = "حالة اليوم";
      let title = "";

      // Always prefer showing what's next (reduces the feeling of being "stuck" on transitions).
      let nextTitle = "";
      try {
        if ((kind || "").toLowerCase() === "period") nextTitle = formatPeriodTitle(nextP);
        else if ((kind || "").toLowerCase() === "break") nextTitle = safeText(nextP.label || "استراحة");
        else nextTitle = safeText(nextP.label || "");
      } catch (e) {
        nextTitle = safeText(nextP.label || "");
      }

      if (stType === "period") {
        badge = "درس";
        title = nextTitle || formatPeriodTitle(nextP);
      } else if (stType === "break") {
        badge = "استراحة";
        title = nextTitle || safeText(nextP.label || "استراحة");
      } else if (stType === "before") {
        badge = "انتظار";
        title = nextTitle || "انتظار";
      }

      const range = fmtTimeRange(fromHM, toHM);

      // Update headline immediately.
      setTextIfChanged(dom.heroTitle, title);
      setTextIfChanged(dom.heroRange, range);
      setTextIfChanged(dom.badgeKind, badge);

      // Update countdown/progress.
      let rem;
      // استخدام nowMs() للحصول على الوقت المتزامن مع السيرفر
      const nowMsValue = nowMs();
      if (isBefore) rem = Math.max(0, Math.floor((startMs - nowMsValue) / 1000));
      else rem = Math.max(0, Math.floor((endMs - nowMsValue) / 1000));

      countdownSeconds = rem;
      hasActiveCountdown = true;
      progressRange = { start: startMs, end: endMs };

      // Keep runtime in sync so list filtering doesn't lag.
      if (stType === "period") {
        rt.activePeriodIndex = getPeriodIndex(nextP) || rt.activePeriodIndex;
        rt.activeFromHM = fromHM;
      } else if (stType === "break") {
        rt.activeFromHM = fromHM;
      } else if (stType === "before") {
        // If we're waiting for a known next block, keep runtime aligned with its start.
        rt.activeFromHM = fromHM;
      }

      // Prevent duplicate 00:00 handling for the just-applied optimistic state.
      lastStateCoreSig = stType + "||" + safeText(title || "") + "||" + safeText(fromHM || "") + "||" + safeText(toHM || "");
      lastZeroHandledCoreSig = lastStateCoreSig;

      return true;
    } catch (e) {
      return false;
    }
  }

  function onCountdownZero() {
    if (isBlocked) return;
    const now = nowMs();
    if (now - lastCountdownZeroAt < 2000) return;
    lastCountdownZeroAt = now;

    // UX guarantee: if we already know what's next (next_period), show it immediately.
    // This avoids waiting for schedule_revision changes or cache TTLs.
    try {
      optimisticAdvanceToNextBlock();
    } catch (e) {}

    // Time-based transitions (period/break) don't bump schedule_revision, so /status may stay 304.
    // Enter a short window where we fetch snapshots directly until the UI advances.
    try {
      rt.transitionUntilTs = nowMs() + 15000; // 15s max
      rt.transitionBackoffSec = 1.2;
    } catch (e) {}

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
    // Add a randomized jitter to distribute load across multiple seconds (not milliseconds).
    // مع 200 شاشة، نحتاج توزيع على 10-15 ثانية لتجنب الضغط المفاجئ
    try {
      // Base random jitter: 1-15 seconds
      const baseJitter = 1000 + Math.floor(Math.random() * 14000);
      
      // School-based deterministic jitter: adds 0-29 seconds based on school ID
      // This ensures schools spread their requests even more during simultaneous events
      let schoolJitter = 0;
      try {
        const schoolId = parseInt(cfg.SERVER_TOKEN.split(':')[0]) || 0;
        schoolJitter = (schoolId % 30) * 1000; // 0-29 seconds
      } catch (e) {}
      
      const totalJitter = baseJitter + schoolJitter; // 1-44 seconds total distribution
      
      setTimeout(() => {
        try {
          forceRefreshNow("countdown_zero");
        } catch (e) {
          try {
            scheduleNext(0.2);
          } catch (e2) {}
        }
      }, totalJitter);
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
        transition: true,
        reason: reason || "manual",
      });

      if (!snap || (snap && snap._notModified)) {
        return;
      }

      // If we got rate-limited exactly at the boundary, retry via the normal loop with backoff.
      if (snap && snap._rateLimited) {
        try {
          const base = Number(rt.transitionBackoffSec) || 1.2;
          rt.transitionBackoffSec = Math.min(10, Math.max(1.2, base * 1.7));
        } catch (e) {}
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

      // If we successfully crossed into a new block with a fresh countdown, exit transition window.
      try {
        const sOk = (snap && snap.state) || {};
        const remOk = typeof sOk.remaining_seconds === "number" ? Math.max(0, Math.floor(sOk.remaining_seconds)) : null;
        if (remOk !== null && remOk > 0) {
          rt.transitionUntilTs = 0;
          rt.transitionBackoffSec = 1.2;
        }
      } catch (e) {}

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
              safeFetchSnapshot({ force: true, bypassEtag: true, bypassServerCache: true, transition: true, reason: "countdown_zero_retry" })
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
                      const now2 = nowMs();
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
        const inTrans = nowMs() < (Number(rt.transitionUntilTs) || 0);
        if (inTrans) {
          scheduleNext(Number(rt.transitionBackoffSec) || 1.2);
        } else {
          scheduleNext(cfg.REFRESH_EVERY);
        }
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
    const range = fmtTimeRange(cur.from || stateObj.from, cur.to || stateObj.to);

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
      // ✅ تحسين performance: lazy loading للصور
      img.loading = "lazy";
      // ✅ تحسين security: منع CORS issues
      img.crossOrigin = "anonymous";
      // ✅ منع layout shift أثناء تحميل الصورة
      img.style.width = "100%";
      img.style.height = "100%";
      img.style.objectFit = "cover";
      img.src =
        src ||
        // ✨ أيقونة مسطحة نظيفة للتميز - Clean Excellence Badge 2026
        "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 200'%3E%3Crect width='200' height='200' fill='%231e293b'/%3E%3Cpath d='M100,50 L115,85 L155,85 L125,110 L135,150 L100,125 L65,150 L75,110 L45,85 L85,85 Z' fill='%23fbbf24'/%3E%3Ccircle cx='100' cy='100' r='10' fill='%23fff'/%3E%3C/svg%3E";

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

    // Luxury container
    const row = document.createElement("div");
    row.className =
      "relative flex items-center justify-between gap-5 px-6 py-4 rounded-2xl " +
      "bg-gradient-to-l from-white/5 to-white/[0.02] border border-white/10 " +
      "shadow-[0_4px_20px_rgba(0,0,0,0.2)] backdrop-blur-md overflow-hidden group";

    // Glow effect via pseudo-element manually
    const glow = document.createElement("div");
    glow.className = "absolute left-0 top-0 w-1 h-full bg-gradient-to-b from-indigo-400 to-purple-500 opacity-0 transition-opacity duration-300 group-hover:opacity-100";
    row.appendChild(glow);

    const left = document.createElement("div");
    left.className = "flex items-center gap-5 min-w-0 z-10";

    // Premium Avatar
    const avatar = document.createElement("div");
    avatar.className =
      "w-12 h-12 rounded-full bg-gradient-to-br from-indigo-500/20 to-purple-500/20 " +
      "border border-white/10 shadow-inner flex items-center justify-center " +
      "text-indigo-200 text-lg font-black shrink-0";
    avatar.textContent = teacher ? teacher.slice(0, 1) : "—";

    const meta = document.createElement("div");
    meta.className = "min-w-0 flex flex-col justify-center";

    const nm = document.createElement("div");
    nm.className = "text-xl font-bold text-white truncate drop-shadow-sm";
    nm.textContent = teacher || "—";

    const sub = document.createElement("div");
    sub.className = "flex items-center gap-2 text-sm text-indigo-200/70 truncate mt-0.5";
    // Location icon
    const locIcon = document.createElement("span");
    locIcon.textContent = "📍";
    locIcon.className = "opacity-60 grayscale";
    
    const locText = document.createElement("span");
    locText.textContent = location || "غير محدد";
    
    sub.appendChild(locIcon);
    sub.appendChild(locText);

    meta.appendChild(nm);
    meta.appendChild(sub);
    left.appendChild(avatar);
    left.appendChild(meta);

    // Badge
    const badge = document.createElement("div");
    const isSup = dutyType === "supervision";
    badge.className =
      "relative z-10 shrink-0 px-4 py-1.5 rounded-full text-sm font-bold border shadow-lg " +
      (isSup
        ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/30"
        : "bg-amber-500/20 text-amber-200 border-amber-500/30");
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

    // Legacy/back-compat: if server includes `payload.now`, keep it as a fallback sync source.
    // Prefer X-Server-Time-MS header (handled in safeFetchSnapshot) because payload bodies may be cached.
    if (payload.now) {
      const serverMs = new Date(payload.now).getTime();
      if (!isNaN(serverMs)) applyServerNowMs(serverMs);

      // Learn server timezone offset + local date (stable even when payload is cached).
      try {
        const offMin = _parseTzOffsetMinFromIso(payload.now);
        if (offMin !== null) {
          // Prefer YYYY-MM-DD from payload.now itself (most reliable across clients and schemas).
          let dstr = null;
          const s = String(payload.now || "").trim();
          const m = s.match(/^(\d{4}-\d{2}-\d{2})/);
          if (m && m[1]) dstr = m[1];
          if (!dstr) {
            const meta0 = payload.meta || {};
            dstr = meta0.date || meta0.local_date || meta0.day || null;
          }
          if (dstr) applyServerCalendar(String(dstr), offMin);
        }
      } catch (e) {}
    }

    const baseMs = nowMs();
    hydrateBrand(payload);

    const settings = payload.settings || {};
    const meta = payload.meta || {};

    // Persist schedule revision so /status?v=... remains authoritative.
    try {
      const rawRev = meta.schedule_revision ?? meta.scheduleRevision ?? meta.rev;
      const n = parseInt(String(rawRev), 10);
      if (!isNaN(n) && n >= 0) {
        rt.scheduleRevision = n;
        try {
          localStorage.setItem(revStorageKey(), String(n));
        } catch (e) {}
      }
    } catch (e) {}

    if (settings.school_type) {
      cfg.SCHOOL_TYPE = settings.school_type;
    }

    if (typeof settings.refresh_interval_sec === "number" && settings.refresh_interval_sec > 0) {
      let nInt = clamp(settings.refresh_interval_sec, 5, 864000);
      // Add a small *percentage* jitter always to reduce stampedes (especially at scale).
      // Keep it bounded and never below 5s.
      const jf = Number(rt.refreshJitterFrac) || 0;
      if (isFinite(jf) && jf !== 0) {
        nInt = clamp(Math.round(nInt * (1 + jf)), 5, 864000);
      }
      if (Math.abs(nInt - cfg.REFRESH_EVERY) > 0.001) cfg.REFRESH_EVERY = nInt;

      // Keep status-first polling in sync by default.
      if (!rt.statusEverySec || rt.statusEverySec < 1) rt.statusEverySec = cfg.REFRESH_EVERY;
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

    if (stType === "period" || stType === "break" || stType === "before") {
      let localCalc = null;
      // ✅ FIX: استخدام nowMs() المباشر لضمان التزامن الدقيق مع الساعة المعروضة
      // نحسب الوقت لحظياً لتجنب أي تأخير في المعالجة
      const currentMs = nowMs();
      const targetHM = stType === "before" ? s.from : s.to;
      if (targetHM) {
        const tMs = hmToMs(targetHM, currentMs);
        // الحساب: وقت الهدف - الوقت الحالي = الوقت المتبقي
        if (tMs) localCalc = Math.floor((tMs - currentMs) / 1000);
      }

      const serverRem =
        typeof s.remaining_seconds === "number"
          ? Math.max(0, Math.floor(s.remaining_seconds))
          : null;

      // Use local calculation if valid (sanity check: result is between -12h and +24h)
      if (localCalc !== null && localCalc > -43200 && localCalc < 86400) {
        countdownSeconds = Math.max(0, localCalc);
      } else if (serverRem !== null) {
        countdownSeconds = serverRem;
      }

      if (countdownSeconds !== null) hasActiveCountdown = true;
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
    let range = (s.from || s.to) ? fmtTimeRange(s.from, s.to) : fmtTimeRange(null, null);
    let badge = "حالة اليوم";

    if (stType === "period") {
      badge = "درس";
      title = formatPeriodTitle(current);
    } else if (stType === "break") {
      badge = "استراحة";
      title = safeText(s.label || "استراحة");
    } else if (stType === "before") {
      badge = "انتظار";
      title = safeText(s.label || "انتظار");
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
      // ✅ CLOCK DRIFT DETECTION: فحص تغييرات التوقيت كل ثانية
      // ⚠️ ZERO COST: هذا الفحص محلي بالكامل، لا يرسل أي request
      if (detectClockDrift()) {
        // ✅ THROTTLED RE-SYNC: طلب واحد فقط كل 5 ثوانٍ
        requestReSyncIfNeeded();
      }
      
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
          const hh = Math.floor(countdownSeconds / 3600);
          const mm = Math.floor((countdownSeconds % 3600) / 60);
          const ss = countdownSeconds % 60;
          
          // عرض HH:MM:SS إذا كان الوقت أكثر من ساعة، وإلا MM:SS
          const timeDisplay = hh > 0 
            ? fmt2(hh) + ":" + fmt2(mm) + ":" + fmt2(ss)
            : fmt2(mm) + ":" + fmt2(ss);
          
          setTextIfChanged(dom.countdown, timeDisplay);
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
  let inflightStatus = null;
  let ctrlStatus = null;
  const etagKey = "display_etag_" + (location.pathname || "/");

  // Device ID (stable per browser/device)
  // تحقق سريع: localStorage.getItem("school_display_device_id")
  const deviceIdKey = "school_display_device_id";
  let memDeviceId = "";

  function fallbackDeviceId() {
    // No cookies. Prefer crypto, fall back to a random-ish stable value.
    try {
      if (window.crypto && typeof window.crypto.randomUUID === "function") {
        return window.crypto.randomUUID();
      }
    } catch (e) {}

    try {
      if (window.crypto && typeof window.crypto.getRandomValues === "function") {
        const buf = new Uint8Array(16);
        window.crypto.getRandomValues(buf);
        const hex = Array.from(buf)
          .map((b) => (b < 16 ? "0" : "") + b.toString(16))
          .join("");
        return "d-" + hex;
      }
    } catch (e) {}

    return "d-" + String(Math.random()).slice(2) + "-" + String(Date.now());
  }

  function getOrCreateDeviceId() {
    if (memDeviceId) return memDeviceId;
    try {
      const existing = (localStorage.getItem(deviceIdKey) || "").trim();
      if (existing) {
        memDeviceId = existing;
        return memDeviceId;
      }
      const created = fallbackDeviceId();
      localStorage.setItem(deviceIdKey, created);
      memDeviceId = created;
      return memDeviceId;
    } catch (e) {
      // If localStorage is blocked, fall back to in-memory per page load.
      memDeviceId = fallbackDeviceId();
      return memDeviceId;
    }
  }

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
    // Always provide a stable device identifier.
    // Some CDNs/proxies may strip non-standard request headers, so also include it in the query.
    const deviceId = getOrCreateDeviceId();
    u.searchParams.set("dk", deviceId);

    // Versioned cache key: ensure CDNs (or misconfigured cache rules) do not keep serving
    // an older snapshot across revisions. This is NOT a random cache-buster; it changes only
    // when the school's revision changes.
    try {
      u.searchParams.set("rev", String(rt.scheduleRevision || 0));
    } catch (e) {}

    // Production-safe transition refresh: used at countdown==0 to force a fresh snapshot build
    // without requiring `?nocache=1` (which is intentionally blocked in production).
    // Server-side is expected to apply stampede protection (shared lock/wait).
    if (opts.transition) {
      try {
        u.searchParams.set("transition", "1");
      } catch (e) {}
    }

    // IMPORTANT (Production): never add cache-busting params to snapshot requests.
    // Allow it only in explicit debug mode (?debug=1).
    if (isDebug()) {
      // Cache-busting is *opt-in* even in debug mode: require `?nocache=1` explicitly.
      // This prevents accidental `?debug=1` deployments from spamming the snapshot API.
      let pageNoCache = false;
      try {
        const qs = new URLSearchParams(window.location.search);
        pageNoCache = (qs.get("nocache") || "").trim() === "1";
        if (pageNoCache) u.searchParams.set("nocache", "1");
      } catch (e) {}

      if (opts.bypassServerCache && pageNoCache) {
        u.searchParams.set("nocache", "1");
        u.searchParams.set("_t", String(Date.now()));
        u.searchParams.set("_cb", String(Date.now()));
      }
    }

    if (ctrl) {
      try {
        ctrl.abort();
      } catch (e) {}
    }
    ctrl = window.AbortController ? new AbortController() : null;

    const headers = {
      Accept: "application/json",
      "X-Display-Token": token || "",
      "X-Display-Device": deviceId,
    };

    if (!opts.bypassEtag) {
      try {
        // Important: on a cold page load, we may not have any in-memory payload yet.
        // If we send If-None-Match and get 304, the UI can get stuck showing "جاري التحميل".
        // So only enable 304 optimization after we've rendered at least one payload.
        const canUse304 = !!lastPayloadForFiltering;
        if (canUse304) {
          const prev = localStorage.getItem(etagKey) || "";
          if (prev) headers["If-None-Match"] = prev;
        }
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
      // Never send cookies on snapshot.
      credentials: "omit",
      signal: ctrl ? ctrl.signal : undefined,
    }).then(async (r) => {
      // Server clock sync: works even when response body is cached or 304.
      try {
        const h = r.headers.get("X-Server-Time-MS");
        if (h) applyServerNowMs(h);
      } catch (e) {}

      if (r.status === 304) return { _notModified: true };

      if (r.status === 429) {
        // Rate-limited: don't hammer the server with fast retries.
        return { _rateLimited: true };
      }

      if (!r.ok) {
        // Diagnostics: log status + response body (if possible)
        let raw = "";
        try {
          raw = await r.text();
        } catch (e) {
          raw = "";
        }
        if (raw) {
          console.warn("[snapshot] HTTP", r.status, raw);
        } else {
          console.warn("[snapshot] HTTP", r.status);
        }

        // 403 عادة تعني: الشاشة مرتبطة بجهاز آخر أو لا يوجد معرف جهاز
        if (r.status === 403) {
          let body = null;
          try {
            body = raw ? JSON.parse(raw) : null;
          } catch (e) {
            body = null;
          }

          const err = body && (body.error || body.code || body.detail);
          const msg = body && (body.message || body.detail);

          if (err === "screen_bound") {
            showBlocker(
              "هذه الشاشة مرتبطة بجهاز آخر",
              msg || "لا يمكن استخدام نفس الرابط على أكثر من تلفاز. افصل الجهاز من لوحة التحكم لتفعيلها على جهاز جديد."
            );
            stopPolling();
            return null;
          }

          if (err === "missing_device_id" || err === "device_required") {
            showBlocker(
              "تعذر تعريف الجهاز",
              msg || "أعد فتح رابط الشاشة من المتصفح ثم انتظر ثوانٍ ليتم تفعيل العرض."
            );
            stopPolling();
            return null;
          }

          if (err === "device_mismatch") {
            showBlocker(
              "هذه الشاشة مرتبطة بجهاز آخر",
              msg || "لا يمكن استخدام نفس الرابط على أكثر من جهاز. افتح الشاشة من الجهاز الأصلي أو أعد ربطها من لوحة التحكم."
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

        // Non-403 errors: do not crash; keep polling.
        // If body is JSON with detail, include it in the error message.
        let msg = "";
        try {
          const obj = raw ? JSON.parse(raw) : null;
          msg = obj && (obj.detail || obj.message) ? String(obj.detail || obj.message) : "";
        } catch (e) {}

        throw new Error("HTTP " + r.status + (msg ? " | " + msg : ""));
      }

      const et = r.headers && r.headers.get ? (r.headers.get("ETag") || "") : "";
      if (et) {
        try {
          localStorage.setItem(etagKey, et);
        } catch (e) {}
      }

      return r.json();
    });

    // Dynamic timeout: 15s for first load, 9s for subsequent refreshes
    // First load may need more time for cache building
    const timeoutMs = lastPayloadForFiltering ? 9000 : 15000;
    
    inflight = withTimeout(fetchPromise, timeoutMs, () => {
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

  async function safeFetchStatus(opts) {
    opts = opts || {};
    if (inflightStatus && !opts.force) return inflightStatus;

    const token = getToken();
    const baseUrl = resolveStatusUrl();

    const u = new URL(baseUrl, window.location.origin);
    // Keep device id consistent across endpoints (useful for server-side binding/diagnostics).
    const deviceId = getOrCreateDeviceId();
    u.searchParams.set("dk", deviceId);

    // Source of truth: numeric revision comparison.
    u.searchParams.set("v", String(rt.scheduleRevision || 0));

    // Defensive: /status must never be cached.
    // If a CDN cache rule accidentally includes /api/display/status/*, this guarantees each poll
    // is unique and reaches origin.
    try {
      u.searchParams.set("_ts", String(Date.now()));
    } catch (e) {}

    if (ctrlStatus) {
      try {
        ctrlStatus.abort();
      } catch (e) {}
    }
    ctrlStatus = window.AbortController ? new AbortController() : null;

    const headers = {
      Accept: "application/json",
      "X-Display-Token": token || "",
      "X-Display-Device": deviceId,
    };

    // Intentionally do NOT send If-None-Match for /status.

    const fetchPromise = fetch(u.toString(), {
      method: "GET",
      headers,
      cache: "no-store",
      credentials: "omit",
      signal: ctrlStatus ? ctrlStatus.signal : undefined,
    }).then(async (r) => {
      // Server clock sync: keep countdown/clock aligned even when we only poll /status.
      try {
        const h = r.headers.get("X-Server-Time-MS");
        if (h) applyServerNowMs(h);
      } catch (e) {}

      if (r.status === 304) {
        // If server provides revision in headers, learn it even on 304.
        try {
          const revH = r.headers.get("X-Schedule-Revision");
          if (revH) {
            const n = parseInt(String(revH), 10);
            if (!isNaN(n) && n >= 0) {
              rt.scheduleRevision = n;
              try {
                localStorage.setItem(revStorageKey(), String(n));
              } catch (e) {}
            }
          }
        } catch (e) {}
        return { _notModified: true };
      }

      if (!r.ok) {
        // Don't block the display on status errors; just fall back to snapshot.
        return { fetch_required: true };
      }

      const body = await r.json().catch(() => null);

      // Prefer header revision if present (authoritative even if body is missing).
      try {
        const revH = r.headers.get("X-Schedule-Revision");
        if (revH) {
          const n = parseInt(String(revH), 10);
          if (!isNaN(n) && n >= 0) {
            rt.scheduleRevision = n;
            try {
              localStorage.setItem(revStorageKey(), String(n));
            } catch (e) {}
          }
        }
      } catch (e) {}

      // Keep local revision in sync if server provides it.
      if (body && typeof body === "object" && typeof body.schedule_revision !== "undefined") {
        const n = parseInt(String(body.schedule_revision), 10);
        if (!isNaN(n) && n >= 0) {
          rt.scheduleRevision = n;
          try {
            localStorage.setItem(revStorageKey(), String(n));
          } catch (e) {}
        }
      }

      return body || { fetch_required: true };
    });

    inflightStatus = withTimeout(fetchPromise, 6000, () => {
      if (ctrlStatus) {
        try {
          ctrlStatus.abort();
        } catch (e) {}
      }
    })
      .catch(() => {
        // Silent fallback.
        return { fetch_required: true };
      })
      .finally(() => {
        inflightStatus = null;
      });

    return await inflightStatus;
  }

  // ===== Refresh loop =====
  let pollTimer = null;
  let failStreak = 0;
  let isFetching = false;

  function shouldPauseWhenHidden() {
    // Many embedded/TV browsers misreport Page Visibility as hidden even while displayed.
    // In those cases, pausing polling makes the screen appear "خامله" and prevents wake-up.
    const ua = (navigator && navigator.userAgent) ? String(navigator.userAgent) : "";
    const isTvUa = /SmartTV|NetCast|Web0S|webOS|Tizen|HbbTV|Viera|BRAVIA|Roku|MiTV|Android TV|AFTB|AFTS|CrKey/i.test(ua);
    return !isTvUa;
  }

  function scheduleNext(sec) {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(refreshLoop, Math.max(0.2, sec) * 1000);
  }

  async function refreshLoop() {
    if (isBlocked) return;
    if (isFetching) return; // Prevent overlapping loops

    // Never skip the very first snapshot fetch because that can leave the UI blank.
    // Also, only pause when hidden on browsers that reliably support it.
    if (document.hidden && !!lastPayloadForFiltering && shouldPauseWhenHidden()) {
      scheduleNext(cfg.REFRESH_EVERY);
      return;
    }

    isFetching = true;
    let snap = null;

    try {
      // Status-first polling: ask the cheap endpoint first, and only fetch snapshot when needed.
      // Initial load still fetches snapshot directly.
      if (!lastPayloadForFiltering) {
        // Critical: on first load, always fetch a full body.
        // If we send If-None-Match and get 304 while we have no payload in memory,
        // the UI can remain stuck on the loading state.
        snap = await safeFetchSnapshot({ bypassEtag: true });
      } else {
        const inTrans = nowMs() < (Number(rt.transitionUntilTs) || 0);
        if (inTrans) {
          // Cross boundary reliably: revision may not change, so don't rely on /status.
          snap = await safeFetchSnapshot({ bypassEtag: true });
        } else {
          const st = await safeFetchStatus();
          if (st && st._notModified) {
            rt.status304Streak = (Number(rt.status304Streak) || 0) + 1;

            // Backoff on 304 to reduce polling load when nothing changes.
            // Tuned for large deployments (many screens): bounded, with stable jitter.
            const base = Math.max(2, Number(cfg.REFRESH_EVERY) || 10);
            const isActiveWin = !!(lastPayloadForFiltering && lastPayloadForFiltering.meta && lastPayloadForFiltering.meta.is_active_window);
            const minEvery = isActiveWin ? Math.min(10, Math.max(8, base)) : 60;
            const maxEvery = isActiveWin ? 45 : 300;

            const backoffFactor = isActiveWin ? 1.7 : 2.0;

            const streak = Math.max(1, Number(rt.status304Streak) || 1);
            const pow = Math.pow(backoffFactor, Math.min(10, Math.max(0, streak - 1)));
            const jitter = 1 + (Number(rt.refreshJitterFrac) || 0);
            let nextEvery = (minEvery * pow) * jitter;
            nextEvery = Math.min(maxEvery, Math.max(minEvery, nextEvery));
            // Round to 0.1s to avoid noisy drift.
            rt.statusEverySec = Math.round(nextEvery * 10) / 10;

            maybeLogPollState(isActiveWin, rt.statusEverySec || cfg.REFRESH_EVERY);

            isFetching = false;
            failStreak = 0;
            scheduleNext(rt.statusEverySec || cfg.REFRESH_EVERY);
            if (isDebug()) {
              ensureDebugOverlay();
              setDebugText(
                "status 304 not-modified | streak=" + String(streak) + " | every=" + String(rt.statusEverySec || cfg.REFRESH_EVERY) + "s | " + new Date().toLocaleTimeString()
              );
            }
            return;
          }

          // Default behavior: fetch snapshot unless server says it's not required.
          const need = !st || st.fetch_required !== false;
          if (need) {
            rt.status304Streak = 0;
            rt.statusEverySec = Number(cfg.REFRESH_EVERY) || 10;
            snap = await safeFetchSnapshot();
          } else {
            rt.status304Streak = 0;
            rt.statusEverySec = Number(cfg.REFRESH_EVERY) || 10;
            isFetching = false;
            failStreak = 0;
            scheduleNext(rt.statusEverySec || cfg.REFRESH_EVERY);
            if (isDebug()) {
              ensureDebugOverlay();
              setDebugText("status says no-fetch | " + new Date().toLocaleTimeString());
            }
            return;
          }
        }
      }
    } catch (e) {
        // Should be caught inside safeFetchSnapshot but just in case
        snap = null;
    }

    if (snap && snap._rateLimited) {
      // Stronger backoff on 429 to avoid bursts.
      isFetching = false;
      failStreak = 0;
      const inTrans = nowMs() < (Number(rt.transitionUntilTs) || 0);
      let wait;
      if (inTrans) {
        const base = Number(rt.transitionBackoffSec) || 1.2;
        wait = Math.min(10, Math.max(1.2, base * 1.7));
        rt.transitionBackoffSec = wait;
      } else {
        const base = Number(cfg.REFRESH_EVERY) || 10;
        wait = Math.min(120, Math.max(15, base * 2));
      }
      scheduleNext(wait);
      if (isDebug()) {
        ensureDebugOverlay();
        setDebugText("snapshot 429 rate-limited | backoff=" + String(wait) + "s | " + new Date().toLocaleTimeString());
      }
      return;
    }

    if (!snap) {
      isFetching = false;
      failStreak += 1;
      // INITIAL LOAD FAST RETRY WITH EXPONENTIAL BACKOFF:
      // If we haven't successfully loaded data yet, retry with exponential backoff
      // to avoid overwhelming the server. This helps with cold starts while preventing
      // thundering herd when multiple screens fail simultaneously.
      let backoff;
      if (!lastPayloadForFiltering) {
          // Exponential backoff: 2s → 3s → 4.5s → 6.7s → 10s → 15s → 22.5s → 30s (max)
          const maxRetries = 8;
          const retryCount = Math.min(failStreak, maxRetries);
          const baseBackoff = Math.min(30, 2 * Math.pow(1.5, retryCount));
          
          // Add ±25% jitter to distribute load across time
          const jitterFactor = 0.75 + Math.random() * 0.5; // 0.75 to 1.25
          backoff = baseBackoff * jitterFactor;
      } else {
          backoff = Math.min(60, cfg.REFRESH_EVERY + failStreak * 5);
      }
      scheduleNext(backoff);
      return;
    }

    if (snap && snap._notModified) {
      // Recovery: if a 304 arrives before any successful render, force a full fetch.
      if (!lastPayloadForFiltering) {
        isFetching = false;
        scheduleNext(0.5);
        try {
          snap = await safeFetchSnapshot({ force: true, bypassEtag: true });
        } catch (e) {
          // fall through to retry path below
        }
        if (snap && !snap._notModified) {
          // continue to render below
        } else {
          return;
        }
      }

      isFetching = false;
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

      // Phase 2: Initialize WebSocket (feature flag from server)
      try {
        const wsEnabledFromServer = !!(snap && snap.meta && snap.meta.ws_enabled);
        if (wsEnabledFromServer && !rt.wsEnabled) {
          // Feature enabled by server, init WS
          rt.wsEnabled = true;
          if (isDebug()) console.log("[WS] feature enabled by server, initializing");
          initWebSocket();
        } else if (!wsEnabledFromServer && rt.wsEnabled) {
          // Feature disabled by server, close WS
          rt.wsEnabled = false;
          if (rt.ws) {
            if (isDebug()) console.log("[WS] feature disabled by server, closing");
            try {
              rt.ws.close();
            } catch (e) {}
            rt.ws = null;
          }
          if (rt.wsPingInterval) {
            clearInterval(rt.wsPingInterval);
            rt.wsPingInterval = null;
          }
          if (rt.wsReconnectTimer) {
            clearTimeout(rt.wsReconnectTimer);
            rt.wsReconnectTimer = null;
          }
        }
      } catch (e) {
        if (isDebug()) console.warn("[WS] feature flag check error:", e);
      }

      // If we crossed into a new block with a fresh countdown, exit transition window.
      try {
        const sOk = (snap && snap.state) || {};
        const remOk = typeof sOk.remaining_seconds === "number" ? Math.max(0, Math.floor(sOk.remaining_seconds)) : null;
        if (remOk !== null && remOk > 0) {
          rt.transitionUntilTs = 0;
          rt.transitionBackoffSec = 1.2;
        }
      } catch (e) {}

      // After DOM updates (cards/items counts change), re-fit to avoid clipping/scroll.
      scheduleFit(0);

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
    } finally {
        isFetching = false;
    }

    {
      const inTrans = nowMs() < (Number(rt.transitionUntilTs) || 0);
      scheduleNext(inTrans ? (Number(rt.transitionBackoffSec) || 1.2) : cfg.REFRESH_EVERY);
    }
  }



  // ===== WebSocket: Realtime Push Invalidate (Phase 2: Dark Launch) =====
  
  function getDeviceId() {
    // Use same device ID as HTTP requests (localStorage: display_device_id)
    try {
      let dk = localStorage.getItem("display_device_id");
      if (!dk) {
        dk = "web_" + Math.random().toString(36).substring(2) + Date.now().toString(36);
        localStorage.setItem("display_device_id", dk);
      }
      return dk;
    } catch (e) {
      return "web_" + Math.random().toString(36).substring(2);
    }
  }

  function initWebSocket() {
    // Only attempt WS if feature enabled (from server meta or flag)
    if (!rt.wsEnabled) {
      if (isDebug()) console.log("[WS] disabled by feature flag");
      return;
    }
    
    // Don't reconnect if max retries exceeded
    if (rt.wsRetryCount >= rt.wsMaxRetries) {
      if (isDebug()) console.log("[WS] max retries exceeded, giving up");
      return;
    }
    
    // Close existing connection if any
    if (rt.ws) {
      try {
        rt.ws.close();
      } catch (e) {}
      rt.ws = null;
    }
    
    // Clear any reconnect timer
    if (rt.wsReconnectTimer) {
      clearTimeout(rt.wsReconnectTimer);
      rt.wsReconnectTimer = null;
    }
    
    const token = getToken();
    const deviceId = getDeviceId();
    
    if (!token || !deviceId) {
      if (isDebug()) console.log("[WS] missing token or device ID");
      return;
    }
    
    // Build WebSocket URL
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const wsUrl = `${proto}//${host}/ws/display/?token=${encodeURIComponent(token)}&dk=${encodeURIComponent(deviceId)}`;
    
    try {
      if (isDebug()) console.log(`[WS] connecting to ${wsUrl.substring(0, 80)}...`);
      
      rt.ws = new WebSocket(wsUrl);
      
      rt.ws.onopen = function() {
        rt.wsRetryCount = 0; // reset on successful connection
        if (isDebug()) console.log("[WS] connected");
        
        // Start keepalive ping (every 30s)
        if (rt.wsPingInterval) clearInterval(rt.wsPingInterval);
        rt.wsPingInterval = setInterval(() => {
          if (rt.ws && rt.ws.readyState === WebSocket.OPEN) {
            try {
              rt.ws.send(JSON.stringify({ type: "ping" }));
            } catch (e) {
              if (isDebug()) console.warn("[WS] ping failed:", e);
            }
          }
        }, 30000);
      };
      
      rt.ws.onmessage = function(event) {
        try {
          const msg = JSON.parse(event.data);
          
          if (msg.type === "pong") {
            // Keepalive response
            return;
          }
          
          if (msg.type === "invalidate") {
            const newRev = parseInt(msg.revision, 10);
            if (isNaN(newRev)) return;
            
            if (isDebug()) console.log(`[WS] invalidate received: revision ${newRev}`);
            
            // Store pending revision
            rt.pendingRev = newRev;
            
            // If not currently fetching, trigger immediate refresh
            if (!isFetching) {
              if (isDebug()) console.log("[WS] triggering immediate refresh");
              rt.status304Streak = 0; // reset backoff
              rt.statusEverySec = Number(cfg.REFRESH_EVERY) || 10;
              scheduleNext(0.5); // slight delay to avoid storm if multiple messages arrive
            } else {
              if (isDebug()) console.log("[WS] fetch in progress, will pick up pendingRev on next cycle");
            }
          }
        } catch (e) {
          if (isDebug()) console.warn("[WS] message parse error:", e);
        }
      };
      
      rt.ws.onerror = function(err) {
        if (isDebug()) console.warn("[WS] error:", err);
      };
      
      rt.ws.onclose = function(event) {
        // Clear ping interval
        if (rt.wsPingInterval) {
          clearInterval(rt.wsPingInterval);
          rt.wsPingInterval = null;
        }
        
        const code = event.code;
        const reason = event.reason || "";
        
        if (isDebug()) console.log(`[WS] closed: code=${code} reason=${reason}`);
        
        // Don't reconnect on auth failures (4400, 4403, 4408)
        if (code === 4400 || code === 4403 || code === 4408) {
          if (isDebug()) console.log("[WS] auth failure, not reconnecting");
          rt.wsEnabled = false; // disable WS
          return;
        }
        
        // Exponential backoff: 1s → 2s → 4s → 8s → 16s → 32s → 60s (max)
        rt.wsRetryCount++;
        const baseDelay = Math.min(60, Math.pow(2, Math.min(5, rt.wsRetryCount - 1)));
        const jitter = 0.5 + Math.random(); // 0.5x to 1.5x jitter
        const delay = baseDelay * jitter;
        
        if (rt.wsRetryCount >= rt.wsMaxRetries) {
          if (isDebug()) console.log(`[WS] max retries (${rt.wsMaxRetries}) exceeded, giving up`);
          return;
        }
        
        if (isDebug()) console.log(`[WS] reconnecting in ${delay.toFixed(1)}s (attempt ${rt.wsRetryCount})`);
        
        rt.wsReconnectTimer = setTimeout(() => {
          initWebSocket();
        }, delay * 1000);
      };
      
    } catch (e) {
      if (isDebug()) console.error("[WS] init error:", e);
      rt.wsRetryCount++;
      
      // Retry with backoff
      if (rt.wsRetryCount < rt.wsMaxRetries) {
        const delay = Math.min(60, Math.pow(2, rt.wsRetryCount - 1));
        if (isDebug()) console.log(`[WS] retrying in ${delay}s`);
        rt.wsReconnectTimer = setTimeout(() => {
          initWebSocket();
        }, delay * 1000);
      }
    }
  }



  // ===== Resize: فقط إعادة القياس =====
  let resizeT = null;
  window.addEventListener(
    "resize",
    () => {
      if (resizeT) clearTimeout(resizeT);
      resizeT = setTimeout(() => {
        setVhVar();
        applyAutoFit();
        if (periodsScroller) periodsScroller.recalc();
        if (standbyScroller) standbyScroller.recalc();
        if (dutyScroller) dutyScroller.recalc();
      }, 160);
    },
    { passive: true }
  );

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      // ✅ عند العودة للصفحة، نتحقق من تزامن الوقت
      // ⚠️ THROTTLED: محمي بـ cooldown لمنع الطلبات الزائدة
      detectClockDrift(); // reset counters
      requestReSyncIfNeeded(); // throttled request
      
      if (periodsScroller) periodsScroller.recalc();
      if (standbyScroller) standbyScroller.recalc();
      if (dutyScroller) dutyScroller.recalc();
      scheduleFit(0);
      scheduleNext(0.25);
    }
  });

  // ✅ CLOCK SYNC: عند focus على النافذة، نتحقق من التزامن
  // ⚠️ THROTTLED: محمي بـ cooldown لمنع الطلبات الزائدة
  window.addEventListener("focus", () => {
    detectClockDrift();
    requestReSyncIfNeeded(); // throttled request
  }, { passive: true });

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
    scheduleFit(0);

    // TVs often load web fonts late; re-fit when font metrics are final.
    try {
      if (document.fonts && document.fonts.ready && typeof document.fonts.ready.then === "function") {
        document.fonts.ready.then(() => scheduleFit(0)).catch(() => {});
      }
    } catch (e) {}

    // Also re-fit after full load (images/layout settle)
    try {
      window.addEventListener(
        "load",
        () => {
          scheduleFit(0);
        },
        { passive: true, once: true }
      );
    } catch (e) {}

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

    // init scrollers (مستقلين)
    // For low-end TVs: cap FPS to reduce paint cost.
    const scrollerOpts = lite ? { maxFps: 20 } : undefined;
    periodsScroller = dom.periodClassesTrack ? createScroller(dom.periodClassesTrack, () => cfg.PERIODS_SPEED, scrollerOpts) : null;
    standbyScroller = dom.standbyTrack ? createScroller(dom.standbyTrack, () => cfg.STANDBY_SPEED, scrollerOpts) : null;
    dutyScroller = dom.dutyTrack ? createScroller(dom.dutyTrack, () => cfg.PERIODS_SPEED, scrollerOpts) : null;

    renderAlert("جاري التحميل…", "يتم الآن جلب البيانات من الخادم.");
    
    // ✅ FIX: جلب التوقيت من السيرفر فوراً عند التحميل لتقليل القفزة
    // نستدعي /status أو /snapshot مباشرة للحصول على X-Server-Time-MS
    (async function syncTimeOnBoot() {
      try {
        // إذا لم يكن لدينا offset محفوظ، نجلبه فوراً
        const savedOffset = localStorage.getItem("serverOffsetMs");
        if (!savedOffset || savedOffset === "0") {
          // استدعاء سريع للحصول على التوقيت
          await safeFetchStatus();
        }
      } catch (e) {
        // ignore - سيتم المحاولة مرة أخرى في refreshLoop
      }
    })();
    
    scheduleNext(0.2);
  });
})();
