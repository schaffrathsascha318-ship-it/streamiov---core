(() => {
  // Source snapshot: 2026-11-03 (current repository sources, no build artifacts).
  // Every part is size- and SHA-256-checked before it is written.
  const parts = [
    {
      name: "streamiov-studio-part-00.bin",
      size: 121731,
      sha256: "ca0bce22a0605a325e38b65ad5008b5a80316a03d1a032ed692c21e16ccb0e91"
    },
    {
      name: "streamiov-studio-part-01.bin",
      size: 121731,
      sha256: "72f3294c3a2a5ce7b090e1c6752d56942dc4a764b26d934b3913f5fbba217e50"
    },
    {
      name: "streamiov-studio-part-02.bin",
      size: 121731,
      sha256: "7f240c9f90ca7995b024e2a7f38434d3755be3d75b0dd1535d2838ab312dc24e"
    },
    {
      name: "streamiov-studio-part-03.bin",
      size: 121731,
      sha256: "cfa3cfd51e2f61b7eeea21a38641bdeb433c948d33651a76fde9588d10a15e19"
    },
    {
      name: "streamiov-studio-part-04.bin",
      size: 121731,
      sha256: "ba6e507993ec7e48a3e5f751a74a6f0340d96d189b59eb26c4b6d4c91a13f693"
    },
    {
      name: "streamiov-studio-part-05.bin",
      size: 121731,
      sha256: "9d91454aed50c61b40cd63e9517e483afae382aba2e3737c81a28a43ae45d824"
    },
    {
      name: "streamiov-studio-part-06.bin",
      size: 121731,
      sha256: "a04370e051e978f8ed47aa18b88ad568c28f557cf2e06a06d4995f91361c64f5"
    }
  ];

  const expectedArchiveSha256 =
    "d223a9fd6e68bb2b7fb04973af173ee7600a291777be2fde5213638ea1c230a1";
  const base = "/downloads/";
  const totalSize = parts.reduce((sum, part) => sum + part.size, 0);
  const isZipSignature = bytes =>
    bytes.length === 4 &&
    bytes[0] === 0x50 &&
    bytes[1] === 0x4b &&
    bytes[2] === 0x03 &&
    bytes[3] === 0x04;

  const toHex = buffer =>
    Array.from(new Uint8Array(buffer))
      .map(byte => byte.toString(16).padStart(2, "0"))
      .join("");

  async function sha256Hex(chunks) {
    if (!globalThis.crypto?.subtle) return null;
    const buffer = await new Blob(chunks).arrayBuffer();
    return toHex(await crypto.subtle.digest("SHA-256", buffer));
  }

  async function downloadStudio() {
    const button = document.getElementById("studio-one-click");
    const status = document.getElementById("studio-status");
    const progress = document.getElementById("studio-progress");

    if (!("showSaveFilePicker" in window)) {
      status.textContent =
        "Dein Browser unterstützt den direkten Download nicht. Bitte nutze die sieben manuellen Download-Teile und die Zusammenfüge-Anleitung.";
      return;
    }

    let writable;

    try {
      const handle = await window.showSaveFilePicker({
        suggestedName: "streamiov-studio-source-20261103.zip",
        types: [{
          description: "ZIP-Datei",
          accept: { "application/zip": [".zip"] }
        }]
      });

      button.disabled = true;
      status.textContent = "Quellpaket wird heruntergeladen …";
      progress.textContent = "0 %";
      writable = await handle.createWritable();

      let downloaded = 0;
      let hashVerified = 0;
      let hashUnavailable = false;
      const signature = [];

      for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        status.textContent = `Lade Teil ${i + 1} von ${parts.length} …`;

        const response = await fetch(base + part.name, { cache: "no-store" });
        if (!response.ok || !response.body) {
          throw new Error(`Download-Teil ${i + 1} fehlgeschlagen (HTTP ${response.status}).`);
        }

        const reader = response.body.getReader();
        const chunks = [];
        let partBytes = 0;

        while (true) {
          const result = await reader.read();
          if (result.done) break;

          const chunk = result.value;
          if (i === 0 && signature.length < 4) {
            for (const byte of chunk) {
              if (signature.length === 4) break;
              signature.push(byte);
            }
          }

          chunks.push(chunk);
          await writable.write(chunk);
          partBytes += chunk.byteLength;
          downloaded += chunk.byteLength;

          const percent = Math.min(100, Math.floor(downloaded / totalSize * 100));
          progress.textContent = `${percent} %`;
          status.textContent =
            `Teil ${i + 1}/${parts.length}: ${partBytes.toLocaleString("de-DE")} Bytes · Gesamt ${downloaded.toLocaleString("de-DE")} Bytes`;
        }

        if (partBytes !== part.size) {
          throw new Error(`Teil ${i + 1} hat ${partBytes} statt ${part.size} Bytes. ZIP wurde nicht gespeichert.`);
        }

        const actualHash = await sha256Hex(chunks);
        if (actualHash === null) {
          hashUnavailable = true;
        } else if (actualHash !== part.sha256) {
          throw new Error(
            `Teil ${i + 1} hat eine falsche SHA-256-Prüfsumme. ZIP wurde nicht gespeichert.`
          );
        } else {
          hashVerified += 1;
        }
      }

      if (downloaded !== totalSize) {
        throw new Error(`Gesamtgröße stimmt nicht: ${downloaded} statt ${totalSize} Bytes.`);
      }
      if (!isZipSignature(signature)) {
        throw new Error("Die zusammengesetzte Datei hat keine gültige ZIP-Kennung. Download abgebrochen.");
      }

      await writable.close();
      writable = null;
      progress.textContent = "100 %";

      if (hashVerified === parts.length) {
        status.textContent =
          `Download vollständig. Größe, ZIP-Kennung und alle ${parts.length} SHA-256-Prüfsummen stimmen. ` +
          `Archiv-SHA-256: ${expectedArchiveSha256}. Bitte ZIP vor der Installation entpacken und prüfen.`;
      } else if (hashUnavailable) {
        status.textContent =
          "Download vollständig. Größe und ZIP-Kennung stimmen. Die SHA-256-Prüfung ist in diesem Browser " +
          "nicht verfügbar; vergleiche die Datei bitte mit SHA256SUMS.txt.";
      }
    } catch (error) {
      if (writable) {
        try {
          await writable.abort();
        } catch (_) {}
      }
      if (error.name !== "AbortError") {
        status.textContent = "Download fehlgeschlagen: " + error.message;
        progress.textContent = "Nicht vollständig";
      }
    } finally {
      button.disabled = false;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const button = document.getElementById("studio-one-click");
    if (button) button.addEventListener("click", downloadStudio);
  });
})();
