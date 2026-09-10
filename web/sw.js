/* Service worker: receives pushes and opens the app when one is tapped.
   iOS only delivers web push to a PWA that has been added to the Home Screen. */

const APP_URL = "./";

self.addEventListener("install", event => {
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", event => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch (err) {
    payload = { title: "Game Day", body: event.data ? event.data.text() : "" };
  }

  const title = payload.title || "Game Day";
  const options = {
    body: payload.body || "",
    icon: "icon.png",
    badge: "icon.png",
    // A tag lets a later push replace an earlier one rather than stacking.
    tag: payload.tag || "gameday",
    renotify: true,
    data: { url: payload.url || APP_URL },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || APP_URL;

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true })
      .then(clientList => {
        for (const client of clientList) {
          if ("focus" in client) return client.focus();
        }
        if (self.clients.openWindow) return self.clients.openWindow(target);
      })
  );
});
