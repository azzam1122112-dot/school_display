(function () {
  var body = document.body;
  var REFRESH_EVERY = parseFloat(body.dataset.refresh || "30") || 30;
  var STANDBY_SPEED = parseFloat(body.dataset.standby || "0.8") || 0.8;
  var PERIODS_SPEED = parseFloat(body.dataset.periodsSpeed || "0.5") || 0.5;
  // عدد العناصر (البطاقات) التي عندها نُجبِر التمرير حتى لو لم يزد المحتوى عن ارتفاع الكرت.
  var STANDBY_MIN_ITEMS_FOR_SCROLL = 4;
  var PERIODS_MIN_ITEMS_FOR_SCROLL = 4;
  var SERVER_TOKEN = body.dataset.apiToken || "";

  var api = {
    today: "/api/display/today/",
    standby: "/api/standby/today/",
    ann: "/api/announcements/active/",
    exc: "/api/announcements/excellence/",
    settings: "/api/display/settings/",
    periodClasses: "/api/display/current-classes/"
  };

  var AR_MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"];
  var HIJRI_MONTHS = ["محرم", "صفر", "ربيع الأول", "ربيع الآخر", "جمادى الأولى", "جمادى الآخرة", "رجب", "شعبان", "رمضان", "شوال", "ذو القعدة", "ذو الحجة"];

  var THEMES = {
    indigo: { p: "#6366f1", s: "#a855f7", soft: "rgba(99, 102, 241, 0.2)", text: "#c7d2fe", b: "rgba(129, 140, 248, 0.3)" },
    sky: { p: "#0ea5e9", s: "#3b82f6", soft: "rgba(14, 165, 233, 0.2)", text: "#bae6fd", b: "rgba(56, 189, 248, 0.3)" },
    emerald: { p: "#10b981", s: "#14b8a6", soft: "rgba(16, 185, 129, 0.2)", text: "#a7f3d0", b: "rgba(52, 211, 153, 0.3)" },
    rose: { p: "#f43f5e", s: "#ec4899", soft: "rgba(244, 63, 94, 0.2)", text: "#fecdd3", b: "rgba(251, 113, 133, 0.3)" },
    amber: { p: "#f59e0b", s: "#f97316", soft: "rgba(245, 158, 11, 0.2)", text: "#fde68a", b: "rgba(251, 191, 36, 0.3)" }
  };

  var $ = function (id) { return document.getElementById(id); };
  var fmt2 = function (n) { n = Number(n) || 0; return n < 10 ? "0" + n : String(n); };

  function applyTheme(name) {
    var t = THEMES[name] || THEMES.indigo;
    var r = document.documentElement.style;
    r.setProperty("--c-primary", t.p);
    r.setProperty("--c-secondary", t.s);
    r.setProperty("--c-bg-soft", t.soft);
    r.setProperty("--c-text", t.text);
    r.setProperty("--c-border", t.b);
  }

  function hmToDate(hm) {
    if (!hm) return null;
    var parts = String(hm).split(":");
    if (parts.length < 2) return null;
    var h = parseInt(parts[0], 10);
    var m = parseInt(parts[1], 10);
    if (isNaN(h) || isNaN(m)) return null;
    var d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), d.getDate(), h, m, 0);
  }

  function isEnded(endHM) {
    var end = hmToDate(endHM);
    if (!end) return false;
    return Date.now() >= end.getTime();
  }

  function isNowBetween(startHM, endHM) {
    var s = hmToDate(startHM);
    var e = hmToDate(endHM);
    if (!s || !e) return false;
    var n = Date.now();
    return n >= s.getTime() && n < e.getTime();
  }

  function toTimeStr(t) {
    if (!t) return "--:--";
    var parts = String(t).split(":");
    if (parts.length < 2) return "--:--";
    return fmt2(parts[0]) + ":" + fmt2(parts[1]);
  }

  var clockEl = $("clock");
  var dateGEl = $("dateGregorian");
  var dateHEl = $("dateHijri");
  var showHijri = false;
  var cachedDateInfo = null;

  function toggleDateDisplay() {
    showHijri = !showHijri;
    if (!dateGEl || !dateHEl) return;
    if (showHijri) {
      dateGEl.classList.remove("translate-y-0", "opacity-100");
      dateGEl.classList.add("-translate-y-8", "opacity-0");
      dateHEl.classList.remove("translate-y-8", "opacity-0");
      dateHEl.classList.add("translate-y-0", "opacity-100");
    } else {
      dateGEl.classList.remove("-translate-y-8", "opacity-0");
      dateGEl.classList.add("translate-y-0", "opacity-100");
      dateHEl.classList.remove("translate-y-0", "opacity-100");
      dateHEl.classList.add("translate-y-8", "opacity-0");
    }
  }

  function tickClock(dateInfo) {
    var now = new Date();
    if (clockEl) {
      clockEl.textContent = fmt2(now.getHours()) + ":" + fmt2(now.getMinutes());
    }
    if (dateInfo) cachedDateInfo = dateInfo;
    var arWeek = new Intl.DateTimeFormat("ar-SA", { weekday: "long" }).format(now);
    if (cachedDateInfo) {
      var g = cachedDateInfo.gregorian || {};
      var h = cachedDateInfo.hijri || {};
      var gMonth = g.month_name || AR_MONTHS[now.getMonth()] || g.month;
      var hMonth = h.month_name || (h.month ? HIJRI_MONTHS[h.month - 1] : "") || h.month;
      var gText = arWeek + " ، " + (g.day || now.getDate()) + " " + gMonth + " " + (g.year || now.getFullYear()) + "م";
      var hText = arWeek + " ، " + (h.day || "") + " " + hMonth + " " + (h.year || "") + "هـ";
      if (dateGEl) dateGEl.textContent = gText;
      if (dateHEl) dateHEl.textContent = hText;
    } else {
      if (dateGEl) {
        var gm = AR_MONTHS[now.getMonth()];
        dateGEl.textContent = arWeek + " ، " + now.getDate() + " " + gm + " " + now.getFullYear() + "م";
      }
    }
  }

  var circleEl = $("circleProgress");
  var progressBar = $("progressBar");
  var countdownEl = $("countdown");
  var countdownWrapper = null;
  if (circleEl && circleEl.parentElement && circleEl.parentElement.nextElementSibling) {
    countdownWrapper = circleEl.parentElement.nextElementSibling;
  }
  var CIRC_TOTAL = 339.292;
  var countdownSeconds = null;
  var progressRange = { start: null, end: null };
  var hasActiveCountdown = false;

  function setRing(pct) {
    if (!circleEl) return;
    var clamped = Math.max(0, Math.min(100, pct));
    var off = CIRC_TOTAL * (1 - clamped / 100);
    circleEl.style.strokeDashoffset = String(off);
  }

  var finishedPeriodIndices = new Set();
  var lastScheduleJSON = "";
  var lastSettingsJSON = "";
  var mainTimer = null;
  var sbAnimFrame = null;
  var standbyItemsCache = [];

  // scroll لجدول الحصة الحالية
  var periodAnimFrame = null;
  var periodItemsCache = [];
  var lastPeriodJSON = "";

  var annList = [];
  var annIdx = 0;
  var annTimer = null;
  var alertContainer = $("alertContainer");

  var LEVEL_STYLES = {
    urgent: { bg: "bg-red-500/20", text: "text-red-400" },
    warning: { bg: "bg-amber-500/20", text: "text-amber-400" },
    info: { bg: "bg-blue-500/20", text: "text-blue-400" },
    success: { bg: "bg-green-500/20", text: "text-green-400" }
  };

  var exList = [];
  var exPtr = 0;
  var exTimer = null;
  var EX_INT = 8000;
  var exSlot = $("exSlot");
  var exIndexEl = $("exIndex");
  var exTotalEl = $("exTotal");

  function resolveImageURL(raw) {
    if (!raw) return "";
    var s = String(raw).trim();
    if (!s) return "";
    if (/^data:image\//i.test(s) || /^blob:/i.test(s)) return s;
    if (/^https?:\/\//i.test(s)) return s.replace(/^http:\/\//i, "//");
    var pref = document.body.dataset.mediaPrefix || "/media/";
    if (pref.charAt(pref.length - 1) !== "/") pref = pref + "/";
    return pref + s.replace(/^\.?\/*/, "");
  }

  function renderExcellence(items) {
    var list = Array.isArray(items) ? items : [];
    list = list.filter(function (x) {
      return x && (x.teacher_name || x.name || (x.teacher && x.teacher.name));
    });
    if (JSON.stringify(list) === JSON.stringify(exList)) return;
    exList = list;
    if (exTotalEl) exTotalEl.textContent = String(exList.length || 0);
    if (!exSlot) return;
    if (!exList.length) {
      if (exTimer) {
        clearInterval(exTimer);
        exTimer = null;
      }
      exSlot.innerHTML = '<div class="h-full flex items-center justify-center text-xs md:text-sm text-slate-300">لا يوجد متميزون حالياً</div>';
      return;
    }
    exPtr = exPtr % exList.length;
    showExcellence(exPtr);
    if (!exTimer && exList.length > 1) {
      exTimer = setInterval(function () {
        showExcellence(exPtr + 1);
      }, EX_INT);
    }
  }

  function showExcellence(i) {
    if (!exList.length || !exSlot) return;
    exPtr = (i + exList.length) % exList.length;
    if (exIndexEl) exIndexEl.textContent = String(exPtr + 1);
    var e = exList[exPtr] || {};
    var teacher = e.teacher || {};
    var rawSrc = e.image_src || e.photo_url || e.image_url || e.photo || e.image || e.avatar || teacher.photo_url || teacher.image_url || teacher.photo || teacher.image;
    var src = resolveImageURL(rawSrc);
    var name = e.teacher_name || e.name || teacher.name || "—";
    var reason = e.reason || "";
    if (reason.length > 120) reason = reason.slice(0, 117) + "…";
    exSlot.style.opacity = "0";
    setTimeout(function () {
      exSlot.innerHTML = "";
      var wrapper = document.createElement("div");
      wrapper.className = "relative h-full w-full bg-slate-900";
      if (src) {
        var blurDiv = document.createElement("div");
        blurDiv.className = "absolute inset-0 overflow-hidden";
        var blurImg = document.createElement("img");
        blurImg.src = src;
        blurImg.className = "w-full h-full object-cover opacity-30 blur-xl scale-110";
        blurDiv.appendChild(blurImg);
        wrapper.appendChild(blurDiv);
        var mainImg = document.createElement("img");
        mainImg.src = src;
        mainImg.className = "absolute inset-0 w-full h-full object-contain z-10";
        mainImg.alt = name;
        wrapper.appendChild(mainImg);
      } else {
        var fb = document.createElement("div");
        fb.className = "absolute inset-0 bg-gradient-to-br from-indigo-900 to-purple-900";
        wrapper.appendChild(fb);
      }
      var gradient = document.createElement("div");
      gradient.className = "absolute inset-0 bg-gradient-to-t from-black/90 via-black/40 to-transparent z-20";
      wrapper.appendChild(gradient);
      var textContainer = document.createElement("div");
      textContainer.className = "absolute bottom-0 left-0 right-0 p-4 z-30";
      var nameDiv = document.createElement("div");
      nameDiv.className = "font-bold text-white text-xl leading-tight mb-1 drop-shadow-md";
      nameDiv.textContent = name;
      textContainer.appendChild(nameDiv);
      if (reason) {
        var reasonDiv = document.createElement("div");
        reasonDiv.className = "text-xs text-slate-200 line-clamp-2 drop-shadow";
        reasonDiv.textContent = reason;
        textContainer.appendChild(reasonDiv);
      }
      wrapper.appendChild(textContainer);
      exSlot.appendChild(wrapper);
      exSlot.style.opacity = "1";
    }, 250);
  }

  function renderStandby(items) {
    var active = Array.isArray(items) ? items : [];
    active = active.filter(function (x) {
      if (!x) return false;
      if (!x.period_index) return true;
      var idx = parseInt(x.period_index, 10);
      if (isNaN(idx)) return true;
      return !finishedPeriodIndices.has(idx);
    });
    active.sort(function (a, b) {
      var pa = parseInt(a.period_index || "0", 10) || 0;
      var pb = parseInt(b.period_index || "0", 10) || 0;
      if (pa !== pb) return pa - pb;
      var ta = a.teacher_name || "";
      var tb = b.teacher_name || "";
      return ta.localeCompare(tb);
    });
    var currentJSON = JSON.stringify(active);
    if (currentJSON === lastStandbyJSON) return;
    lastStandbyJSON = currentJSON;
    standbyItemsCache = active.slice();
    var countEl = $("sbCount");
    if (countEl) countEl.textContent = String(active.length) + " حصة";
    var track = $("standbyTrack");
    if (!track) return;
    if (sbAnimFrame) {
      cancelAnimationFrame(sbAnimFrame);
      sbAnimFrame = null;
    }
    track.innerHTML = "";
    track.style.transform = "translateY(0)";
    if (!active.length) {
      track.innerHTML = '<div class="text-center text-xs md:text-sm text-slate-400 py-12">لا توجد حصص انتظار مسجلة اليوم</div>';
      return;
    }
    var block = function (x) {
      var div = document.createElement("div");
      div.className = "bg-white/5 border border-white/10 rounded-xl p-3 flex flex-col justify-between backdrop-blur-sm hover:bg-white/10 transition-colors";
      var header = document.createElement("div");
      header.className = "flex items-center justify-between mb-2";
      var periodBadge = document.createElement("div");
      periodBadge.className = "bg-slate-900/60 text-slate-100 font-bold px-2 py-0.5 rounded text-sm num-font";
      periodBadge.textContent = "ح " + (x.period_index || "—");
      var classBadge = document.createElement("div");
      classBadge.className = "text-[10px] text-slate-300 bg-black/20 px-2 py-0.5 rounded";
      classBadge.textContent = x.class_name || "";
      header.appendChild(periodBadge);
      header.appendChild(classBadge);
      var teacherName = document.createElement("div");
      teacherName.className = "font-semibold text-white text-sm truncate";
      teacherName.textContent = x.teacher_name || "";
      div.appendChild(header);
      div.appendChild(teacherName);
      return div;
    };
    var contentDiv = document.createElement("div");
    contentDiv.className = "standby-grid pb-4";
    active.forEach(function (item) {
      contentDiv.appendChild(block(item));
    });
    track.appendChild(contentDiv);
    setTimeout(startStandbyScroll, 120);
  }

  var lastStandbyJSON = "";

  function findViewportForTrack(trackEl) {
    if (!trackEl) return null;
    var vp = trackEl.parentElement;
    while (vp && !vp.classList.contains("standby-viewport")) {
      vp = vp.parentElement;
    }
    return vp || null;
  }

  function startStandbyScroll() {
    var track = $("standbyTrack");
    var viewport = findViewportForTrack(track);
    if (!track || !viewport) return;
    if (sbAnimFrame) {
      cancelAnimationFrame(sbAnimFrame);
      sbAnimFrame = null;
    }
    track.style.transform = "translateY(0)";
    while (track.children.length > 1) {
      track.removeChild(track.lastElementChild);
    }
    var contentDiv = track.firstElementChild;
    if (!contentDiv) return;
    var contentHeight = contentDiv.offsetHeight;
    var viewHeight = viewport.offsetHeight;

    // نُجبر التمرير إذا كان عدد حصص الانتظار كبيراً بما يكفي حتى لو لم يزد طول المحتوى عن ارتفاع الكرت.
    var forceScroll = standbyItemsCache && standbyItemsCache.length >= STANDBY_MIN_ITEMS_FOR_SCROLL;

    if (!forceScroll && contentHeight <= viewHeight + 4) {
      return;
    }

    var clone = contentDiv.cloneNode(true);
    clone.setAttribute("aria-hidden", "true");
    track.appendChild(clone);
    var y = 0;
    var speed = STANDBY_SPEED;
    function loop() {
      y += speed;
      if (y >= contentHeight) {
        y = 0;
      }
      track.style.transform = "translateY(-" + y + "px)";
      sbAnimFrame = requestAnimationFrame(loop);
    }
    sbAnimFrame = requestAnimationFrame(loop);
  }

  function startPeriodScroll() {
    var track = $("periodClassesTrack");
    var viewport = findViewportForTrack(track);
    if (!track || !viewport) return;
    if (periodAnimFrame) {
      cancelAnimationFrame(periodAnimFrame);
      periodAnimFrame = null;
    }
    track.style.transform = "translateY(0)";
    while (track.children.length > 1) {
      track.removeChild(track.lastElementChild);
    }
    var contentDiv = track.firstElementChild;
    if (!contentDiv) return;
    var contentHeight = contentDiv.offsetHeight;
    var viewHeight = viewport.offsetHeight;

    // نُجبر التمرير إذا كان عدد الحصص الجارية كبيراً بما يكفي حتى لو لم يزد طول المحتوى عن ارتفاع الكرت.
    var forceScroll = periodItemsCache && periodItemsCache.length >= PERIODS_MIN_ITEMS_FOR_SCROLL;

    if (!forceScroll && contentHeight <= viewHeight + 4) {
      return;
    }

    var clone = contentDiv.cloneNode(true);
    clone.setAttribute("aria-hidden", "true");
    track.appendChild(clone);
    var y = 0;
    var speed = PERIODS_SPEED;
    function loop() {
      y += speed;
      if (y >= contentHeight) {
        y = 0;
      }
      track.style.transform = "translateY(-" + y + "px)";
      periodAnimFrame = requestAnimationFrame(loop);
    }
    periodAnimFrame = requestAnimationFrame(loop);
  }

  window.addEventListener("resize", function () {
    if (standbyItemsCache.length) startStandbyScroll();
    if (periodItemsCache.length) startPeriodScroll();
  });

  function mountAnnouncements(items) {
    var newItems = Array.isArray(items) ? items : [];
    if (JSON.stringify(newItems) === JSON.stringify(annList)) return;
    annList = newItems;
    if (!alertContainer) return;
    if (!annList.length) {
      alertContainer.classList.add("hidden");
      alertContainer.innerHTML = "";
      if (annTimer) {
        clearInterval(annTimer);
        annTimer = null;
      }
      return;
    }
    alertContainer.classList.remove("hidden");
    if (annTimer) {
      clearInterval(annTimer);
      annTimer = null;
    }
    showNextAnn();
    if (annList.length > 1) {
      annTimer = setInterval(showNextAnn, 5000);
    }
  }

  function showNextAnn() {
    if (!annList.length || !alertContainer) return;
    annIdx = annIdx % annList.length;
    var item = annList[annIdx] || {};
    var level = item.level || "info";
    var style = LEVEL_STYLES[level] || LEVEL_STYLES.info;
    var el = document.createElement("div");
    el.className = "absolute inset-0 flex items-center justify-start px-4 md:px-6 alert-enter";
    var wrapper = document.createElement("div");
    wrapper.className = "flex items-center gap-3 w-full";
    var iconSpan = document.createElement("span");
    iconSpan.className = "flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-full " + style.bg + " " + style.text + " animate-pulse";
    var iconSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    iconSvg.setAttribute("class", "w-5 h-5");
    iconSvg.setAttribute("viewBox", "0 0 24 24");
    iconSvg.setAttribute("fill", "none");
    iconSvg.setAttribute("stroke", "currentColor");
    var iconPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    if (level === "success") {
      iconPath.setAttribute("d", "M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z");
    } else if (level === "urgent" || level === "warning") {
      iconPath.setAttribute("d", "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z");
    } else {
      iconPath.setAttribute("d", "M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z");
    }
    iconPath.setAttribute("stroke-linecap", "round");
    iconPath.setAttribute("stroke-linejoin", "round");
    iconPath.setAttribute("stroke-width", "2");
    iconSvg.appendChild(iconPath);
    iconSpan.appendChild(iconSvg);
    var textDiv = document.createElement("div");
    textDiv.className = "flex flex-col md:flex-row md:items-center gap-1 md:gap-3 overflow-hidden";
    var titleSpan = document.createElement("span");
    titleSpan.className = "text-white font-bold text-base md:text-lg whitespace-nowrap";
    titleSpan.textContent = item.title || "";
    textDiv.appendChild(titleSpan);
    if (item.body) {
      var sep = document.createElement("span");
      sep.className = "hidden md:inline text-white/40";
      sep.textContent = "|";
      var bodySpan = document.createElement("span");
      bodySpan.className = "text-white/80 text-xs md:text-sm truncate";
      bodySpan.textContent = item.body;
      textDiv.appendChild(sep);
      textDiv.appendChild(bodySpan);
    }
    wrapper.appendChild(iconSpan);
    wrapper.appendChild(textDiv);
    el.appendChild(wrapper);
    if (alertContainer.firstElementChild) {
      var old = alertContainer.firstElementChild;
      old.classList.remove("alert-enter", "alert-enter-active");
      old.classList.add("alert-exit", "alert-exit-active");
      setTimeout(function () {
        if (old.parentNode === alertContainer) old.parentNode.removeChild(old);
      }, 450);
    }
    alertContainer.appendChild(el);
    void el.offsetWidth;
    el.classList.add("alert-enter-active");
    el.classList.remove("alert-enter");
    annIdx = (annIdx + 1) % annList.length;
  }

  async function safeFetch(url) {
    try {
      var urlObj = new URL(url, window.location.origin);
      urlObj.searchParams.append("_t", String(Date.now()));
      var currentParams = new URLSearchParams(window.location.search);
      var token = currentParams.get("token");
      if (!token && SERVER_TOKEN) token = SERVER_TOKEN;
      if (!token) {
        return null;
      }
      urlObj.searchParams.append("token", token);
      var r = await fetch(urlObj.toString(), { headers: { Accept: "application/json" } });
      if (!r.ok) throw new Error(String(r.status));
      return await r.json();
    } catch (e) {
      console.error(e);
      return null;
    }
  }

  async function checkSettings() {
    var s = await safeFetch(api.settings);
    if (!s) return;
    var relevant = {
      name: s.name,
      theme: s.theme,
      logo_url: s.logo_url,
      refresh_interval_sec: s.refresh_interval_sec,
      standby_scroll_speed: s.standby_scroll_speed,
      periods_scroll_speed: s.periods_scroll_speed
    };
    var current = JSON.stringify(relevant);
    if (!lastSettingsJSON) {
      lastSettingsJSON = current;
      if (s.theme) applyTheme(s.theme);
      if (typeof s.refresh_interval_sec === "number" && s.refresh_interval_sec > 0) {
        REFRESH_EVERY = s.refresh_interval_sec;
      }
      if (typeof s.standby_scroll_speed === "number" && s.standby_scroll_speed > 0) {
        STANDBY_SPEED = s.standby_scroll_speed;
      }
      if (typeof s.periods_scroll_speed === "number" && s.periods_scroll_speed > 0) {
        PERIODS_SPEED = s.periods_scroll_speed;
      }
      return;
    }
    if (current !== lastSettingsJSON) {
      window.location.reload();
    }
  }

  function renderPeriodClasses(payload) {
    if (!payload) return;
    var periodIndex = payload.period_index || payload.index || null;
    var items = payload.classes || payload.items || [];
    if (!Array.isArray(items)) items = [];
    var currentJSON = JSON.stringify({ idx: periodIndex, items: items });
    if (currentJSON === lastPeriodJSON) return;
    lastPeriodJSON = currentJSON;
    periodItemsCache = items.slice();
    var countEl = $("pcCount");
    if (countEl) {
      countEl.textContent = String(items.length) + " فصل";
    }
    var track = $("periodClassesTrack");
    if (!track) return;
    if (periodAnimFrame) {
      cancelAnimationFrame(periodAnimFrame);
      periodAnimFrame = null;
    }
    track.innerHTML = "";
    track.style.transform = "translateY(0)";
    if (!items.length) {
      track.innerHTML = '<div class="text-center text-xs md:text-sm text-slate-400 py-12">لا توجد حصة جارية حالياً</div>';
      return;
    }
    var list = document.createElement("div");
    list.className = "flex flex-col gap-2 pb-4";
    items.forEach(function (x) {
      var clsName = x.class || x.class_name || x.classroom || "—";
      var subj = x.subject || x.subject_name || "";
      var teacher = x.teacher || x.teacher_name || "";
      var row = document.createElement("div");
      row.className = "bg-white/5 border border-white/10 rounded-xl px-3 py-2 flex items-center justify-between text-xs md:text-sm";
      var left = document.createElement("div");
      left.className = "font-bold text-indigo-300";
      left.textContent = clsName;
      var right = document.createElement("div");
      right.className = "text-slate-200 flex-1 flex flex-col md:flex-row md:items-center md:justify-end gap-1 md:gap-2";
      var subjSpan = document.createElement("span");
      subjSpan.className = "text-slate-200";
      subjSpan.textContent = subj || "—";
      right.appendChild(subjSpan);
      if (teacher) {
        var teacherSpan = document.createElement("span");
        teacherSpan.className = "text-slate-300";
        teacherSpan.textContent = teacher;
        right.appendChild(teacherSpan);
      }
      row.appendChild(left);
      row.appendChild(right);
      list.appendChild(row);
    });
    track.appendChild(list);
    setTimeout(startPeriodScroll, 120);
  }

  function renderState(payload) {
    if (!payload) return;
    var s = payload.state || {};
    var day = payload.day || {};
    var settings = payload.settings || {};
    if (settings.theme) applyTheme(settings.theme);
    if (typeof settings.refresh_interval_sec === "number" && settings.refresh_interval_sec > 0 && settings.refresh_interval_sec !== REFRESH_EVERY) {
      REFRESH_EVERY = settings.refresh_interval_sec;
      if (mainTimer) clearInterval(mainTimer);
      mainTimer = setInterval(refreshAll, Math.max(10, REFRESH_EVERY) * 1000);
    }
    if (typeof settings.standby_scroll_speed === "number" && settings.standby_scroll_speed > 0 && settings.standby_scroll_speed !== STANDBY_SPEED) {
      STANDBY_SPEED = settings.standby_scroll_speed;
      if (sbAnimFrame) startStandbyScroll();
    }
    if (typeof settings.periods_scroll_speed === "number" && settings.periods_scroll_speed > 0 && settings.periods_scroll_speed !== PERIODS_SPEED) {
      PERIODS_SPEED = settings.periods_scroll_speed;
      if (periodAnimFrame) startPeriodScroll();
    }
    tickClock(payload.date_info || null);
    finishedPeriodIndices.clear();
    if (Array.isArray(day.periods)) {
      day.periods.forEach(function (p) {
        if (!p) return;
        if (isEnded(p.ends_at)) {
          var idx = parseInt(p.index, 10);
          if (!isNaN(idx)) finishedPeriodIndices.add(idx);
        }
      });
    }
    var currentScheduleList = $("currentScheduleList");
    if (currentScheduleList) {
      currentScheduleList.innerHTML = "";
      var now = new Date();
      var periodsNow = [];
      if (Array.isArray(day.periods)) {
        periodsNow = day.periods.filter(function (p) {
          if (!p) return false;
          var start = hmToDate(p.starts_at);
          var end = hmToDate(p.ends_at);
          if (!start || !end) return false;
          return now >= start && now < end;
        });
      }
      if (!periodsNow.length) {
        currentScheduleList.innerHTML = '<div class="w-full rounded-xl border border-slate-600/40 bg-slate-900/40 px-3 py-3 text-center text-slate-400 text-xs md:text-sm">لا توجد حصص حالية الآن</div>';
      } else {
        periodsNow.forEach(function (p) {
          var isStandby = !!p.is_standby;
          var card = document.createElement("div");
          card.className = "rounded-xl p-3 flex flex-col md:flex-row items-center justify-between bg-white/5 border border-white/10 gap-2";
          var inner = document.createElement("div");
          inner.className = "flex flex-col md:flex-row gap-2 items-center w-full text-xs md:text-sm";
          var cName = document.createElement("span");
          cName.className = "font-bold text-indigo-300";
          cName.textContent = p.class_name || "—";
          var subj = document.createElement("span");
          subj.className = "text-slate-300";
          subj.textContent = p.subject_name || "—";
          var teacher = document.createElement("span");
          teacher.className = "text-slate-300";
          teacher.textContent = p.teacher_name || "—";
          var idxSpan = document.createElement("span");
          idxSpan.className = "bg-slate-900/60 px-2 py-1 rounded text-[11px] num-font text-slate-100";
          idxSpan.textContent = "حصة " + (p.index || "");
          var kindSpan = document.createElement("span");
          if (isStandby) {
            kindSpan.className = "text-emerald-400 font-bold";
            kindSpan.textContent = "انتظار";
          } else {
            kindSpan.className = "text-slate-400";
            kindSpan.textContent = "عادية";
          }
          inner.appendChild(cName);
          inner.appendChild(subj);
          inner.appendChild(teacher);
          inner.appendChild(idxSpan);
          inner.appendChild(kindSpan);
          card.appendChild(inner);
          currentScheduleList.appendChild(card);
        });
      }
    }
    var title = "لوحة العرض المدرسية";
    var range = "--:-- → --:--";
    var badge = "حالة اليوم";
    countdownSeconds = null;
    progressRange = { start: null, end: null };
    hasActiveCountdown = false;
    var nextLabelEl = $("nextLabel");
    if (s.type === "before") {
      title = "صباح الخير";
      badge = "قبل الطابور";
      if (s.next && s.next.type === "period") range = "تبدأ " + toTimeStr(s.next.starts_at);
      if (typeof s.countdown_seconds === "number") {
        countdownSeconds = s.countdown_seconds;
        hasActiveCountdown = true;
      }
    } else if (s.type === "off") {
      title = "يوم إجازة";
      badge = "عطلة";
      range = "--:--";
      if (nextLabelEl) nextLabelEl.textContent = "نتمنى لكم يوماً سعيداً";
    } else if (s.type === "after") {
      title = "انتهى الدوام";
      badge = "في أمان الله";
    } else if (s.type === "break") {
      title = (s.current && s.current.label) || "استراحة";
      badge = "استراحة";
      range = toTimeStr(s.current && s.current.starts_at) + " → " + toTimeStr(s.current && s.current.ends_at);
      if (typeof s.countdown_seconds === "number") {
        countdownSeconds = s.countdown_seconds;
        hasActiveCountdown = true;
      }
      if (s.current && s.current.starts_at && s.current.ends_at) {
        var d = new Date();
        var sh = parseInt(String(s.current.starts_at).split(":")[0], 10) || 0;
        var sm = parseInt(String(s.current.starts_at).split(":")[1], 10) || 0;
        var eh = parseInt(String(s.current.ends_at).split(":")[0], 10) || 0;
        var em = parseInt(String(s.current.ends_at).split(":")[1], 10) || 0;
        progressRange.start = new Date(d.getFullYear(), d.getMonth(), d.getDate(), sh, sm, 0).getTime();
        progressRange.end = new Date(d.getFullYear(), d.getMonth(), d.getDate(), eh, em, 0).getTime();
      }
    } else if (s.type === "period") {
      title = "الحصة " + (s.current && s.current.index ? s.current.index : "");
      badge = "درس";
      range = toTimeStr(s.current && s.current.starts_at) + " → " + toTimeStr(s.current && s.current.ends_at);
      if (typeof s.countdown_seconds === "number") {
        countdownSeconds = s.countdown_seconds;
        hasActiveCountdown = true;
      }
      if (s.current && s.current.starts_at && s.current.ends_at) {
        var d2 = new Date();
        var sh2 = parseInt(String(s.current.starts_at).split(":")[0], 10) || 0;
        var sm2 = parseInt(String(s.current.starts_at).split(":")[1], 10) || 0;
        var eh2 = parseInt(String(s.current.ends_at).split(":")[0], 10) || 0;
        var em2 = parseInt(String(s.current.ends_at).split(":")[1], 10) || 0;
        progressRange.start = new Date(d2.getFullYear(), d2.getMonth(), d2.getDate(), sh2, sm2, 0).getTime();
        progressRange.end = new Date(d2.getFullYear(), d2.getMonth(), d2.getDate(), eh2, em2, 0).getTime();
      }
    }
    var heroTitle = $("heroTitle");
    var heroRange = $("heroRange");
    var badgeKind = $("badgeKind");
    if (heroTitle) heroTitle.textContent = title;
    if (heroRange) heroRange.textContent = range;
    if (badgeKind) badgeKind.textContent = badge;
    if (nextLabelEl) {
      nextLabelEl.innerHTML = "";
      if (s.next) {
        var span1 = document.createElement("span");
        span1.className = "opacity-80";
        span1.textContent = "التالي: ";
        var span2 = document.createElement("span");
        span2.className = "font-bold text-white mx-1";
        span2.textContent = s.next.type === "period" ? "الحصة " + (s.next.index || "") : (s.next.label || "—");
        var span3 = document.createElement("span");
        span3.className = "bg-slate-900/60 px-1.5 rounded text-xs num-font";
        span3.textContent = toTimeStr(s.next.starts_at);
        nextLabelEl.appendChild(span1);
        nextLabelEl.appendChild(span2);
        nextLabelEl.appendChild(span3);
      } else {
        nextLabelEl.textContent = "التالي: —";
      }
    }
    var mini = $("miniSchedule");
    var timeline = [];
    if (Array.isArray(day.periods)) {
      day.periods.forEach(function (p) {
        if (!p) return;
        timeline.push({ kind: "period", start: p.starts_at, end: p.ends_at, label: p.index || "" });
      });
    }
    if (Array.isArray(day.breaks)) {
      day.breaks.forEach(function (b) {
        if (!b) return;
        timeline.push({ kind: "break", start: b.starts_at, end: b.ends_at, label: b.label || "استراحة" });
      });
    }
    timeline.sort(function (a, b) {
      var da = hmToDate(a.start) || new Date();
      var db = hmToDate(b.start) || new Date();
      if (da.getTime() !== db.getTime()) return da.getTime() - db.getTime();
      if (a.kind === b.kind) return 0;
      return a.kind === "period" ? -1 : 1;
    });
    var shown = timeline.filter(function (x) {
      return !isEnded(x.end);
    });
    var currentScheduleJSON = JSON.stringify(shown);
    if (mini) {
      if (currentScheduleJSON !== lastScheduleJSON) {
        lastScheduleJSON = currentScheduleJSON;
        mini.innerHTML = "";
        if (!shown.length) {
          mini.innerHTML = '<div class="text-xs md:text-sm text-slate-400">انتهى جدول اليوم</div>';
        } else {
          shown.forEach(function (x, i) {
            var chip = document.createElement("div");
            chip.id = "sched-item-" + i;
            chip.className = "flex-shrink-0 rounded-xl p-3 flex flex-col items-center justify-center min-w-[4.5rem] h-20 md:h-22 transition-all duration-300 bg-white/5 text-slate-300 border border-white/10";
            var timeSpan = document.createElement("span");
            timeSpan.className = "text-[10px] opacity-70 mb-1";
            timeSpan.textContent = toTimeStr(x.start);
            var labelSpan = document.createElement("span");
            labelSpan.className = "font-bold text-lg leading-none";
            labelSpan.textContent = x.kind === "period" ? "ح " + x.label : x.label;
            chip.appendChild(timeSpan);
            chip.appendChild(labelSpan);
            mini.appendChild(chip);
          });
        }
      }
      if (shown.length) {
        shown.forEach(function (x, i) {
          var el = document.getElementById("sched-item-" + i);
          if (!el) return;
          var isCurrent = isNowBetween(x.start, x.end);
          var clsBase = "flex-shrink-0 rounded-xl p-3 flex flex-col items-center justify-center min-w-[4.5rem] h-20 md:h-22 transition-all duration-300 ";
          if (isCurrent) {
            el.className = clsBase + "bg-indigo-500 text-white ring-4 ring-sky-400/60 shadow-[0_0_20px_rgba(99,102,241,0.8)] scale-110 z-10";
          } else {
            el.className = clsBase + "bg-white/5 text-slate-300 border border-white/10 opacity-70";
          }
        });
      }
    }
  }

  async function refreshAll() {
    await checkSettings();
    var res = await Promise.all([
      safeFetch(api.today),
      safeFetch(api.ann),
      safeFetch(api.standby),
      safeFetch(api.exc),
      safeFetch(api.periodClasses)
    ]);
    var d = res[0];
    var a = res[1];
    var s = res[2];
    var x = res[3];
    var p = res[4];
    if (d) renderState(d);
    if (a && a.items) mountAnnouncements(a.items);
    else if (a && Array.isArray(a)) mountAnnouncements(a);
    if (s && s.items) renderStandby(s.items);
    else if (s && Array.isArray(s)) renderStandby(s);
    if (x && x.items) renderExcellence(x.items);
    else if (x && Array.isArray(x)) renderExcellence(x);
    if (p) renderPeriodClasses(p);
  }

  function startTicker() {
    setInterval(function () {
      tickClock();
      if (hasActiveCountdown && typeof countdownSeconds === "number") {
        if (countdownSeconds > 0) countdownSeconds -= 1;
      }
      if (countdownEl) {
        if (hasActiveCountdown && typeof countdownSeconds === "number") {
          var mm = Math.floor(countdownSeconds / 60);
          var ss = countdownSeconds % 60;
          countdownEl.textContent = fmt2(mm) + ":" + fmt2(ss);
        } else {
          countdownEl.textContent = "--:--";
        }
      }
      if (countdownWrapper) {
        if (hasActiveCountdown) {
          countdownWrapper.style.visibility = "visible";
          countdownWrapper.style.opacity = "1";
        } else {
          countdownWrapper.style.visibility = "hidden";
          countdownWrapper.style.opacity = "0";
        }
      }
      if (progressBar) {
        if (progressRange.start && progressRange.end && progressRange.end > progressRange.start) {
          var now = Date.now();
          var pct = ((now - progressRange.start) / (progressRange.end - progressRange.start)) * 100;
          if (pct < 0) pct = 0;
          if (pct > 100) pct = 100;
          progressBar.style.width = pct.toFixed(1) + "%";
          setRing(pct);
        } else {
          progressBar.style.width = "0%";
          setRing(0);
        }
      }
    }, 1000);
  }

  function bindFullscreen() {
    var fsBtn = $("fsBtn");
    if (!fsBtn) return;
    fsBtn.addEventListener("click", function () {
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(function () {});
      } else {
        document.exitFullscreen().catch(function () {});
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    tickClock();
    startTicker();
    refreshAll();
    mainTimer = setInterval(refreshAll, Math.max(10, REFRESH_EVERY) * 1000);
    setInterval(toggleDateDisplay, 5000);
    bindFullscreen();
  });
})();
