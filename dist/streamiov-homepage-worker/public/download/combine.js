(() => {
  // Source snapshot: 2026-11-03 (current repository sources, no build artifacts).
  // Every part is size- and SHA-256-checked before it is written.
  const parts = [
    {
      name: "streamiov-studio-part-00.bin",
      size: 121724,
      sha256: "91bdbc5ca00c15aa074952308c10ee6ad7d2b7dea7a89bc5daa61508bf7a8a83"
    },
    {
      name: "streamiov-studio-part-01.bin",
      size: 121724,
      sha256: "27ebad2f51df8ab31594d589ae240803e4ca4055e70b401c37e154a1a46c93db"
    },
    {
      name: "streamiov-studio-part-02.bin",
      size: 121724,
      sha256: "dfe25d5abf7184a8ec5834b47f33dfa7e17eec8589f045708a4febe2da6f6c8a"
    },
    {
      name: "streamiov-studio-part-03.bin",
      size: 121724,
      sha256: "b053683ecad154140ae5af012154eb18690a43d9cd2fc0a5d47051068d1fd028"
    },
    {
      name: "streamiov-studio-part-04.bin",
      size: 121724,
      sha256: "5fa1d950e9c948cad11180d541f2d4f534218934316731cb6cb1af5d19694500"
    },
    {
      name: "streamiov-studio-part-05.bin",
      size: 121724,
      sha256: "91f19762a66cc760a66eeaed9d77829db0d439d1c5db5c7ccf3c92b1a4886ad1"
    },
    {
      name: "streamiov-studio-part-06.bin",
      size: 121723,
      sha256: "22fec59f8cfc6bcdcde2696ae2178dfe9e3e1195d4720b03698edd3b7760bf46"
    }
  ];

  const expectedArchiveSha256 =
    "70acd025f9be01b0e4a5e74a735a88f12b208290b69ce084550d721716de1a3c";
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
