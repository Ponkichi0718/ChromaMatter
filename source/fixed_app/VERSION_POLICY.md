# ChromaMatter version policy

- Public application name: `ChromaMatter — AI Model Print Studio`
- Current development display version: `0.9`
- Current development revision: `r33`
- Current Windows string version: `0.9`
- Current Windows numeric version: `0.9.0.0`
- Public executable identity: `ChromaMatter.exe` / `ChromaMatter`
- Current official-site release: `0.9` for Windows, macOS and Linux
- Published Windows application: `ChromaMatter-0.9-win64-app.zip`
- Published macOS application: `ChromaMatter-0.9-macos-arm64-app.zip`
- Published Linux application: `ChromaMatter-0.9-linux-x86_64.tar.xz`
- Windows corresponding source: `ChromaMatter-0.9-complete-corresponding-source.zip`
- macOS corresponding source: `ChromaMatter-0.9-macOS-corresponding-source.zip`
- Linux corresponding source: `ChromaMatter-0.9-Linux-complete-corresponding-source.zip`
- GitHub synchronization checkpoint (2026-09-10): verified official 0.9 source and archive identities
- Do not change any public version string merely for fixes or beta features.
- Advance the version only after an explicit user request.

The owner has authorized synchronizing GitHub software and source with the
existing official `0.9` publication. The application archives are reused with
identical bytes. This is not a new application build or a new GUI verification.
Windows and Linux use application-source baseline
`5059163a1a6d05e823c44323558f344ad000b580`; macOS has a separate corresponding-source
bundle at `c629f428868e26f11dbcd679983ee2cd74d9c1cd`. Its application, inventory
and complete-source coverage agree; the nested application-source ZIP matches
the official `ChromaMatter-0.9-source-c629f42-2e185dc1.zip` byte for byte,
including CRC, archive comment and all 597 files.
Do not describe one platform's source or native verification as covering another.
Current artifact hashes and publication progress belong to the
[release record](../../RELEASE_0.9.md) and
[platform artifact manifest](../../publication/RELEASE_0.9.json).

This pin applies to the window title, self-test/report application identity,
3MF hotfix metadata, documentation, and the release name selected during
packaging. Legacy executable, schema, and `%APPDATA%\TripoSpectrumMapper`
identifiers remain readable intentionally so existing projects, language, and
application preferences are not lost during the rename.

The project owner explicitly advanced the working application to `0.9` on
2026-09-05.  The principal 0.9 change is improved 3MF output accuracy and
success for ordinary single logical GLB input: exact seams are welded first,
then only strictly planar tiny openings within the bounded repair policy may be
closed, and the result must still pass the unchanged final solid validation.
The Radial Experiment is not part of the 0.9 application UI.

## Historical release — 0.8beta / r32.2

- Published complete corresponding source: `ChromaMatter-0.8beta-r32.2-complete-corresponding-source.zip`
- Published Windows artifact: `ChromaMatter-0.8beta-r32.2-win64.zip`
- Published detached distribution checksum record: `SHA256SUMS-r32.2.txt`

`v0.8beta-r32.2` remains an immutable published prerelease and historical
evidence. Its exact regression, build, packaged/fresh-extracted tests, UI smoke,
source/software stage, checksums, and unauthenticated redownload verification
apply only to frozen commit `aba20685d2fd6987621b2e1e6624f46ea84912a3`.
