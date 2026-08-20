# ChromaMatter application icon provenance

Status: **creator-authorized for the approved source-only release; no independent legal clearance performed**

## Source record

- Received from the user in this Codex task on 2026-08-20.
- Original filename: `ChatGPT Image 2026年8月20日 11_22_50.png`
- Original format and dimensions: RGB PNG, 1254 x 1254 px
- Original SHA-256: `CEB0A34A314D50DBA6B7AA5105C0007D5AE7C4BBE404D636EADB84ED6DB740EC`
- The original user-supplied file is not copied into the public source tree.

## Deterministic application assets

`tooling/generate_public_icon.py` accepts only the exact source hash above. It
removes the bright background connected to the four outside corners, keeps
interior white details opaque, downsamples with Pillow LANCZOS, and writes the
following runtime assets:

- `obj_adjuster_icon.png`: 1024 x 1024 RGBA PNG; SHA-256 `BDDD06B090F25FFEAE20F393A86A8E65B297923D2F8A1FE8461CF93A9B3AEA3B`
- `obj_adjuster_icon.ico`: explicit 16, 24, 32, 48, 64, 128, and 256 px PNG-backed ICO frames; SHA-256 `EC7324CA3B19134ED31FA34870DD89DD12913FF5275EA06A2D7419CD60B1C5B0`

The legacy `obj_adjuster_icon` filenames remain internal compatibility paths;
the displayed artwork is the user-selected ChromaMatter mark.

## Creator declaration and publication decision

On 2026-08-20, the user and project creator declared that:

- the stylized robot is an original fictional machine created for this project;
  references influenced the design, but the machine is not intended to depict
  or reproduce an existing character or product;
- `ZENITH DYNAMICS CORP.` is fictional wording created for the artwork and is
  not intended to identify or imply affiliation with any real organization;
- the creator authorizes public use and redistribution of the supplied artwork
  as the ChromaMatter icon, including use in the repository, executable,
  screenshots, videos, and Innovation Fund submission; and
- the creator knowingly gave a publication **GO** for this asset and release.

A basic exact-phrase web check performed during release review found no exact
match for `ZENITH DYNAMICS CORP.` and no exact match for `ChromaMatter`.
Several active organizations do, however, use the close name `Zenith Dynamics`.
The project therefore makes no claim that either expression is globally clear,
registrable, or free of third-party rights, and it must not imply affiliation
with those organizations.

This record captures the creator's declaration and publication authorization.
It is not an independent trademark search, third-party likeness clearance,
legal opinion, or guarantee about every jurisdiction. The project owner accepts
that residual risk and has chosen to proceed with publication.

The final r31 source-only stage passed its icon hash, identity, tooling, archive,
and privacy checks. This authorizes the icon inside the approved source release;
it does not waive the separate third-party licence audit required before the
prebuilt executable or software ZIP can be published.
