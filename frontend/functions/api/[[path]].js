const BACKEND = "http://8.210.177.205";

export async function onRequest(context) {
  const { request, params } = context;

  const path = Array.isArray(params.path) ? params.path.join("/") : "";
  const url = new URL(request.url);
  const targetUrl = `${BACKEND}/api/${path}${url.search}`;

  if (request.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: corsHeaders(),
    });
  }

  const headers = new Headers(request.headers);
  headers.delete("host");

  const proxyRequest = new Request(targetUrl, {
    method: request.method,
    headers,
    body:
      request.method === "GET" || request.method === "HEAD"
        ? undefined
        : request.body,
    redirect: "follow",
  });

  const response = await fetch(proxyRequest);
  const responseHeaders = new Headers(response.headers);

  for (const [key, value] of Object.entries(corsHeaders())) {
    responseHeaders.set(key, value);
  }

  responseHeaders.delete("content-security-policy");
  responseHeaders.delete("content-security-policy-report-only");

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: responseHeaders,
  });
}

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "https://ai-video-s5v.pages.dev",
    "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Max-Age": "86400",
  };
}
