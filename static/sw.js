const CACHE_NAME = 'edu-v7';
const STATIC_ASSETS = [
    '/static/css/style.css',
    '/static/css/professional.css',
    '/static/css/print.css',
    '/static/js/app.js',
    '/static/js/dashboard.js',
    '/static/manifest.json',
    '/static/img/icon-192.png',
    '/static/img/icon-512.png',
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((names) =>
            Promise.all(
                names
                    .filter((name) => name !== CACHE_NAME)
                    .map((name) => caches.delete(name))
            )
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);
    if (event.request.method !== 'GET') return;

    // Cache only public same-origin static assets. Authenticated HTML, API
    // responses, reports, exports and uploaded documents are never cached.
    if (url.origin === self.location.origin && url.pathname.startsWith('/static/')) {
        event.respondWith(staleWhileRevalidate(event.request));
        return;
    }

    event.respondWith(networkOnly(event.request));
});

async function staleWhileRevalidate(request) {
    const cache = await caches.open(CACHE_NAME);
    const cachedResponse = await cache.match(request);
    const fetchPromise = fetch(request)
        .then((networkResponse) => {
            if (networkResponse && networkResponse.ok) {
                cache.put(request, networkResponse.clone());
            }
            return networkResponse;
        })
        .catch(() => null);

    return cachedResponse || fetchPromise || offlineResponse();
}

async function networkOnly(request) {
    try {
        return await fetch(request);
    } catch {
        return offlineResponse();
    }
}

function offlineResponse() {
    return new Response(
        '<h1>Hors ligne</h1><p>Une connexion est necessaire pour afficher les donnees scolaires.</p>',
        { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
    );
}
