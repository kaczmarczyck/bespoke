// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

/**
 * Service Worker for Bespoke PWA (Offline Shell Caching)
 */

const CACHE_NAME = 'bespoke-cache-v2';
const ASSETS_TO_CACHE = [
    '/',
    '/index.html',
    '/style.css',
    '/app.js',
    '/deck.js',
    '/urgency.js',
    '/icon.svg',
    '/manifest.json',
    '/index.mjs',
    '/sqlite3.wasm',
    '/sqlite3-opfs-async-proxy.js',
    '/sqlite3-worker1.mjs'
];

// 1. Install Event: Cache all shell assets
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => {
            console.log('[Service Worker] Caching app shell assets');
            return cache.addAll(ASSETS_TO_CACHE);
        }).then(() => {
            return self.skipWaiting();
        })
    );
});

// 2. Activate Event: Clean up old cache storage versions
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys => {
            return Promise.all(
                keys.map(key => {
                    if (key !== CACHE_NAME) {
                        console.log('[Service Worker] Removing old cache version:', key);
                        return caches.delete(key);
                    }
                })
            );
        }).then(() => {
            return self.clients.claim();
        })
    );
});

// 3. Fetch Event: Intercept network requests and apply Cache-First strategy for cached resources
self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);

    // Skip API endpoints and database downloads (never cache DB files in the Service Worker Cache Storage)
    if (url.pathname.startsWith('/api/') || url.pathname.endsWith('.db') || url.pathname.endsWith('.sqlite3')) {
        return;
    }

    event.respondWith(
        caches.match(event.request).then(cachedResponse => {
            if (cachedResponse) {
                return cachedResponse;
            }
            
            // Fallback to network fetch
            return fetch(event.request).catch(() => {
                // If offline and request is HTML/navigation, fallback to root page
                if (event.request.mode === 'navigate') {
                    return caches.match('/');
                }
            });
        })
    );
});
