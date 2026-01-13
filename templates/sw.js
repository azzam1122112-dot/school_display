/*
  Minimal Service Worker
  الهدف: منع 404 عند طلب /sw.js من المتصفح.
  لا يقوم بكاش/تخزين أي شيء بشكل افتراضي.
*/

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// Pass-through fetch (no caching)
self.addEventListener('fetch', (event) => {
  // فقط نمرّر الطلب كما هو
});
