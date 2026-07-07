const BACKEND = "https://ai-video.47-76-143-158.sslip.io";

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

  const proxyHeaders = new Headers();

  const contentType = request.headers.get("content-type");
  if (contentType) proxyHeaders.set("content-type", contentType);

  const authorization = request.headers.get("authorization");
  if (authorization) proxyHeaders.set("authorization", authorization);

  const response = await fetch(targetUrl, {
    method: request.method,
    headers: proxyHeaders,
    body:
      request.method === "GET" || request.method === "HEAD"
        ? undefined
        : request.body,
  });

  const responseHeaders = new Headers(response.headers);

  for (const [key, value] of Object.entries(corsHeaders())) {
    responseHeaders.set(key, value);
  }

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: responseHeaders,
  });
}

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Max-Age": "86400",
  };
}
