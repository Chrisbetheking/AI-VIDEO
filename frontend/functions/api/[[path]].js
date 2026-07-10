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

  const method = request.method.toUpperCase();

  if (method === "OPTIONS") {
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

  let requestBody;

  if (method !== "GET" && method !== "HEAD") {
    const buffer = await request.arrayBuffer();

    if (buffer.byteLength > 0) {
      requestBody = buffer;
    }
  }

  try {
    const upstream = await fetch(targetUrl, {
      method,
      headers: proxyHeaders,
      body: requestBody,
      redirect: "follow",
    });

    const responseBody = await upstream.arrayBuffer();
    const responseHeaders = new Headers(upstream.headers);

    for (const [key, value] of Object.entries(corsHeaders())) {
      responseHeaders.set(key, value);
    }

    responseHeaders.set(
      "X-AI-Video-Backend",
      "production-sslip"
    );

    responseHeaders.set(
      "Cache-Control",
      "no-store"
    );

    return new Response(responseBody, {
      status: upstream.status,
      statusText: upstream.statusText,
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
