// The catalog shell and API must go to the network for device authorization.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil(caches.delete("vr-catalog-shell-v1").then(() => self.clients.claim()));
});
