# Code-license decision record

On 2026-09-20, the owner confirmed authority to license the original project code and
selected Apache License 2.0. The canonical text is in `LICENSE`, and package metadata
uses SPDX identifier `Apache-2.0`.

## Independent model and third-party decision

Apache-2.0 applies only to original project code. It does not relicense model weights,
model conversions, fonts, or dependencies. The fast Electron build contains
hash-verified GigaAM-He and Silero VAD; MiLMMT is downloaded and verified during
desktop preparation. The optional ivrit.ai Whisper MLX conversion is downloaded
only when Accurate recognition is selected. Its conversion card does not clearly
state a license, so its provenance and notice obligations remain a public-release
gate. GigaAM-He is offered
under the publisher's stated MIT terms; MiLMMT is subject to separate Gemma
terms; Silero VAD is MIT. The public binary must include all required license
texts, notices, and use conditions before distribution. The separate review
and its open Gemma redistribution gate are in `THIRD_PARTY.md`.

The export scanner, wheel, sdist, and source allowlist require the project `LICENSE`.
No project `NOTICE` was added because the original project does not currently declare
project-level attribution notices. Third-party license and notice obligations remain a
separate review item; if that review finds required NOTICE content, add only the
supported attribution text and rerun the package/export gates.
