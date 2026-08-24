# ChromaMatter version policy

- Public application name: `ChromaMatter — AI Model Print Studio`
- Public displayed version: `0.8beta`
- Current published prerelease revision: `r32.2`
- Windows string version: `0.8beta`
- Windows numeric version: `0.8.0.0` (numeric resource fields cannot contain `beta`)
- Public executable identity: `ChromaMatter.exe` / `ChromaMatter`
- Published complete corresponding source: `ChromaMatter-0.8beta-r32.2-complete-corresponding-source.zip`
- Published Windows artifact: `ChromaMatter-0.8beta-r32.2-win64.zip`
- Published detached distribution checksum record: `SHA256SUMS-r32.2.txt`
- Do not change any public version string merely for fixes or beta features.
- Advance the version only after an explicit user request.

This pin applies to the window title, self-test/report application identity,
3MF hotfix metadata, documentation, and the release name selected during
packaging. Legacy executable, schema, and `%APPDATA%\TripoSpectrumMapper`
identifiers remain readable intentionally so existing projects, language, and
application preferences are not lost during the rename.

The r32.2 release revision advances independently while the public display and
Windows versions remain pinned. r32.2 is a published prerelease with seven
derived demo 3MF outputs. Its exact regression, clean build, packaged and
fresh-extracted self-tests, isolated Japanese/English UI smoke, source/software
stage, checksums, GitHub publication, and unauthenticated redownload verification
passed from frozen commit `aba20685d2fd6987621b2e1e6624f46ea84912a3`.
Published `v0.8beta-r32.1` remains immutable previous evidence.
