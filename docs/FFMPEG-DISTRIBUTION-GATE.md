# FFmpeg runtime distribution gate

Streamiov Studio now stages a pinned FFmpeg executable in the Electron application resources. The current CI candidate is **not approved for public redistribution yet**.

## Pinned binary inputs

- Upstream release: `FFmpeg-Builds/FFmpeg-Builds`, tag `autobuild-2026-11-22-12-36`
- FFmpeg source commit: `359c825152`
- Build scripts commit: `7f2a6b1050d302144de8366afa37a75e46f326aa`
- Variant: static GPLv3, not the nonfree variant
- Windows x64 SHA-256: `af969e0dda60550d75a393a575bad7be6ca7be8e698baa1c80f4963250acc969`
- Windows ARM64 SHA-256: `94c08d75532f5b450f8562871452a863ffeaba66659b740eec85aadf4b6148c4`
- Linux x64 SHA-256: `bcc1539edf917320fd3eb83bd5ab4d0a5ff686980d4717e802e346279beb1f30`
- Linux ARM64 SHA-256: `84ebc321674db39637175861ccfaf840b953bda2f115d7de77dddf155a2f11f6`

CI verifies the downloaded archive checksum before extraction. Native runners must prove that the executable provides `libx264`, native `aac`, RTMP, GPLv3 configuration, and no `--enable-nonfree`. Windows ARM64 is cross-built on an x64 runner; CI checks its PE machine type, but a real ARM64 runtime test remains required.

## Mandatory before release

This FFmpeg variant is GPLv3 because it includes GPL-only components such as x264. The installer must not be published until the release contains the complete corresponding source for the exact FFmpeg build **and every statically linked third-party component**, with their exact revisions, build scripts, and applicable license notices. The FFmpeg GPLv3 license text and binary provenance are embedded in the app resources, but those files alone are not the complete corresponding source.

The release workflow therefore has a hard gate requiring a separately generated `streamiov-ffmpeg-source-code` artifact containing `ffmpeg-source-bundle.tar.xz` and `SHA256SUMS.txt`. Do not weaken or remove that gate to make a release green. The source bundle must be reproducible from the pinned build and dependency revisions before it is attached.

Also review codec patent obligations for H.264/AAC in the jurisdictions where Streamiov is distributed. A successful build or a GPL license notice does not grant patent rights.

## References

- FFmpeg source: https://github.com/FFmpeg/FFmpeg/tree/359c825152
- Pinned build scripts: https://github.com/FFmpeg-Builds/FFmpeg-Builds/tree/7f2a6b1050d302144de8366afa37a75e46f326aa
- Pinned upstream release: https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/tag/autobuild-2026-11-22-12-36
- FFmpeg legal guidance: https://ffmpeg.org/legal.html
