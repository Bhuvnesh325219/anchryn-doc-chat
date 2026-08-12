/**
 * Production build, swapped in by the fileReplacements rule in angular.json.
 * Set apiBaseUrl to the deployed backend URL, and add this origin to
 * CORS_ALLOWED_ORIGINS on the backend so the browser is allowed to call it.
 */
export const environment = {
  production: true,
  apiBaseUrl: 'https://anchryn-doc-chat.onrender.com',
};
