const API = "https://api.cloudflare.com/client/v4";

function safeSegment(value) {
  return String(value).replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 80);
}

function assertConfig(env) {
  for (const key of ["CLOUDFLARE_ACCOUNT_ID", "D1_DATABASE_ID", "D1_REST_API_TOKEN"]) {
    if (typeof env[key] !== "string" || !env[key].trim()) throw new Error(`Missing required backup configuration: ${key}`);
  }
  if (!env.BACKUPS || typeof env.BACKUPS.put !== "function" || typeof env.BACKUPS.get !== "function") {
    throw new Error("R2 binding BACKUPS is unavailable");
  }
}

async function cloudflareRequest(url, token, init = {}, fetchImpl = fetch) {
  const response = await fetchImpl(url, {
    ...init,
    headers: { authorization: `Bearer ${token}`, ...(init.headers || {}) }
  });
  if (!response.ok) throw new Error(`Cloudflare API HTTP ${response.status}`);
  const payload = await response.json();
  if (!payload || payload.success !== true || !payload.result) {
    const codes = Array.isArray(payload?.errors) ? payload.errors.map((e) => e.code).join(",") : "unknown";
    throw new Error(`Cloudflare API rejected backup request (codes: ${codes})`);
  }
  return payload.result;
}

async function sha256(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

export async function runD1Backup(env, options = {}) {
  assertConfig(env);
  const fetchImpl = options.fetchImpl || fetch;
  const sleep = options.sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  const now = options.now || (() => new Date());
  const maxPolls = options.maxPolls ?? 40;
  const pollIntervalMs = options.pollIntervalMs ?? 3000;
  const maxBytes = options.maxBytes ?? 256 * 1024 * 1024;
  const account = safeSegment(env.CLOUDFLARE_ACCOUNT_ID);
  const database = safeSegment(env.D1_DATABASE_ID);
  const endpoint = `${API}/accounts/${account}/d1/database/${database}/export`;
  const headers = { "content-type": "application/json" };

  let result = await cloudflareRequest(endpoint, env.D1_REST_API_TOKEN, {
    method: "POST",
    headers,
    body: JSON.stringify({ output_format: "polling", dump_options: { compatibility: "d1" } })
  }, fetchImpl);

  const bookmark = result.at_bookmark;
  if (!bookmark) throw new Error("D1 export did not return an at_bookmark");
  let signedUrl = result.result?.signed_url;
  for (let attempt = 0; !signedUrl && attempt < maxPolls; attempt += 1) {
    if (result.status === "error" || result.error) throw new Error("D1 export failed");
    await sleep(pollIntervalMs);
    result = await cloudflareRequest(endpoint, env.D1_REST_API_TOKEN, {
      method: "POST",
      headers,
      body: JSON.stringify({ output_format: "polling", current_bookmark: bookmark })
    }, fetchImpl);
    if (result.at_bookmark && result.at_bookmark !== bookmark) throw new Error("D1 export bookmark changed while polling");
    signedUrl = result.result?.signed_url;
  }
  if (result.status === "error" || result.error) throw new Error("D1 export failed");
  if (!signedUrl) throw new Error("D1 export polling timed out");
  const parsedSignedUrl = new URL(signedUrl);
  if (parsedSignedUrl.protocol !== "https:") throw new Error("D1 export returned a non-HTTPS download URL");

  const download = await fetchImpl(signedUrl);
  if (!download.ok || !download.body) throw new Error("D1 SQL dump download failed");
  const bytes = await download.arrayBuffer();
  if (bytes.byteLength === 0 || bytes.byteLength > maxBytes) throw new Error("D1 SQL dump size is empty or exceeds configured safety limit");

  const timestamp = now().toISOString().replace(/[:.]/g, "-");
  const key = `d1/${database}/${timestamp}-${bookmark.replace(/[^a-zA-Z0-9_-]/g, "_")}.sql`;
  const checksum = await sha256(bytes);
  const manifest = {
    version: 1,
    format: "cloudflare-d1-sql",
    database_id: env.D1_DATABASE_ID,
    at_bookmark: bookmark,
    exported_at: now().toISOString(),
    object_key: key,
    size_bytes: bytes.byteLength,
    sha256: checksum,
    verification: "sha256-computed-before-upload"
  };
  const manifestKey = `${key}.manifest.json`;

  // Do not overwrite an existing object. A retry with the same deterministic
  // key must verify the previous object rather than silently replace it.
  const existing = await env.BACKUPS.head?.(key);
  if (existing) {
    if (existing.size !== manifest.size_bytes || existing.customMetadata?.sha256 !== checksum) {
      throw new Error("An object already exists at the backup key with different metadata");
    }
  } else {
    await env.BACKUPS.put(key, bytes, {
      httpMetadata: { contentType: "application/sql; charset=utf-8" },
      customMetadata: { database_id: env.D1_DATABASE_ID, at_bookmark: bookmark, sha256: checksum }
    });
  }

  const stored = await env.BACKUPS.get(key);
  if (!stored) throw new Error("R2 backup object is missing after upload");
  const storedBytes = await stored.arrayBuffer();
  if (storedBytes.byteLength !== manifest.size_bytes || await sha256(storedBytes) !== checksum) {
    throw new Error("R2 backup verification failed");
  }
  await env.BACKUPS.put(manifestKey, JSON.stringify({ ...manifest, verification: "r2-readback-sha256-verified" }, null, 2), {
    httpMetadata: { contentType: "application/json" }
  });
  return { ...manifest, manifest_key: manifestKey, verification: "r2-readback-sha256-verified" };
}

export async function getTimeTravelBookmark(env, options = {}) {
  assertConfig(env);
  const fetchImpl = options.fetchImpl || fetch;
  const url = `${API}/accounts/${safeSegment(env.CLOUDFLARE_ACCOUNT_ID)}/d1/database/${safeSegment(env.D1_DATABASE_ID)}/time_travel/bookmark`;
  const response = await fetchImpl(url, { headers: { authorization: `Bearer ${env.D1_REST_API_TOKEN}` } });
  if (!response.ok) throw new Error(`D1 bookmark API HTTP ${response.status}`);
  const payload = await response.json();
  if (payload.success !== true || typeof payload.result?.bookmark !== "string") throw new Error("D1 bookmark response was incomplete");
  return { bookmark: payload.result.bookmark, captured_at: new Date().toISOString() };
}
