import React from 'react';
import ReactDOM from 'react-dom/client';
import '@mantine/core/styles.css';
import App from './App';
import { registerSW } from 'virtual:pwa-register';

// Automatically detect new Docker/server versions and seamlessly reload
const updateSW = registerSW({
  immediate: true,
  onNeedRefresh() {
    // New version deployed: skip waiting and reload the page automatically
    updateSW(true);
  },
  onRegisteredSW(_swUrl, registration) {
    if (registration) {
      // Check for updates whenever the phone/tablet wakes up or regains focus
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
          registration.update();
        }
      });
      // Also check every 30 minutes in the background
      setInterval(() => {
        registration.update();
      }, 30 * 60 * 1000);
    }
  },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
