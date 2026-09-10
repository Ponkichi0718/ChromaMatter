# Frozen Windows dependency recipe

`BUILD_PYTETWILD_WINDOWS_20260823.ps1` is the byte-exact recipe used by the
successful controlled PyTetWild rebuild recorded in the dependency attestation.
It is 82,572 bytes with SHA-256
`d00cc6cdbc61abeaa040dfc81a3dfe7086ac0027685d798ac70f46e14e4360c8`.
The file was recovered from source commit
`5feb198eef3432cdec19a0367d53e1b52bd4a363`, without changing its contents.

The separately maintained `../BUILD_PYTETWILD_WINDOWS.ps1` includes subsequent
Visual Studio layout and PowerShell discovery changes. Those changes are
preserved, but they did not produce the approved dependency wheel and are not
substituted for its actual build evidence. Using that developer recipe for a
new release wheel requires a new controlled rebuild and matching attestation.

The static-closure and corresponding-source gates bind the frozen recipe,
approved repaired wheel, distinct raw wheel, eight physical audit logs,
attestation, component source archives, and application dependency lock. All
byte/hash and exact release-commit checks remain mandatory. Relocating this
recipe does not approve a changed wheel or an application distribution.

When reproducing the frozen build from this location, explicitly supply
`-RequirementsLock` with `../requirements-pytetwild-build.lock` and
`-PyTetWildSourcePatch` with
`../patches/pytetwild-0.3.0-optional-pyvista.patch` (resolved relative to this
directory), along with all controlled toolchain/output/network inputs required
by the recipe. The historical recipe's default paths assumed its former
location. Preserve its bytes; do not edit the frozen recipe to adjust paths.
