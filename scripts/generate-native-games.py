#!/usr/bin/env python3
"""Generate five independent native Godot projects from the shared StreamioV runtime."""
from __future__ import annotations
import json, shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TEMPLATE=ROOT/"games/native-template"
DEST=ROOT/"games/native"
GAMES=[
 ("neon-relay","Neon Relay","Arcade-Reflexspiel"),
 ("echo-grid","Echo Grid","Sequenz- und Gedächtnisrätsel"),
 ("pulse-defender","Pulse Defender","Wellen-Shooter"),
 ("star-defender","Star Defender","Weltraum-Shooter"),
 ("signal-weave","Signal Weave","Leitungs- und Logikrätsel"),
]
def make_presets(game_id,title):
 bundle="org.streamiov.games."+game_id.replace("-","")
 return f"""[preset.0]
name="Windows Desktop x64"
platform="Windows Desktop"
runnable=true
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path="build/StreamioV-{game_id}-windows-x64.exe"
encryption_include_filters=""
encryption_exclude_filters=""
encrypt_pck=false
encrypt_directory=false

[preset.0.options]
custom_template/debug=""
custom_template/release=""
debug/export_console_wrapper=1
binary_format/architecture="x86_64"
binary_format/embed_pck=true

[preset.1]
name="Linux x64"
platform="Linux/X11"
runnable=true
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path="build/StreamioV-{game_id}-linux-x86_64"
encryption_include_filters=""
encryption_exclude_filters=""
encrypt_pck=false
encrypt_directory=false

[preset.1.options]
custom_template/debug=""
custom_template/release=""
debug/export_console_wrapper=1
binary_format/architecture="x86_64"

[preset.2]
name="Android ARM64"
platform="Android"
runnable=false
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path="build/StreamioV-{game_id}-android-arm64.apk"
encryption_include_filters=""
encryption_exclude_filters=""
encrypt_pck=false
encrypt_directory=false

[preset.2.options]
custom_template/debug=""
custom_template/release=""
gradle_build/use_gradle_build=false
architectures/armeabi-v7a=false
architectures/arm64-v8a=true
architectures/x86=false
architectures/x86_64=false
version/code=1
version/name="0.1.0"
package/unique_name="{bundle}"
package/name="StreamioV {title}"
screen/immersive_mode=true
screen/orientation=1
graphics/opengl_debug=false
xr_features/xr_mode=0

[preset.3]
name="iOS Xcode Project"
platform="iOS"
runnable=false
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path="build/StreamioV-{game_id}-ios-xcode.zip"
encryption_include_filters=""
encryption_exclude_filters=""
encrypt_pck=false
encrypt_directory=false

[preset.3.options]
custom_template/debug=""
custom_template/release=""
application/app_store_team_id=""
application/bundle_identifier="{bundle}"
application/signature="StreamioV"
application/short_version="0.1.0"
application/version="1"
application/provisioning_profile=""
application/code_sign_identity_debug=""
application/code_sign_identity_release=""
architectures/arm64=true
"""
def main():
 if not (TEMPLATE/"main.gd").is_file() or not (TEMPLATE/"main.tscn").is_file():
  raise SystemExit("Native Godot template is incomplete.")
 DEST.mkdir(parents=True,exist_ok=True)
 for game_id,title,genre in GAMES:
  project=DEST/game_id
  if project.exists(): shutil.rmtree(project)
  project.mkdir(parents=True)
  shutil.copy2(TEMPLATE/"main.gd",project/"main.gd")
  shutil.copy2(TEMPLATE/"main.tscn",project/"main.tscn")
  settings=f'''config_version=5

[application]
config/name="StreamioV {title}"
config/description="Eigenständiges kostenloses StreamioV-Spiel: {genre}."
run/main_scene="res://main.tscn"
config/features=PackedStringArray("4.7", "GL Compatibility")

[display]
window/size/viewport_width=1280
window/size/viewport_height=720
window/size/window_width_override=1280
window/size/window_height_override=720
window/stretch/mode="canvas_items"
window/handheld/orientation=1

[streamiov]
game_id="{game_id}"

[rendering]
renderer/rendering_method="gl_compatibility"
renderer/rendering_method.mobile="gl_compatibility"
textures/default_filters/use_nearest_mipmap_filter=false
'''
  (project/"project.godot").write_text(settings,encoding="utf-8")
  (project/"export_presets.cfg").write_text(make_presets(game_id,title),encoding="utf-8")
  manifest={"id":game_id,"name":title,"genre":genre,"engine":"Godot 4.7.2","independent":True,"targets":{"windows":"x86_64 EXE","linux":"x86_64 native binary","chromeos":"Android ARM64 APK on supported ChromeOS devices; Linux x86_64 build via Crostini","android":"ARM64 APK","ios":"unsigned Xcode project ZIP; Apple signing and provisioning required"},"release_state":"native prototype; device and gameplay verification pending"}
  (project/"game.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps([{"id":g[0],"path":str((DEST/g[0]).relative_to(ROOT))} for g in GAMES],indent=2))
if __name__=="__main__":main()
