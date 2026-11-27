(() => {
  // Source snapshot: 2026-11-03 (current repository sources, no build artifacts).
  // Every part is size- and SHA-256-checked before it is written.
  const parts = [
    {
      name: "streamiov-studio-part-00.bin",
      size: 86540,
      sha256: "0ac880e769393db4269986f2ea90ae49e2195d8ed5028b46aff5e323145cf4ab"
    },
    {
      name: "streamiov-studio-part-01.bin",
      size: 86539,
      sha256: "759c9fbf6c92b45f5c2437875841938db5ce0f96fd0b1ed036c76d1566740579"
    },
    {
      name: "streamiov-studio-part-02.bin",
      size: 86539,
      sha256: "92da607909cf16720964b557b87fb204f8d9f5ff4ec0c3a776c4e5d1ed5e90d8"
    },
    {
      name: "streamiov-studio-part-03.bin",
      size: 86539,
      sha256: "6b4e5e32417fdaec84846079f36cbe60b65815ba7dd5935a983b5d2ba0edadd8"
    },
    {
      name: "streamiov-studio-part-04.bin",
      size: 86539,
      sha256: "7bf9467f12b72563e66a9a973a65c3c9a1a0c49ce8d914a089341fd965748b94"
    },
    {
      name: "streamiov-studio-part-05.bin",
      size: 86539,
      sha256: "f760dbcff927b51ea39c4776211b58647d11c98ffadfffef69f2979746586188"
    },
    {
      name: "streamiov-studio-part-06.bin",
      size: 86539,
      sha256: "1cbea7b1602e1741d2e85a2956f5b14dc072ac8cbdddc1af2ddfd0d7b4ef2e22"
    }
  ];

  const expectedArchiveSha256 =
    "94776cba9af77eaff61149c6ceb810a27033de164decd332c1e9868026c4ffae";
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

  async function downloadStudio(button) {
    const status = document.getElementById(button.dataset.studioStatus);
    const progress = document.getElementById(button.dataset.studioProgress);
    if (!status || !progress) return;

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
      const signature = [];
      const archiveChunks = [];

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
          archiveChunks.push(chunk);
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
          throw new Error(
            "SHA-256 ist in diesem Browser nicht verfügbar. Die ZIP wurde nicht gespeichert."
          );
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
      if (hashVerified !== parts.length) {
        throw new Error("Nicht alle SHA-256-Prüfsummen konnten verifiziert werden.");
      }

      const archiveSha256 = await sha256Hex(archiveChunks);
      if (archiveSha256 === null) {
        throw new Error(
          "SHA-256 des zusammengesetzten Archivs konnte nicht berechnet werden. ZIP wurde nicht gespeichert."
        );
      }
      if (archiveSha256 !== expectedArchiveSha256) {
        throw new Error(
          `SHA-256 des zusammengesetzten Archivs stimmt nicht: ${archiveSha256} statt ${expectedArchiveSha256}. ` +
          "ZIP wurde nicht gespeichert."
        );
      }

      await writable.close();
      writable = null;
      progress.textContent = "100 %";

      status.textContent =
        `Download vollständig. Größe (${totalSize.toLocaleString("de-DE")} Bytes), ZIP-Kennung, ` +
        `alle ${parts.length} SHA-256-Prüfsummen der Teile und die SHA-256-Prüfsumme des zusammengesetzten Archivs sind verifiziert. ` +
        `Archiv-SHA-256: ${archiveSha256}. Bitte ZIP vor der Installation entpacken und prüfen.`;
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
    document.querySelectorAll("[data-studio-download]").forEach(button => {
      button.addEventListener("click", () => downloadStudio(button));
    });
  });
})();
