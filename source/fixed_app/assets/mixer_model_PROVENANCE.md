# mixer_model.npz provenance

`mixer_model.npz` contains polynomial powers, coefficients, and intercepts used only for colour-mix prediction.

- Upstream project: <https://github.com/justinh-rahb/filament-mixer>
- Upstream revision verified: `22a23e9ed479f06b4ab57998b82f5e08093bb406`
- Upstream file: `cpp/filament_mixer.h`
- Upstream file SHA-256: `65986A94CD8B89CAD1A231E44021558FC9450B3D1AE831FD48AF4AAC4DDEF7D4`
- Upstream license: MIT
- Upstream copyright notice: Copyright (c) 2026 Justin Hayes
- Bundled NPZ SHA-256: `9A54432438132038E60BB3F8F348FB4A73ADAAE20AFAC0357E80631EE8143914`

The arrays in the bundled NPZ were compared element-for-element with that upstream revision on 2026-08-06: `POWERS`, `COEF`, and `INTERCEPT` were exactly equal, including all floating-point values.

`tooling/build_mixer_model.py` documents the conversion and can either rebuild the NPZ from a separately downloaded copy of the upstream header or verify an existing NPZ. The script performs no network access. With the pinned dependencies and exact header above, `numpy.savez_compressed` reproduces the bundled NPZ byte-for-byte.

The historical source label inside the NPZ names the Snapmaker Orca integration header from which the data was first extracted. The exact values are independently anchored to the upstream FilamentMixer revision above. Inclusion of this MIT-licensed data does not imply endorsement by Justin Hayes, FilamentMixer, Snapmaker, or Snapmaker Orca.

