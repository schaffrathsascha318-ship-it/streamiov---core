"use strict";
const test=require("node:test"), assert=require("node:assert/strict"), fs=require("node:fs"), os=require("node:os"), path=require("node:path");
const {TikTokOAuth,EncryptedTokenStore,validateRedirectUri}=require("../core/integration/tiktok-oauth");
const key=Buffer.alloc(32,9).toString("base64");
function fixture(extra={}) {
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),"st-oauth-"));
 const store=new EncryptedTokenStore({filePath:path.join(dir,"sandbox.json"),encryptionKey:key,environment:"sandbox"});
 const calls=[];
 const oauth=new TikTokOAuth({environment:"sandbox",clientKey:"sandbox-key",clientSecret:"sandbox-secret",redirectUri:"http://127.0.0.1:3455/callback",store,clock:extra.clock||Date.now,
 fetch:extra.fetch||async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({access_token:"access-secret",refresh_token:"refresh-secret",expires_in:3600,scope:"user.info.basic",open_id:"test"})};}});
 return {oauth,store,calls,dir};
}
test("sandbox and production redirect validation",()=>{
 assert.equal(validateRedirectUri("http://127.0.0.1:3455/callback","sandbox"),"http://127.0.0.1:3455/callback");
 assert.throws(()=>validateRedirectUri("http://example.com/callback","sandbox"));
 assert.throws(()=>validateRedirectUri("http://127.0.0.1/callback","sandbox"));
 assert.throws(()=>validateRedirectUri("http://127.0.0.1:3455/callback","production"));
 assert.equal(validateRedirectUri("https://streamiov.pages.dev/callback","production"),"https://streamiov.pages.dev/callback");
});
test("authorization uses basic scope and PKCE S256",()=>{
 const {oauth}=fixture(), a=oauth.createAuthorizationUrl(), u=new URL(a.url);
 assert.equal(u.searchParams.get("scope"),"user.info.basic"); assert.equal(u.searchParams.get("code_challenge_method"),"S256");
 assert.ok(u.searchParams.get("code_challenge")); assert.equal(u.searchParams.get("redirect_uri"),"http://127.0.0.1:3455/callback");
});
test("state mismatch and missing state are rejected",async()=>{
 const {oauth}=fixture(); oauth.createAuthorizationUrl();
 await assert.rejects(()=>oauth.callback({code:"c",state:"wrong"}),/oauth_state_mismatch/);
 await assert.rejects(()=>oauth.callback({code:"c"}),/oauth_state_missing/);
});
test("expired state and invalid code are rejected",async()=>{
 let now=1000; const {oauth}=fixture({clock:()=>now}); const a=oauth.createAuthorizationUrl(); now+=600001;
 await assert.rejects(()=>oauth.callback({code:"c",state:a.state}),/oauth_state_expired/);
 const b=oauth.createAuthorizationUrl(); await assert.rejects(()=>oauth.callback({code:"",state:b.state}),/authorization_code_invalid/);
});
test("code exchange sends verifier and stores only encrypted tokens",async()=>{
 const {oauth,store,calls}=fixture(),a=oauth.createAuthorizationUrl();
 const result=await oauth.callback({code:"sandbox-code",state:a.state});
 assert.equal(result.status,"connected"); assert.match(calls[0].options.body,/code_verifier=/);
 assert.equal(JSON.stringify(oauth.status()).includes("access-secret"),false);
 const raw=fs.readFileSync(store.filePath,"utf8"); assert.equal(raw.includes("access-secret"),false); assert.equal(raw.includes("refresh-secret"),false);
});
test("provider exchange failures do not persist tokens",async()=>{
 const {oauth,store}=fixture({fetch:async()=>({ok:false,json:async()=>({error:"invalid_grant"})})});
 const a=oauth.createAuthorizationUrl(); await assert.rejects(()=>oauth.callback({code:"bad",state:a.state}),/oauth_token_request_failed/);
 assert.equal(store.load(),null);
});
test("refresh, revoke and disconnect",async()=>{
 let n=0; const {oauth,store}=fixture({fetch:async(url)=>{n++; if(url.endsWith("/revoke/"))return {ok:true,json:async()=>({})}; return {ok:true,json:async()=>({access_token:n===1?"a1":"a2",refresh_token:n===1?"r1":"r2",expires_in:3600,scope:"user.info.basic"})};}});
 const a=oauth.createAuthorizationUrl(); await oauth.callback({code:"c",state:a.state});
 await oauth.refresh(); assert.equal(store.load().access_token,"a2");
 assert.equal((await oauth.disconnect()).status,"disconnected"); assert.equal(store.load(),null);
});
test("environment-bound encryption prevents sandbox/production token crossover",()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),"st-isolation-")),p=path.join(dir,"same.json");
 const s=new EncryptedTokenStore({filePath:p,encryptionKey:key,environment:"sandbox"}),prod=new EncryptedTokenStore({filePath:p,encryptionKey:key,environment:"production"});
 s.save({access_token:"sandbox"}); assert.throws(()=>prod.load(),/token_environment_mismatch/);
});
