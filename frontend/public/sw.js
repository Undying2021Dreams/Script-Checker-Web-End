/**
 * A deliberately empty service worker.
 *
 * Chrome will not offer to install a site without one that handles
 * fetch, so this exists to satisfy that and nothing else. It caches
 * nothing on purpose.
 *
 * Caching here would be actively harmful. The app is almost entirely
 * authenticated requests whose responses differ per person and change
 * the moment a teacher releases a mark — and a cached index.html is the
 * classic way to leave people running last week's build with no way to
 * tell. A student seeing a stale mark, or an old bundle calling an
 * endpoint that has moved, is a worse failure than a slow load.
 *
 * Offline support would be a real feature: queue a photographed script
 * taken with no signal and upload it later. That is worth building
 * deliberately, not by leaving a cache switched on and hoping.
 */
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))
self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request))
})
