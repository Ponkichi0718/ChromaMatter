# ChromaMatter Linux x86_64 technical alpha: native replacement and relinking

ChromaMatter is distributed as a PyInstaller one-folder application. Native
libraries remain separate ELF files below `_internal`; they are not converted
into a single statically linked executable. This layout is intended to permit
inspection and replacement, but replacement is not considered validated until
the following procedure succeeds for the exact application bytes.

1. Make a recoverable copy of the application directory.
2. Locate the library in `BINARY_COMPONENT_MAP.json`. Do not replace a file
   whose owner or corresponding source is unresolved.
3. Build a compatible x86_64 shared library from the staged corresponding
   source and record the build commands, compiler, configuration, and SHA-256.
4. Replace only the mapped shared object. Preserve the expected SONAME or the
   package-relative symlink chain. Do not introduce an absolute RPATH/RUNPATH.
5. Run `readelf -h`, `readelf -d`, `patchelf --print-rpath`, and `ldd` with the
   application's `_internal` directory as `LD_LIBRARY_PATH`. All dependencies
   must resolve only inside the application or normal system library roots.
6. Run the packaged self-test, Linux native/render self-test, and both UI
   smokes. Exercise the feature that loads the replaced library.
7. Regenerate the complete inventory and verify that only the intended files,
   symlinks, and hashes changed.

Qt, GEOS, GMP, libgomp, Tcl/Tk, and any LGPL-covered library must remain
replaceable in practice. If its owner, source, SONAME, symlink chain, or test
procedure is missing, the Linux distribution gate must remain blocked.
