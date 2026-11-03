(() => {
  // Source snapshot: 2026-11-03 (current repository sources, no build artifacts).
  // Every part is size- and SHA-256-checked before it is written.
  const parts = [
    {
      name: "streamiov-studio-part-00.bin",
      size: 124327,
      sha256: "28808f10458a249a0dff98f293a1d9521e8a10c0d21dfe8d6e7437707c65741f"
    },
    {
      name: "streamiov-studio-part-01.bin",
      size: 124327,
      sha256: "889ecf2bd580ea077d24f32fc32a2648481e3692bd5fed2b5c51e40e17253f2b"
    },
    {
      name: "streamiov-studio-part-02.bin",
      size: 124327,
      sha256: "42f59a75649658ee96f9c71d5e0626f5fea2e4d698fbe660f5c0cf114492d0f2"
    },
    {
      name: "streamiov-studio-part-03.bin",
      size: 124327,
      sha256: "24fea902e1f6f0423b49507167d296d6834f6589625e1498aa6d3e4bf7bc89c3"
    },
    {
      name: "streamiov-studio-part-04.bin",
      size: 124327,
      sha256: "7cc44f200cd812f0bd3afecab7e794c11fa42ed30d1a2e26b44e5d7bd60662bc"
    },
    {
      name: "streamiov-studio-part-05.bin",
      size: 124327,
      sha256: "c767704b7094f35a8ffd55c55105cb22ef5bf81aedcc569b78b7b71781623a5d"
    },
    {
      name: "streamiov-studio-part-06.bin",
      size: 124321,
      sha256: "4d6890a9d4a58ce3a2bee1228d0ff1bd2782abb17732e9f4553db70c59063a2d"
    }
  ];

  const expectedArchiveSha256 =
    "af97d095b280fd16a3fd69e67a0de5815f8402d3cf3c460a77f1e43a59670bfd";
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
