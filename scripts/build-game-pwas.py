#!/usr/bin/env python3
"""Build offline, installable browser editions and portable bundles for StreamioV games."""
from __future__ import annotations
import hashlib, json, shutil, tarfile, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PUBLIC=ROOT/"dist/streamiov-homepage-worker/public"
GAMES=ROOT/"games/releases"
BRANDING=ROOT/"games/branding"
CATALOG=[
("streamiov-neon-relay","Neon Relay",GAMES/"streamiov-neon-relay","index.html"),
("streamiov-echo-grid","Echo Grid",GAMES/"streamiov-echo-grid","index.html"),
("streamiov-pulse-defender","Pulse Defender",GAMES/"streamiov-pulse-defender","index.html"),
("streamiov-signal-weave","Signal Weave",GAMES/"streamiov-signal-weave","index.html"),
("streamiov-star-defender","Star Defender",GAMES/"streamiov-star-defender"/"web","index.html")]
def checksum(path):
 d=hashlib.sha256(path.read_bytes()).hexdigest()
 path.with_suffix(path.suffix+".sha256").write_text(f"{d}  {path.name}\n",encoding="ascii")
 return d
def main():
 out=PUBLIC/"games"; downloads=PUBLIC/"downloads/games"
 out.mkdir(parents=True,exist_ok=True);downloads.mkdir(parents=True,exist_ok=True)
 rows=[]
 for gid,title,source,entry in CATALOG:
  if not (source/entry).is_file(): raise SystemExit(f"Missing game entry: {source/entry}")
  dest=out/gid
  if dest.exists(): shutil.rmtree(dest)
  shutil.copytree(source,dest)
  assets=dest/"assets";assets.mkdir(exist_ok=True)
  for asset in ("streamiov-game-intro.js","streamiov-symbol.svg"):
   p=BRANDING/asset
   if p.is_file() and not (assets/asset).exists(): shutil.copy2(p,assets/asset)
  manifest={"id":gid,"name":title,"short_name":title,"description":f"{title} – kostenloses StreamioV-Spiel, offline spielbar.","lang":"de","start_url":f"/games/{gid}/","scope":f"/games/{gid}/","display":"standalone","orientation":"any","background_color":"#080b12","theme_color":"#080b12","icons":[{"src":"assets/streamiov-symbol.svg","sizes":"any","type":"image/svg+xml","purpose":"any maskable"}]}
  (dest/"manifest.webmanifest").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
  cache=["./","./index.html","./manifest.webmanifest","./assets/streamiov-symbol.svg"]
  if (dest/"assets/streamiov-game-intro.js").is_file(): cache.append("./assets/streamiov-game-intro.js")
  if (dest/"engine.js").is_file(): cache.append("./engine.js")
  worker=f"""const CACHE={json.dumps(gid+"-v1")};const FILES={json.dumps(cache)};
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(FILES))));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k))))));
self.addEventListener('fetch',e=>{{if(e.request.method!=='GET')return;e.respondWith(caches.match(e.request).then(hit=>hit||fetch(e.request).then(res=>{{if(new URL(e.request.url).origin===self.location.origin)caches.open(CACHE).then(c=>c.put(e.request,res.clone()));return res}}).catch(()=>caches.match('./index.html'))))}});
"""
  (dest/"sw.js").write_text(worker,encoding="utf-8")
  hp=dest/entry; html=hp.read_text(encoding="utf-8")
  if 'rel="manifest"' not in html: html=html.replace("</head>",'<link rel="manifest" href="./manifest.webmanifest">\n</head>')
  if "navigator.serviceWorker.register" not in html: html=html.replace("</body>",'<script>if("serviceWorker" in navigator)window.addEventListener("load",()=>navigator.serviceWorker.register("./sw.js").catch(()=>{}));</script>\n</body>')
  hp.write_text(html,encoding="utf-8")
  zp=downloads/f"{gid}-browser-pwa.zip"
  with zipfile.ZipFile(zp,"w",zipfile.ZIP_DEFLATED,compresslevel=9) as z:
   for f in sorted(dest.rglob("*")):
    if f.is_file():z.write(f,f.relative_to(dest).as_posix())
  zh=checksum(zp)
  tp=downloads/f"{gid}-browser-pwa.tar.gz"
  with tarfile.open(tp,"w:gz") as t:t.add(dest,arcname=gid)
  th=checksum(tp)
  rows.append({"id":gid,"url":f"/games/{gid}/","zip":f"/downloads/games/{zp.name}","zip_sha256":zh,"tar_gz":f"/downloads/games/{tp.name}","tar_gz_sha256":th})
 (downloads/"catalog.json").write_text(json.dumps({"schema_version":1,"distribution":"cross-platform browser PWA; no native APK, EXE or DEB is claimed","games":rows},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps(rows,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
