const CACHE = 'gridtracker-v6';
const ASSETS = ['./bist_tracker.html', './manifest.json', './icon-192.png', './icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  if(!e.request.url.startsWith(self.location.origin)) return;
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request))
  );
});

// ── Push bildirimleri ──────────────────────────────────
self.addEventListener('push', e => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch(err) {}
  const title = data.title || 'GridTracker';
  const options = {
    body:    data.body  || '',
    icon:    './icon-192.png',
    badge:   './icon-192.png',
    tag:     data.tag   || 'gridtracker',
    renotify: true,
    silent:  false,
    vibrate: [300, 100, 300, 100, 300],
    data:    data
  };
  e.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(
    clients.matchAll({type:'window', includeUncontrolled:true}).then(list => {
      for(const c of list){
        if(c.url.includes('bist_tracker') && 'focus' in c) return c.focus();
      }
      return clients.openWindow('./bist_tracker.html');
    })
  );
});
