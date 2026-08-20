# ChromaMatter version policy

- Public application name: `ChromaMatter — AI Model Print Studio`
- Public displayed version: `0.8beta`
- Public release revision: `r31`
- Windows string version: `0.8beta`
- Windows numeric version: `0.8.0.0` (numeric resource fields cannot contain `beta`)
- Public executable identity: `ChromaMatter.exe` / `ChromaMatter`
- Public source artifact: `ChromaMatter_0.8beta-r31-ai-model-print-studio_HANDOFF`
- Public software artifact: `ChromaMatter_0.8beta-r31-ai-model-print-studio`
- Detached distribution checksum record after final restage: `SHA256SUMS-r31.txt`
- Do not change any public version string merely for fixes or beta features.
- Advance the version only after an explicit user request.

This pin applies to the window title, self-test/report application identity,
3MF hotfix metadata, documentation, and the release name selected during
packaging. Legacy executable, schema, and `%APPDATA%\TripoSpectrumMapper`
identifiers remain readable intentionally so existing projects, language, and
application preferences are not lost during the rename.

The r31 exact-source regression, clean build, packaged self-test, isolated
Japanese/English UI smoke, and preflight source/software stage, archive,
fresh-extract, and privacy audits are current evidence. Final restage,
Downloads placement, detached checksum, legal, physical, and publication gates
remain separate and pending; r30 artifact evidence must not be reused for r31.
