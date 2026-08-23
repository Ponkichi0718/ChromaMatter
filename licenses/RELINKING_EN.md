# Replacing LGPL libraries in the Windows package

ChromaMatter is shipped as a PyInstaller **one-folder** package. Qt and GEOS
remain separate DLLs; they are not embedded into `ChromaMatter.exe`.
`BINARY_COMPONENT_MAP.json` is authoritative for the exact paths in a given
release.

## Qt 5.15.2

The PyMeshLab wheel supplies Qt DLLs below `_internal/pymeshlab/`, including
`Qt5Core.dll`, `Qt5Gui.dll`, `Qt5Network.dll`, `Qt5OpenGL.dll`,
`Qt5Svg.dll`, `Qt5Widgets.dll`, and `Qt5Xml.dll`, plus plugins and
translations. This distribution uses Qt's LGPL-3.0 option.

1. Build an ABI-compatible Windows x64 Qt 5.15.2 set from the matching source
   in the corresponding-source archive.
2. Close ChromaMatter and back up the extracted package.
3. Replace the complete mutually compatible Qt DLL set and affected plugins,
   keeping the names and layout recorded in the component map.
4. Run `ChromaMatter.exe --self-test`, then test GLB loading, mesh repair,
   and 3MF export with non-private data.

Do not mix DLLs or plugins built with incompatible Qt options or ABIs.

## GEOS 3.13.1

The Shapely wheel supplies GEOS and GEOS C API DLLs below
`_internal/Shapely.libs/`. This distribution uses GEOS under
LGPL-2.1-or-later.

1. Build ABI-compatible Windows x64 GEOS 3.13.1 and GEOS C API DLLs.
2. Close ChromaMatter, back up the package, and replace the paired DLLs at
   the exact component-map paths while retaining their expected filenames.
3. Run `ChromaMatter.exe --self-test` and exercise Shapely/Trimesh paths.

The package SHA-256 manifest describes the unmodified release. Replacing an
LGPL DLL intentionally changes those hashes; the manifest is an integrity
record, not an execution lock. ABI-incompatible replacements may fail to load,
and no warranty is made for modified combinations.
