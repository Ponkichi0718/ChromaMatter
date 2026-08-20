# Privacy and private-test data

ChromaMatter — AI Model Print Studio processes models locally. The application does not intentionally upload OBJ, GLB, image, project, or 3MF data to a project-operated server.

The following existing development and validation materials are private by default and must remain outside the public repository, source archive, binary archive, issue attachments, and downloadable samples:

- real OBJ/STL models and source images;
- generated 3MF files and slicer projects;
- screenshots or diagnostics derived from a real model;
- videos and their editable source files;
- local validation reports containing a filename, absolute path, model identifier, hash, vertex/face count, or diagnostic coordinate;
- temporary geometry such as fTetWild tracked-surface files.

Project and preference files may contain paths selected by the local user. Before sharing one, open it as text and remove or replace those paths. A public issue should use the synthetic sample or a newly created minimal fixture, not a private production model.

The optional owned-filament inventory is stored locally at `%APPDATA%\TripoSpectrumMapper\owned_filaments.json`. It can contain manufacturer, series, colour name, HEX, finish, source identifier, and source URL snapshots for products the user marked as owned. It is not uploaded by the application and is not included by the public staging or build scripts. Treat it as personal inventory data and remove it before sharing a settings archive. A project may retain the four applied product snapshots needed to reproduce spool order; inspect that metadata before publishing the project.

Video demonstrations may show a private model without making the underlying file downloadable only when the presenter has the necessary rights to the image, design, generated model, music, and other visible content. Crop or blur local filenames, account information, model identifiers, and absolute paths.

A downloadable demonstration model is a separate class of asset, not an exception granted to an existing private model. It must be generated specifically for public demonstration from fully original, generic prompts and pass the documented rights gate before it enters the public staging allowlist. The record must identify the generation service and plan, date, model ID, exact prompt and seed, rights to any input image, third-party-IP review, redistribution permission, applicable licence, required attribution, and SHA-256 of every distributed image, OBJ, and 3MF. A service-imposed licence such as CC BY 4.0 must be retained and must not be replaced with CC0. No generated public demonstration asset is currently included.

The public staging script uses an allowlist and rejects common personal-path and private-model markers. Passing that scan is a safeguard, not a guarantee; review the staged tree manually before publication.
