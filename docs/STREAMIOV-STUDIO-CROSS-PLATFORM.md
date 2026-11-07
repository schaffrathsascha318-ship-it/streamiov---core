# Streamiov Studio – Cross-Platform Architektur

## Produktziel

Eine gemeinsame Streamiov-Regie für Windows 11 x64, Linux x64, ChromeOS/Chromebook,
Android und iOS. Szenen, Preview/Program/TAKE, Chat, TTS, Alerts, Musik,
Streamiov-Galerie und KI-Regie bleiben fachlich gemeinsame Studio-Funktionen.
Geräteabhängige Aufnahme-, Audio- und Encoder-Funktionen werden über Adapter
bereitgestellt und anhand real verfügbarer Fähigkeiten freigeschaltet.

## Bestehender Stand (Ausgangslage)

- Die vorhandene Desktop-App basiert auf Electron.
- Bereits vorhandene Build-Skripte erzeugen Windows x64, Linux x64 und
  ChromeOS-Linux-Pakete (x64/ARM64).
- Die bestehende Regie enthält bereits responsive Mobile-CSS-Regeln und einen
  separaten mobilen Inhaltsbereich.
- Electron-Builds sind keine Android- oder iOS-Apps.
- Eine vollständige mobile Version benötigt einen nativen Runtime-/Plugin-Layer
  (vorgesehen: Capacitor) und native Adapter für Kamera, Mikrofon,
  Benachrichtigungen, Dateizugriff und Audio.
- Bildschirmaufnahme, Systemton, Mehrfach-Audioausgänge und Hardware-Encoding
  unterscheiden sich je Betriebssystem und müssen zur Laufzeit geprüft werden.

## Architekturregeln

1. Gemeinsame Regie- und Szenenlogik bleibt plattformneutral.
2. Gerätefunktionen werden nicht anhand des Gerätenamens versprochen, sondern
   durch Capability Detection und echte Runtime-Probes freigegeben.
3. Windows 11 x64 ist primäres Desktop-Ziel; kein ARM-Build als Ersatz dafür.
4. Linux x64 und ChromeOS werden separat gebaut und auf realer Hardware getestet.
5. Android und iOS erhalten eigene native App-Pakete; Electron wird dort nicht
   als mobile Laufzeit verwendet.
6. TikTok LIVE bleibt die einzige externe Streaming-Plattform im aktuellen Scope.
7. Streamiov Core bleibt zentraler Dienst. Das Chromebook ist kein produktiver
   Streaming- oder Hosting-Server.
8. Keine Änderung an TikTok-App-Registrierung, OAuth-Geheimnissen, Cloudflare-
   Produktion, DNS oder produktiven Releases ohne gesonderte Freigabe.

## Umsetzungsphasen

### Phase 1 – Gemeinsame Plattform-Erkennung
- Plattform- und Laufzeit-Erkennung
- Capability-Modell für Kamera, Mikrofon, Bildschirmaufnahme, Audioausgänge,
  Benachrichtigungen, Dateizugriff und Hardware-Encoding
- Tests für Windows, Linux, ChromeOS, Android und iOS

### Phase 2 – Adapter-Grenzen
- Einheitliche Interfaces für Capture, Audio Routing, Encoder und Notifications
- Electron-Adapter für Desktop
- Capacitor-Adapter für Android/iOS
- Capability-basierte UI statt nicht unterstützter Bedienelemente

### Phase 3 – Native mobile Apps
- Capacitor-Projekt und native Android-/iOS-Projekte
- sichere Berechtigungsabfragen zur Laufzeit
- mobile Regie mit Inhaltsbereich oben und Regie darunter
- Geräte- und Hintergrundverhalten auf echten Geräten testen

### Phase 4 – Medienpipeline
- Compositor, Audio-Mixer mit unabhängigen Ausgängen und Encoder
- Hardware-Encoder-Fallbacks je Plattform
- Last-, Latenz-, Wiederverbindungs- und Langzeittests

### Phase 5 – Release-Matrix
- Windows 11 x64 Installer
- Linux x64 AppImage/DEB
- ChromeOS-Paket passend zur CPU-Architektur
- Android APK/AAB
- iOS IPA über Apples Signierungs-/Build-Prozess
- erst nach bestandenen Tests als produktiv freigeben

## Status dieses Commits

Dieser Commit legt die gemeinsame Capability-Erkennung samt Tests und die
verbindliche Plattformarchitektur an. Er erzeugt noch keine fertigen Android-
oder iOS-Installationspakete und behauptet keine produktive Medienpipeline.
