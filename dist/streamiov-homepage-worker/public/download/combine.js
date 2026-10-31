






















                                     
(() => {
  const parts = [
    "streamiov-studio-part-00.bin",
    "streamiov-studio-part-01.bin",
    "streamiov-studio-part-02.bin",
    "streamiov-studio-part-03.bin",
    "streamiov-studio-part-04.bin",
    "streamiov-studio-part-05.bin",
    "streamiov-studio-part-06.bin"
  ];

  const base = "/downloads/";
  const totalSize = 129377662;

  async function downloadStudio() {
    const button = document.getElementById("studio-one-click");
    const status = document.getElementById("studio-status");
    const progress = document.getElementById("studio-progress");

    if (!("showSaveFilePicker" in window)) {
      status.textContent =
        "Dein Browser unterstützt den direkten Dateidownload nicht. Bitte nutze vorerst die sieben Download-Teile weiter unten.";
      return;
    }

    let writable;

    try {
      const handle = await window.showSaveFilePicker({
        suggestedName: "streamiov-studio.zip",
        types: [{
          description: "ZIP-Datei",
          accept: { "application/zip": [".zip"] }
        }]
      });

      button.disabled = true;
      status.textContent = "Studio wird heruntergeladen …";
      progress.textContent = "0 %";

      writable = await handle.createWritable();
      let downloaded = 0;

      for (let i = 0; i < parts.length; i++) {
        status.textContent =
          `Lade Teil ${i + 1} von ${parts.length} …`;

        const response = await fetch(base + parts[i]);

        if (!response.ok || !response.body) {
          throw new Error(`Download-Teil ${i + 1} fehlgeschlagen.`);
        }

        const reader = response.body.getReader();

        while (true) {
          const result = await reader.read();
          if (result.done) break;

          await writable.write(result.value);
          downloaded += result.value.byteLength;

          const percent = Math.min(
            100,
            Math.floor(downloaded / totalSize * 100)
          );

          progress.textContent = `${percent} %`;
          status.textContent =
            `Studio-Download: ${downloaded.toLocaleString("de-DE")} Bytes`;
        }
      }

      await writable.close();
      writable = null;

      progress.textContent = "100 %";
      status.textContent =
        "Download abgeschlossen. Bitte ZIP-Datei anschließend prüfen.";
    } catch (error) {
      if (writable) {
        try {
          await writable.abort();
        } catch (_) {}
      }

      if (error.name !== "AbortError") {
        status.textContent =
          "Download fehlgeschlagen: " + error.message;
      }
    } finally {
      button.disabled = false;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const button = document.getElementById("studio-one-click");
    if (button) {
      button.addEventListener("click", downloadStudio);
    }
  });
})();

