# Security

Returns Portal holds read-only access to brokerage accounts and shows what they contain, so
security reports are very welcome.

## Reporting a vulnerability

Please report it privately through GitHub: the repository's **Security** tab, **Report a
vulnerability**. Do not open a public issue for it. Include what you found, how to reproduce it, and
what an attacker could do with it. You will get an answer as soon as possible; there is no bounty.

## What the app protects, and what it leaves to you

The design assumes a single user running the app on their own machine or behind access control
they trust. Within that:

- **Broker credentials** are read-only by design, encrypted at rest with `SECRETS_ENCRYPTION_KEY`
  (Fernet), and never logged, returned by the API or stored in raw payloads.
- **No login.** The app has no accounts or authentication of its own. Anyone who can reach it can see
  everything in it. Serve it beyond localhost only behind a VPN or an authenticating reverse proxy.
- **Other web pages** in the user's browser cannot use it: the frontend server answers only to its
  own host names (against DNS rebinding), and both the frontend server and the API refuse writes from
  other sites. Pages cannot be framed. A production build (`npm run build`, then `node server.mjs`
  with `NODE_ENV=production`) also sends a strict Content-Security-Policy; the development server
  that `dev.sh` starts sends only `frame-ancestors 'none'`, so use a production build for daily use.
- **Saxo OAuth** uses a single-use `state` bound to the browser that started the login.

Reports about weaknesses in these protections are in scope. Attacks that need access the design
already grants, such as reaching an instance that was exposed without access control, are not.
