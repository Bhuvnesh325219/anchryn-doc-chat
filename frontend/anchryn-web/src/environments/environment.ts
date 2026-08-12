/**
 * Development. An empty apiBaseUrl keeps requests relative (/api/...), which
 * proxy.conf.json forwards to the FastAPI backend on port 8000.
 */
export const environment = {
  production: false,
  apiBaseUrl: '',
};
