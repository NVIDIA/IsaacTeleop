import React from 'react';
import ReactDOM from 'react-dom/client';

import App from './App';

// Start the React app immediately in the 3d-ui container
function startApp() {
  const reactContainer = document.getElementById('3d-ui');

  if (reactContainer) {
    const root = ReactDOM.createRoot(reactContainer);
    root.render(
      <React.StrictMode>
        <App />
      </React.StrictMode>
    );
  } else {
    console.error('3d-ui container not found');
  }
}

// Initialize the app when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', startApp);
} else {
  startApp();
}
