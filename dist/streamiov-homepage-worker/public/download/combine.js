(() => {
  // Source snapshot: 2026-11-03 (current repository sources, no build artifacts).
  // Every part is size- and SHA-256-checked before it is written.
  const parts = [
    {
      name: "streamiov-studio-part-00.bin",
      size: 83934,
      sha256: "444f22a1e994209f529f538a509a19416445d2323ea687cd58d997631b9ed634"
    },
    {
      name: "streamiov-studio-part-01.bin",
      size: 83934,
      sha256: "f488a2c882d5d02496f3bbc02ae79a1949d4b7ce071a6222901e068d88a6a8f2"
    },
    {
      name: "streamiov-studio-part-02.bin",
      size: 83933,
      sha256: "cd7356f5eb71fa4c31a68f348e889c4ebbbabeb1b6e7a7dc1a5c32315c2b6751"
    },
    {
      name: "streamiov-studio-part-03.bin",
      size: 83933,
      sha256: "7467a0bf697fb07d3acef65c3c21afb0dee15eacb68fce8cea5a02d1ad0a7c82"
    },
    {
      name: "streamiov-studio-part-04.bin",
      size: 83933,
      sha256: "3ec56621736d15fb6b843b7fe51178649ea07cd4b2fab4fb8a7c7fa1d42ac75b"
    },
    {
      name: "streamiov-studio-part-05.bin",
      size: 83933,
      sha256: "c0b224153795bad154bf5f52f8aba16ede791a5db082c289c1bdf41732238fa6"
    },
    {
      name: "streamiov-studio-part-06.bin",
      size: 83933,
      sha256: "e61563dd4058cdb5e537d7ad2d2416a653531535b0ef23fc8bc1f5e00b43e05c"
    }
  ];

  const expectedArchiveSha256 =
    "a63c21daba46d866642d72f09d6315be22cfde9c0be3d28827f8edb6d780bec9";
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
