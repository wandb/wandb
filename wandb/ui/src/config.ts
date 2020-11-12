// Config interface
interface Config {
  AUTH0_CLIENT_ID: string;
  AUTH0_DOMAIN: string;
  AUTH_STUB_JWT: string;
  BACKEND_HOST: string; // NOTE: Don't use this directly. Call backendHost() below.
  ALTERNATE_BACKEND_HOST: string;
  ALTERNATE_BACKEND_PORT: string;
  ANALYTICS_DISABLED: boolean;
  CI: boolean;
  ENABLE_DEBUG_FEATURES: boolean;
  ENABLE_SERVICE_WORKER: boolean;
  ENVIRONMENT_IS_PRIVATE: boolean;
  ENVIRONMENT_NAME: string;
  HOST: string;
  SENTRY_DSN?: string;
  SENTRY_ENVIRONMENT?: string;
  GITHUB_CLIENT_ID?: string;
  STRIPE_API_KEY?: string;
}

declare global {
  interface Window {
    CONFIG?: Config;
  }
}
function toBool(str: string | undefined): boolean {
  return str === 'true';
}

// Config vars can be overridden by env vars, or by a `window.CONFIG` object
// in the case of on-premises builds. window.CONFIG objects are inserted on
// Docker container launch so environment variables can be inserted without
// forcing the frontend build to happen on container boot.
const defaults = {
  AUTH_STUB_JWT: process.env.REACT_APP_AUTH_STUB_JWT ?? '',
  AUTH0_CLIENT_ID: process.env.REACT_APP_AUTH0_CLIENT_ID ?? '',
  AUTH0_DOMAIN: process.env.REACT_APP_AUTH0_DOMAIN ?? '',
  BACKEND_HOST: process.env.REACT_APP_BACKEND_HOST ?? '',
  ALTERNATE_BACKEND_HOST: process.env.REACT_APP_ALTERNATE_BACKEND_HOST ?? '',
  ALTERNATE_BACKEND_PORT: process.env.REACT_APP_ALTERNATE_BACKEND_PORT ?? '',
  ANALYTICS_DISABLED: toBool(process.env.REACT_APP_ANALYTICS_DISABLED),
  ENABLE_DEBUG_FEATURES: toBool(process.env.REACT_APP_ENABLE_DEBUG_FEATURES),
  ENABLE_SERVICE_WORKER: toBool(process.env.REACT_APP_ENABLE_SERVICE_WORKER),
  ENVIRONMENT_IS_PRIVATE: toBool(process.env.REACT_APP_ENVIRONMENT_IS_PRIVATE),
  CI: toBool(process.env.REACT_APP_CI),
  ENVIRONMENT_NAME: process.env.REACT_APP_ENVIRONMENT_NAME ?? 'development',
  HOST: process.env.REACT_APP_HOST ?? '',
  SENTRY_DSN: process.env.REACT_APP_SENTRY_DSN,
  SENTRY_ENVIRONMENT: process.env.REACT_APP_SENTRY_ENVIRONMENT,
  GITHUB_CLIENT_ID: process.env.REACT_APP_GITHUB_CLIENT_ID,
  STRIPE_API_KEY: process.env.REACT_APP_STRIPE_API_KEY,
};
const config: Config = Object.assign(defaults, window.CONFIG ?? {});

export default config;

export const isDev = () =>
  config.ENVIRONMENT_NAME === 'development' ||
  config.ENVIRONMENT_NAME === 'devprod';

export const isIntegration = () => config.ENVIRONMENT_NAME === 'integration';

export const backendHost = () => {
  // Check for alternate hostname in origin.
  const alternateHostBase = config.ALTERNATE_BACKEND_HOST.replace(
    'https://api.',
    ''
  );
  if (
    alternateHostBase !== '' &&
    window.location.origin.indexOf(alternateHostBase) !== -1
  ) {
    // Yeah I know this is insane. It's really just a single use case thing for one customer.
    // They have two domain names pointing to one instance, and the second one needs a custom port too.
    let host = config.ALTERNATE_BACKEND_HOST;
    if (config.ALTERNATE_BACKEND_PORT) {
      host = `${host}:${config.ALTERNATE_BACKEND_PORT}`;
    }

    return host;
  }

  return config.BACKEND_HOST;
};
