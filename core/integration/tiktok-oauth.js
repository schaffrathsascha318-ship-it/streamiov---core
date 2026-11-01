"use strict";
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const AUTH = "https://www.tiktok.com/v2/auth/authorize/";
const TOKEN = "https://open.tiktokapis.com/v2/oauth/token/";
const REVOKE = "https://open.tiktokapis.com/v2/oauth/revoke/";
const BASIC_SCOPE = "user.info.basic";

function need(v, n) { if (typeof v !== "string" || !v.trim()) throw new Error(n + "_required"); return v.trim(); }
function keyBytes(v) { const b = Buffer.from(need(v, "token_encryption_key"), "base64"); if (b.length !== 32) throw new Error("token_encryption_key_must_be_32_bytes"); return b; }
function validateRedirectUri(uri, environment) {
  const u = new URL(need(uri, "redirect_uri"));
  if (u.username || u.password || u.hash) throw new Error("invalid_redirect_uri");
  if (environment === "production" && u.protocol !== "https:") throw new Error("production_redirect_must_use_https");
  if (environment === "sandbox" && !(u.protocol === "http:" && ["127.0.0.1", "localhost"].includes(u.hostname) && u.port)) throw new Error("sandbox_redirect_must_use_loopback_with_port");
  if (!["sandbox", "production"].includes(environment)) throw new Error("invalid_oauth_environment");
  return u.toString();
}
class EncryptedTokenStore {
  constructor({filePath, encryptionKey, environment}) { this.filePath = path.resolve(need(filePath, "token_store_path")); this.key = keyBytes(encryptionKey); this.environment = need(environment, "environment"); }
  save(tokens) {
    const iv = crypto.randomBytes(12), cipher = crypto.createCipheriv("aes-256-gcm", this.key, iv);
    cipher.setAAD(Buffer.from("streamiov-tiktok:" + this.environment));
    const encrypted = Buffer.concat([cipher.update(JSON.stringify(tokens)), cipher.final()]);
    const rec = {version:1, environment:this.environment, iv:iv.toString("base64"), tag:cipher.getAuthTag().toString("base64"), ciphertext:encrypted.toString("base64")};
    fs.mkdirSync(path.dirname(this.filePath), {recursive:true, mode:0o700});
    const tmp = this.filePath + "." + crypto.randomBytes(6).toString("hex") + ".tmp";
    fs.writeFileSync(tmp, JSON.stringify(rec), {mode:0o600, flag:"wx"}); fs.renameSync(tmp, this.filePath);
    try { fs.chmodSync(this.filePath, 0o600); } catch (_) {}
  }
  load() {
    if (!fs.existsSync(this.filePath)) return null;
    const r = JSON.parse(fs.readFileSync(this.filePath, "utf8"));
    if (r.version !== 1 || r.environment !== this.environment) throw new Error("token_environment_mismatch");
    const d = crypto.createDecipheriv("aes-256-gcm", this.key, Buffer.from(r.iv, "base64"));
    d.setAAD(Buffer.from("streamiov-tiktok:" + this.environment)); d.setAuthTag(Buffer.from(r.tag, "base64"));
    return JSON.parse(Buffer.concat([d.update(Buffer.from(r.ciphertext, "base64")), d.final()]).toString("utf8"));
  }
  clear() { try { fs.unlinkSync(this.filePath); } catch(e) { if (e.code !== "ENOENT") throw e; } }
}
class TikTokOAuth {
  constructor(o={}) {
    this.environment = need(o.environment, "environment");
    const prefix = this.environment === "sandbox" ? "STREAMIOV_TIKTOK_SANDBOX" : "STREAMIOV_TIKTOK_PRODUCTION";
    const env = o.env || process.env;
    this.clientKey = need(o.clientKey || env[prefix+"_CLIENT_KEY"], "client_key");
    this.clientSecret = need(o.clientSecret || env[prefix+"_CLIENT_SECRET"], "client_secret");
    this.redirectUri = validateRedirectUri(o.redirectUri || env[prefix+"_REDIRECT_URI"], this.environment);
    this.clock = o.clock || Date.now; this.ttl = o.stateTtlMs || 600000; this.pending = new Map();
    this.fetch = o.fetch || globalThis.fetch;
    this.scopes = [BASIC_SCOPE];
    this.store = o.store || new EncryptedTokenStore({filePath:o.tokenFile || env[prefix+"_TOKEN_FILE"] || path.join(process.cwd(),"data","oauth","tiktok-"+this.environment+".json"), encryptionKey:o.encryptionKey || env[prefix+"_TOKEN_ENCRYPTION_KEY"], environment:this.environment});
  }
  createAuthorizationUrl() {
    const state=crypto.randomBytes(32).toString("base64url"), verifier=crypto.randomBytes(48).toString("base64url");
    const challenge=crypto.createHash("sha256").update(verifier).digest("base64url");
    this.pending.set(state,{verifier,created:this.clock()});
    const u=new URL(AUTH); u.search=new URLSearchParams({client_key:this.clientKey,response_type:"code",scope:this.scopes.join(","),redirect_uri:this.redirectUri,state,code_challenge:challenge,code_challenge_method:"S256"}).toString();
    return {url:u.toString(),state,expiresInSeconds:this.ttl/1000};
  }
  async tokenRequest(fields) {
    const r=await this.fetch(TOKEN,{method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded","Cache-Control":"no-store"},body:new URLSearchParams(fields).toString()});
    let data; try { data=await r.json(); } catch(_) { throw new Error("oauth_provider_invalid_response"); }
    if (!r.ok || data.error) throw new Error("oauth_token_request_failed");
    return data;
  }
  normalize(t) {
    if (!t || typeof t.access_token!=="string" || !t.access_token) throw new Error("token_response_invalid");
    const expires=Number(t.expires_in), refreshExpires=Number(t.refresh_expires_in);
    return {access_token:t.access_token,refresh_token:typeof t.refresh_token==="string"?t.refresh_token:null,token_type:t.token_type||"Bearer",scope:t.scope||BASIC_SCOPE,expires_at:this.clock()+(Number.isFinite(expires)?expires:0)*1000,refresh_expires_at:Number.isFinite(refreshExpires)&&refreshExpires>0?this.clock()+refreshExpires*1000:null,open_id:t.open_id||null};
  }
  async callback({code,state,error}={}) {
    if (error) throw new Error("provider_authorization_error");
    if (typeof state!=="string" || !state) throw new Error("oauth_state_missing");
    const p=this.pending.get(state); this.pending.delete(state);
    if (!p) throw new Error("oauth_state_mismatch");
    if (this.clock()-p.created>this.ttl) throw new Error("oauth_state_expired");
    if (typeof code!=="string" || !code || code.length>2048) throw new Error("authorization_code_invalid");
    const tokens=await this.tokenRequest({client_key:this.clientKey,client_secret:this.clientSecret,code,grant_type:"authorization_code",redirect_uri:this.redirectUri,code_verifier:p.verifier});
    this.store.save(this.normalize(tokens));
    return {ok:true,status:"connected",environment:this.environment};
  }
  async refresh() {
    const old=this.store.load(); if (!old || !old.refresh_token) throw new Error("refresh_token_unavailable");
    const next=await this.tokenRequest({client_key:this.clientKey,client_secret:this.clientSecret,grant_type:"refresh_token",refresh_token:old.refresh_token});
    this.store.save(this.normalize({...next,refresh_token:next.refresh_token||old.refresh_token}));
    return this.status();
  }
  async disconnect() {
    const t=this.store.load();
    if (t && t.access_token) {
      const r=await this.fetch(REVOKE,{method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded","Cache-Control":"no-store"},body:new URLSearchParams({client_key:this.clientKey,client_secret:this.clientSecret,token:t.access_token}).toString()});
      if (!r.ok) throw new Error("oauth_revoke_failed");
    }
    this.store.clear(); this.pending.clear(); return {ok:true,status:"disconnected",environment:this.environment};
  }
  status() {
    const t=this.store.load(); if (!t) return {status:"not_connected",environment:this.environment,scopes:this.scopes};
    return {status:t.expires_at<=this.clock()?"token_expired":"connected",environment:this.environment,scopes:String(t.scope||"").split(/[ ,]+/).filter(Boolean),expiresAt:new Date(t.expires_at).toISOString(),refreshAvailable:Boolean(t.refresh_token),openIdPresent:Boolean(t.open_id)};
  }
}
module.exports={TikTokOAuth,EncryptedTokenStore,validateRedirectUri};
