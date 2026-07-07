const BACKEND_ORIGIN = 'https://ai-video.47-76-143-158.sslip.io';

export async function onRequest(context) {
  const url = new URL(context.request.url);
  const target = new URL(url.pathname + url.search, BACKEND_ORIGIN);
  const headers = new Headers(context.request.headers);
  headers.delete('host');
  return fetch(target.toString(), {
    method: context.request.method,
    headers,
    body: ['GET', 'HEAD'].includes(context.request.method) ? undefined : context.request.body,
    redirect: 'manual',
  });
}
