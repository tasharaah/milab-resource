/*
 * Simple service worker for offline support.
 * It caches core assets like CSS, JS and the manifest, enabling
 * offline access to previously visited pages. For a production
 * application you may want to expand the list of cached assets.
 */
const CACHE_NAME = 'mi-lab-cache-v1';
const urlsToCache = [
  '/',
  '/static/labapp/css/styles.css',
  '/static/labapp/js/scripts.js',
  '/static/manifest.json',
];

// Install event - pre-cache essential assets
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(urlsToCache);
    })
  );
});

// Activate event - cleanup old caches
self.addEventListener('activate', event => {
  const cacheWhitelist = [CACHE_NAME];
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheWhitelist.indexOf(cacheName) === -1) {
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
});

// Fetch event - serve from cache when offline
self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request).then(response => {
      return response || fetch(event.request);
    })
  );
});