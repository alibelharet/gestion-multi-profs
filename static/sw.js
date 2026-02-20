const CACHE_NAME = 'edu-v3';
const STATIC_ASSETS = [
    '/',
    '/static/css/style.css',
    '/static/js/app.js',
    '/static/manifest.json',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css',
    'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap',
];

// Install: pre-cache static assets
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

// Activate: clean old caches
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

// Fetch: strategy selection based on request type
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Skip non-GET requests (POST, PUT, etc.)
    if (event.request.method !== 'GET') return;

    // API calls: Network-first with fallback
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(networkFirst(event.request));
        return;
    }

    // Static assets: Stale-while-revalidate
    if (
        url.pathname.startsWith('/static/') ||
        url.hostname.includes('cdn.jsdelivr.net') ||
        url.hostname.includes('fonts.googleapis.com') ||
        url.hostname.includes('fonts.gstatic.com')
    ) {
        event.respondWith(staleWhileRevalidate(event.request));
        return;
    }

    // HTML pages: Network-first with cache fallback
    if (event.request.headers.get('Accept')?.includes('text/html')) {
        event.respondWith(networkFirst(event.request));
        return;
    }

    // Default: stale-while-revalidate
    event.respondWith(staleWhileRevalidate(event.request));
});

// ─── Strategies ────────────────────────────────────────────────

async function staleWhileRevalidate(request) {
    const cache = await caches.open(CACHE_NAME);
    const cachedResponse = await cache.match(request);

    // Start network fetch in background
    const fetchPromise = fetch(request)
        .then((networkResponse) => {
            if (networkResponse && networkResponse.ok) {
                cache.put(request, networkResponse.clone());
            }
            return networkResponse;
        })
        .catch(() => null);

    // Return cached immediately, or wait for network
    return cachedResponse || fetchPromise || offlineFallback();
}

async function networkFirst(request) {
    try {
        const networkResponse = await fetch(request);
        if (networkResponse.ok) {
            const cache = await caches.open(CACHE_NAME);
            cache.put(request, networkResponse.clone());
        }
        return networkResponse;
    } catch (e) {
        const cachedResponse = await caches.match(request);
        return cachedResponse || offlineFallback();
    }
}

function offlineFallback() {
    return caches.match('/') || new Response(
        '<h1>Hors ligne</h1><p>Veuillez verifier votre connexion.</p>',
        { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
    );
}
