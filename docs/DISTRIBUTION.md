# Public macOS distribution

The desktop release is one Apple Silicon `Hebrew Live.app` containing GigaAM-He
and Silero VAD. It downloads the pinned MiLMMT files during first preparation or
when files need repair. Optional ivrit.ai Whisper weights download only when
Accurate recognition is selected; the Whisper runtime itself is in the app.
A DMG is a
compressed macOS disk image: the user opens it, sees the English or Russian
software agreement, accepts it, and drags the app into Applications. The app
also requires first-launch acceptance, covering direct `.app` copies and later
agreement changes. ZIP is another container for the same app, without the DMG
agreement prompt; neither format changes the model licensing, installed size,
or Apple's trust checks. The compressed size must be measured on the final
signed app.

For the previous **all-model unsigned local test build**, the `.app` is 3,903,787,049
logical bytes, the verified DMG with a bilingual license prompt is
3,110,351,044 bytes, and the verified comparison ZIP is 3,111,887,555 bytes.
DMG is 1,536,511 bytes smaller (about 0.05%).
Signing and notarization will change the final published bytes and checksum.

The **lighter unsigned local test DMG** built on 2026-09-24 is
1,132,996,132 bytes (1.055 GiB), with SHA-256
`6f54b2223c0333ae23a0246c5d407b68b6dfcad5456900176b11aaca834844e1`.
It contains GigaAM-He and Silero, but no MiLMMT or Whisper weights. This is a local test
artifact, not a signed public release.

## Release gates

1. Review the model provenance, the optional Whisper MLX conversion's missing
   license declaration, Gemma use restrictions and notice obligations, the bundled
   notices and complete agreement, and the Hebrew Live first-launch agreement
   with qualified counsel for the intended public markets. The first-launch
   click-through records the agreement version locally and blocks model
   preparation and backend launch until accepted. It is not a legal opinion or
   proof that every clause will be enforceable everywhere.
2. Obtain an Apple Developer ID Application signing identity, sign the app and
   its native components with appropriate entitlements, notarize with Apple,
   and staple the result. The current local build is unsigned and must not be
   described as a public-ready, trusted download.
3. Test the exact notarized DMG on a clean second Apple Silicon Mac with the
   supported macOS version. Confirm Gatekeeper, drag-to-Applications,
   first-launch agreement, initial download, offline reuse, microphone permission, a real
   Hebrew-to-Russian session, archive, and uninstall behavior.
4. Create a SHA-256 checksum for the exact published DMG, and publish its
   version, architecture, minimum macOS, size, known limits, license links,
   checksum, and download location together.

## Hosting

[GitHub Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
accepts individual assets smaller than 2 GiB. The local DMG build targets at
most 1.8 GiB to leave headroom. If the compressed DMG is larger,
publish the source and release notes on GitHub and link to a separate binary
host. Do not commit the DMG or model weights into the source repository.

[Google Drive](https://support.google.com/drive/answer/2494822?hl=en) can share
a DMG to "Anyone with the link" as Viewer, with downloading enabled. It is
reasonable for a small first release, but it is not a dedicated software
distribution service. A public Drive link reveals the owner's name and email
address; use an account whose identity you intend to expose. High download
traffic may hit Drive limits, so object storage with stable public downloads
is preferable if the audience grows. Uploading, link sharing, and publishing
the release are separate external actions.

## User instructions for a signed and notarized build

1. Download the DMG from the release link and compare its SHA-256 with the
   value in the release notes.
2. Open the DMG and drag `Hebrew Live.app` to Applications. Eject the DMG.
3. Open the app from Applications, read and accept the software agreement and
   Gemma restrictions, then complete hardware and microphone checks.
4. The app verifies included GigaAM-He and Silero, then downloads MiLMMT if
   missing or damaged. After preparation it works offline. The user does not
   need a separate manual model package.

Do not advise users to bypass Gatekeeper for an unsigned public build.
