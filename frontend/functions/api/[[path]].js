const DEFAULT_BACKEND =
  "https://ai-video.47-76-143-158.sslip.io";

export async function onRequest(context) {
  const { request, params, env } = context;

  const backend = String(
    env.AI_VIDEO_BACKEND || DEFAULT_BACKEND
  ).replace(/\/+$/, "");

  const path = Array.isArray(params.path)
    ? params.path.join("/")
    : String(params.path || "");

  const sourceUrl = new URL(request.url);
  const targetUrl =
    `${backend}/api/${path}${sourceUrl.search}`;

  if (request.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: corsHeaders(),
    });
  }

  const proxyHeaders = new Headers();

  for (const name of [
    "accept",
    "content-type",
    "authorization",
    "x-ai-video-token",
  ]) {
    const value = request.headers.get(name);
    if (value) {
      proxyHeaders.set(name, value);
    }
  }

  try {
    const response = await fetch(targetUrl, {
      method: request.method,
      headers: proxyHeaders,
      body:
        request.method === "GET" ||
        request.method === "HEAD"
          ? undefined
          : request.body,
      redirect: "follow",
    });

    const responseHeaders = new Headers(response.headers);

    for (const [key, value] of Object.entries(corsHeaders())) {
      responseHeaders.set(key, value);
    }

    responseHeaders.set(
      "X-AI-Video-Backend",
      "production-sslip"
    );

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    return Response.json(
      {
        ok: false,
        error: "backend_proxy_failed",
        message: String(error?.message || error),
        target: targetUrl,
      },
      {
        status: 502,
        headers: corsHeaders(),
      }
    );
  }
}

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods":
      "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Max-Age": "86400",
  };
}
