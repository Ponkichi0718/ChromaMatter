# ChromaMatter Linux x86_64 technical alpha: build from source

This document applies only to the exact source commit and dependency/source
manifests shipped beside a Linux technical-alpha binary.  It is not a claim
that another commit, another wheel, or another archive has been reviewed.

## Supported reproduction baseline

- Ubuntu 22.04 x86_64 (glibc 2.35)
- CPython 3.13.14
- the exact hashes in `requirements-build-linux-x86_64.lock`
- GNU binutils, `file`, `patchelf`, `realpath`, and the compiler/build tools
  identified by the staged source payloads
- the Japanese font packages listed by `BUILD_LINUX_X86_64.sh`

## Rebuild procedure

1. Verify every source payload against `SOURCE_PAYLOADS.json` and the detached
   checksum file before extracting or importing it.
2. Restore the ChromaMatter Git bundle at the commit recorded in
   `CORRESPONDING_SOURCE_MANIFEST.json`, including every staged submodule or
   external native source listed there.
3. Create a clean CPython 3.13.14 environment. Install only the wheel files
   whose filenames and SHA-256 values match the Linux lock, using
   `--require-hashes --only-binary=:all:`.
4. From the repository root run `BUILD_LINUX_X86_64.sh` with fresh source,
   Python-prefix, and output directories. Do not build in a previously used
   output directory.
5. Preserve the emitted application directory. Run `AUDIT_LINUX_APP.sh`, the
   packaged self-test, native/render self-test, and Japanese/English UI smokes.
6. Regenerate the Linux inventory, component map, SPDX SBOM, and corresponding
   source manifest for those exact bytes. Evidence from an older build is not
   transferable.

The PyInstaller output is a one-folder application. Replacing a native library
must be followed by the relinking/replacement checks in `RELINKING_EN.md` and
by the full build and packaged-runtime validation above.
