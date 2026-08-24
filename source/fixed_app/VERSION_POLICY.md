# ChromaMatter version policy

- Public application name: `ChromaMatter — AI Model Print Studio`
- Public displayed version: `0.8beta`
- Current local release-candidate revision: `r32.2`
- Windows string version: `0.8beta`
- Windows numeric version: `0.8.0.0` (numeric resource fields cannot contain `beta`)
- Public executable identity: `ChromaMatter.exe` / `ChromaMatter`
- Planned public source artifact: `ChromaMatter-0.8beta-r32.2-source-public-20260824`
- Planned public software artifact: `ChromaMatter-0.8beta-r32.2-win64`
- Planned detached distribution checksum record: `SHA256SUMS-r32.2.txt`
- Do not change any public version string merely for fixes or beta features.
- Advance the version only after an explicit user request.

This pin applies to the window title, self-test/report application identity,
3MF hotfix metadata, documentation, and the release name selected during
packaging. Legacy executable, schema, and `%APPDATA%\TripoSpectrumMapper`
identifiers remain readable intentionally so existing projects, language, and
application preferences are not lost during the rename.

The r32.2 release revision advances independently while the public display and
Windows versions remain pinned. r32.2 is a local release candidate that adds
seven derived demo 3MF outputs to the planned Windows package. Its exact
regression, clean build, packaged self-test, isolated Japanese/English UI
smoke, source/software stage, fresh extraction, checksum, and GitHub
publication gates are pending until they are measured from frozen r32.2
source. Published `v0.8beta-r32.1` remains immutable previous evidence and
must not be presented as validation of r32.2.
