# ChromaMatter version policy

- Public application name: `ChromaMatter — AI Model Print Studio`
- Public displayed version: `0.8beta`
- Public release revision: `r32`
- Windows string version: `0.8beta`
- Windows numeric version: `0.8.0.0` (numeric resource fields cannot contain `beta`)
- Public executable identity: `ChromaMatter.exe` / `ChromaMatter`
- Public source artifact: `ChromaMatter-0.8beta-r32-source-public-20260823`
- Public software artifact: `ChromaMatter-0.8beta-r32-win64`
- Detached distribution checksum record after final restage: `SHA256SUMS-r32.txt`
- Do not change any public version string merely for fixes or beta features.
- Advance the version only after an explicit user request.

This pin applies to the window title, self-test/report application identity,
3MF hotfix metadata, documentation, and the release name selected during
packaging. Legacy executable, schema, and `%APPDATA%\TripoSpectrumMapper`
identifiers remain readable intentionally so existing projects, language, and
application preferences are not lost during the rename.

The r32 edition advances independently while the public display and Windows
versions remain pinned. Exact r32 regression, clean build, packaged self-test,
isolated Japanese/English UI smoke, source/software stage, fresh extraction,
checksum, and GitHub-update evidence are pending until they are measured from
the frozen r32 source. The completed r31 source-only publication remains
previous evidence and must not be presented as validation of r32.
