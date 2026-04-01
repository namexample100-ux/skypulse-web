// SkyPulse Service Worker — Push Notifications
self.addEventListener('push', event => {
  let data = { title: 'SkyPulse', body: 'Новое уведомление', icon: '/static/icon.png' };
  
  if (event.data) {
    try { data = JSON.parse(event.data.text()); } catch(e) {}
  }

  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: data.icon || '/static/icon.png',
      badge: '/static/icon.png',
      vibrate: [200, 100, 200],
    })
  );
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(clients.openWindow('/'));
});
