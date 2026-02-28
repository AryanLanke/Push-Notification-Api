/*
 * Service Worker for Web Push Notifications
 * This script runs in the background of the browser.
 */

self.addEventListener('push', function (event) {
    console.log('[Service Worker] Push Received.');

    let data = { title: 'New Notification', body: 'You have a new message!' };

    if (event.data) {
        try {
            data = event.data.json();
        } catch (e) {
            data.body = event.data.text();
        }
    }

    const title = data.title;
    const options = {
        body: data.body,
        icon: '/static/icon.png', // Optional: add an icon later
        badge: '/static/badge.png', // Optional: add a small badge icon
        vibrate: [200, 100, 200],
        data: {
            dateOfArrival: Date.now(),
            primaryKey: 1
        },
        actions: [
            { action: 'explore', title: 'View Details' },
            { action: 'close', title: 'Close' },
        ]
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', function (event) {
    console.log('[Service Worker] Notification click Received.');
    event.notification.close();

    // Open the dashboard when notification is clicked
    event.waitUntil(
        clients.openWindow('/')
    );
});
