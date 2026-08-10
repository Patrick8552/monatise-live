const ORIGIN_URL = "https://monatise-live.onrender.com";
const PROXIED_PREFIXES = ["/api/", "/health/"];

function isProxiedPath(pathname) {
  return PROXIED_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

async function proxyToOrigin(request) {
  const incomingUrl = new URL(request.url);
  const originUrl = new URL(ORIGIN_URL);
  originUrl.pathname = incomingUrl.pathname;
  originUrl.search = incomingUrl.search;

  const headers = new Headers(request.headers);
  headers.set("X-Forwarded-Host", incomingUrl.host);
  headers.set("X-Forwarded-Proto", incomingUrl.protocol.slice(0, -1));

  try {
    const upstreamResponse = await fetch(new Request(originUrl, {
      method: request.method,
      headers,
      body: request.body,
      redirect: "manual",
    }));
    const responseHeaders = new Headers(upstreamResponse.headers);
    responseHeaders.set("X-Monatise-Edge", "cloudflare-pages");
    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error(JSON.stringify({
      event: "origin_fetch_failed",
      path: incomingUrl.pathname,
      error: error instanceof Error ? error.message : "unknown error",
    }));
    return Response.json(
      { status: "unavailable", reason: "Monatise origin is temporarily unavailable" },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (isProxiedPath(url.pathname)) {
      return proxyToOrigin(request);
    }
    return env.ASSETS.fetch(request);
  },
};
