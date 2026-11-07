const SECURITY_HEADERS = {
  "Content-Security-Policy": "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()"
};

function withSecurityHeaders(response) {
  const headers = new Headers(response.headers);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    headers.set(name, value);
  }
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/healthz") {
      return withSecurityHeaders(new Response(
        JSON.stringify({ service: "streamiov-liberty-tv-core", status: "ok", mode: "static-site-host" }),
        { headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } }
      ));
    }

    if (!env.ASSETS || typeof env.ASSETS.fetch !== "function") {
      return withSecurityHeaders(new Response("Static assets binding is not configured.", {
        status: 503,
        headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" }
      }));
    }

    return withSecurityHeaders(await env.ASSETS.fetch(request));
  }
};
