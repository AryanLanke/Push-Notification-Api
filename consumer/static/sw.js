// Service Worker for Push Notifications
self.addEventListener('install', function (event) {
    self.skipWaiting();
});

self.addEventListener('activate', function (event) {
    event.waitUntil(self.clients.claim());
});

self.addEventListener('push', function (event) {
    let data = {
        title: 'New Notification',
        body: 'You have received a new push notification'
    };

    if (event.data) {
        try {
            data = event.data.json();
        } catch (e) {
            data.body = event.data.text();
        }
    }

    const options = {
        body: data.body || data.message || 'No content',
        icon: 'https://cdn-icons-png.flaticon.com/512/3602/3602145.png',
        badge: 'https://cdn-icons-png.flaticon.com/512/3602/3602145.png',
        vibrate: [100, 50, 100],
        data: data
    };

    event.waitUntil(
        self.registration.showNotification(data.title || 'Notification', options)
    );
});

self.addEventListener('notificationclick', function (event) {
    event.notification.close();
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (clientList) {
            if (clientList.length > 0) {
                return clientList[0].focus();
            }
            return clients.openWindow('/');
        })
    );
});
