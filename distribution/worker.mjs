/**
 * DiscDeck download worker.
 *
 * The worker serves the object named by the channel pointer. A build is
 * published only after that pointer is replaced, so a failed upload cannot
 * become the URL Decky installs.
 */

export function resolveRequest(pathname) {
  if (pathname === "/dev/DiscDeck.zip" || pathname === "/dev/latest") {
    return { channel: "development", kind: "zip", pointer: "dev/latest.json" };
  }
  if (pathname === "/dev/metadata.json" || pathname === "/dev/latest.json") {
    return { channel: "development", kind: "metadata", pointer: "dev/latest.json" };
  }
  if (pathname === "/stable/DiscDeck.zip" || pathname === "/stable/latest") {
    return { channel: "stable", kind: "zip", pointer: "stable/latest.json" };
  }
  if (pathname === "/stable/metadata.json" || pathname === "/stable/latest.json") {
    return { channel: "stable", kind: "metadata", pointer: "stable/latest.json" };
  }
  return null;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method not allowed", { status: 405 });
    }
    const resolved = resolveRequest(url.pathname);
    if (!resolved) {
      return new Response("DiscDeck distribution. Use /dev/DiscDeck.zip or /stable/DiscDeck.zip.", {
        status: 404,
        headers: { "Cache-Control": "no-store" },
      });
    }
    const pointerObject = await env.BUCKET.get(resolved.pointer);
    if (!pointerObject) {
      return new Response("No published build for this channel.", { status: 404, headers: { "Cache-Control": "no-store" } });
    }
    const pointer = JSON.parse(await pointerObject.text());
    if (resolved.kind === "metadata") {
      return new Response(JSON.stringify(pointer), {
        status: 200,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Cache-Control": "no-store",
          "X-DiscDeck-Channel": resolved.channel,
        },
      });
    }
    const objectKey = pointer.object_key;
    if (!objectKey || !objectKey.startsWith(`${resolved.channel}/`)) {
      return new Response("Published pointer is invalid.", { status: 500, headers: { "Cache-Control": "no-store" } });
    }
    const zip = await env.BUCKET.get(objectKey);
    if (!zip) {
      return new Response("Published ZIP is missing.", { status: 404, headers: { "Cache-Control": "no-store" } });
    }
    const headers = new Headers();
    headers.set("Content-Type", "application/zip");
    headers.set("Cache-Control", "no-store");
    headers.set("X-DiscDeck-Channel", resolved.channel);
    if (pointer.commit) {
      headers.set("X-DiscDeck-Commit", String(pointer.commit));
    }
    headers.set("X-DiscDeck-Hardware-Validated", "false");
    if (request.method === "HEAD") {
      return new Response(null, { status: 200, headers });
    }
    return new Response(zip.body, { status: 200, headers });
  },
};
