# Code-license decision record

On 2026-09-20, the owner confirmed authority to license the original project code and
selected Apache License 2.0. The canonical text is in `LICENSE`, and package metadata
uses SPDX identifier `Apache-2.0`.

## Independent model and third-party decision

Apache-2.0 applies only to original project code. It does not relicense model weights,
model conversions, fonts, or dependencies. The installer downloads model assets only
after an explicit command and displays their sources and terms/evidence links. Users
may instead supply compatible local model paths. Both routes retain the separate
review described in `THIRD_PARTY.md`.

The export scanner, wheel, sdist, and source allowlist require the project `LICENSE`.
No project `NOTICE` was added because the original project does not currently declare
project-level attribution notices. Third-party license and notice obligations remain a
separate review item; if that review finds required NOTICE content, add only the
supported attribution text and rerun the package/export gates.
