# ChromaMatter · Sorca CM

**From coloured models to real prints — colour editing, mixing and slicing inside Snapmaker Orca.**

[日本語](README_JA.md) · **[Download](https://chromamatter.app/download)** · [Website](https://chromamatter.app/) · [Prints & demos](#prints--demos)

ChromaMatter began as a standalone colour-processing app, then brought its tools into Snapmaker Orca as **Orca with CM**. We now call this integration **Sorca CM** to make its Snapmaker Orca — “Sorca” — foundation clearer. ChromaMatter remains the project name; Sorca CM is the independent development edition based on Snapmaker Orca 2.4.0.

## Download — 20261022 r2

| Windows | macOS | Linux |
| --- | --- | --- |
| **[Download ZIP](https://github.com/Ponkichi0718/ChromaMatter/releases/download/sorca-cm-r2-20261022/Sorca-CM-20261022-r2-Windows-x64.zip)** | **[Download app ZIP](https://github.com/Ponkichi0718/ChromaMatter/releases/download/sorca-cm-r2-20261022/Sorca-CM-20261022-r2-macos-arm64-app.zip)** | **[Download tar.gz](https://github.com/Ponkichi0718/ChromaMatter/releases/download/sorca-cm-r2-20261022/Sorca-CM-20261022-r2-Linux-x86_64.tar.gz)** |
| Windows x64 | Apple Silicon · macOS 15+ | Ubuntu 22.04 · x86_64 |
| `Open-Sorca-CM.cmd` | `Sorca CM.app` | `Start-Sorca-CM.sh` |

[Release notes & checksums](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/sorca-cm-r2-20261022) · [Corresponding source](#source) · [Previous versions](https://chromamatter.app/download#previous-versions)

Extract the complete archive into a new folder. **Mac is ad-hoc signed, without Apple notarization; Intel Macs are not supported.** Linux needs the system libraries listed in the release notes. This is a development release; keep original projects and check the sliced result.

## Prints & demos

Click a photo to open its Reddit post, video and experiment notes.

<table>
  <tr>
    <td width="33%" valign="top" align="center"><a href="https://www.reddit.com/r/snapmaker/comments/1wsehu7/tanjiro_and_a_few_of_my_earlier_prints/"><img src="publication/images/print-collection.jpg" width="280" alt="A collection of physical colour prints, including Tanjiro and a mech bust" /></a><br /><strong>Colour prints</strong><br />Full Spectrum and Core/Shell experiments.<br /><a href="https://www.reddit.com/r/snapmaker/comments/1wsehu7/tanjiro_and_a_few_of_my_earlier_prints/">Tanjiro &amp; earlier prints ↗</a></td>
    <td width="33%" valign="top" align="center"><a href="https://www.reddit.com/r/snapmaker/comments/1ww6efo/a_pumpkin_with_layered_walls_clear_yellow_magenta/"><img src="publication/images/clear-coated-pumpkin.jpg" width="280" alt="A clear-coated pumpkin on the printer bed" /></a><br /><strong>Layered pumpkin</strong><br />Clear → yellow → magenta → black.<br /><a href="https://www.reddit.com/r/snapmaker/comments/1ww6efo/a_pumpkin_with_layered_walls_clear_yellow_magenta/">Four-layer experiment ↗</a></td>
    <td width="33%" valign="top" align="center"><a href="https://www.reddit.com/r/snapmaker/comments/1xasrxa/an_innovation_fund_thankyou_and_a_zinogremonster/"><img src="publication/images/zinogre-rybw.png" width="280" alt="A Zinogre print using red, gold and blue silk PLA plus white" /></a><br /><strong>RYBW with silk PLA</strong><br />Red, gold and blue silk PLA + white.<br /><a href="https://www.reddit.com/r/snapmaker/comments/1xasrxa/an_innovation_fund_thankyou_and_a_zinogremonster/">Zinogre experiment ↗</a></td>
  </tr>
</table>

### Watch the workflow

<table>
  <tr>
    <td width="33%" valign="top" align="center"><a href="https://www.reddit.com/r/snapmaker/comments/1x4lkq4/orca_with_cm_flat_color_painting_and_cutting/"><img src="publication/images/painting-cutting-demo.png" width="240" alt="The dev3 R8 painting and cutting feature overview" /><br /><strong>Paint &amp; cut</strong><br />dev3 R8 overview ↗</a></td>
    <td width="33%" valign="top" align="center"><a href="https://www.reddit.com/r/snapmaker/comments/1whzk5l/cmy_coreshell_experiment_on_the_u1_using_a_black/"><img src="publication/images/cmy-core-shell-demo.png" width="240" alt="A CMY mech model with black Core/Shell shading" /><br /><strong>CMY + Core/Shell</strong><br />Black-core shading ↗</a></td>
    <td width="33%" valign="top" align="center"><a href="https://www.reddit.com/r/snapmaker/comments/1wk7kab/a_little_coreshell_experiment_color_inside_a/"><img src="publication/images/clear-shell-demo.png" width="240" alt="A striped colour sample inside a clear shell" /><br /><strong>Clear shell + colour</strong><br />A small material experiment ↗</a></td>
  </tr>
</table>

These are examples from different development stages, not print-validation results for r2. [More demos on the website](https://chromamatter.app/#demos). An illustrated manual is in preparation.

## What you can do

| Workflow | Tools |
| --- | --- |
| **Import & choose colours** | Coloured GLB and vertex-colour OBJ, Flat Color, Full Spectrum and CMY. Specify four filaments from products or simple colour swatches; use RYBW templates. |
| **Edit paint & shading** | 2D/3D brushes, fill, local colour replacement, overpaint allow/block filters, shape-line painting, shading and manga-style filters. |
| **Plan your materials** | Filament library, HEX/TD information where available, colour-match values and Top 3 suggestions. Up to 16 Flat Color candidates for editing and part planning. |
| **Arrange material layers** | Core/Shell and up to four layers. Put several filaments in one layer for model-colour-based mixing. |
| **Prepare parts** | Colour-preserving planar cuts, position/angle controls, protection brushes, connectors and bridges. |
| **Bring mixed 3MF to U1** | Convert supported Bambu fixed-mixture projects while retaining their plate grouping, paint and recipes. Existing CM projects follow their normal settings-restoration route. |

**Beta:** transparent coat, colour lithophane, shape-line cutting, recess-colour suggestions and white-reflection suppression. **Specified four-filament import is a regular feature.**

U1 still uses **four physical filaments per plate**. Palette candidates and mixed colours do not add printer tools. A part using too many physical materials needs adjustment; automatic four-colour regrouping is not promised.

<details>
<summary><strong>Setup, compatibility and verification</strong></summary>

- Keep originals, use a new extraction folder and save edited projects under new names. Existing CM editions may share settings; close other editions before switching and back up your settings.
- Windows web features require Microsoft Edge WebView2 Runtime. Linux targets Ubuntu 22.04 / glibc 2.35 and requires the documented GTK/WebKit/GStreamer/OpenGL libraries; it is not an AppImage.
- r2 includes multi-colour-number selection for transparent windows and a 0.4 mm preference for new U1 setups. Saved nozzle selections are preserved.
- Build/package and targeted headless checks passed. The Mac build completed on October 23. These checks do not establish GUI, full-model slicing or physical-print correctness for this release.
- Colour previews and TD-based estimates are not optically calibrated. Cutting and protection depend on geometry and do not understand named body parts; complex models can still fail.
- CM-specific project settings need a compatible CM build. Stock Orca and older CM versions may not reproduce them.

</details>

## Snapmaker U1 Innovation Fund Award

**ChromaMatter -AI Model Print Studio**, by **Ponkichi0718**, received **Third Prize (US$1,500)** in the final results of **Snapmaker U1 Innovation Fund Phase 1 (2026)**.

[Official results](https://www.snapmaker.com/innovation-fund) · [Official announcement](https://forum.snapmaker.com/t/built-by-makers-meet-the-20-snapmaker-u1-innovation-fund-winners/43667/1)

The original submission was a standalone app; development now continues as **Sorca CM**. The award recognizes the submitted project, not validation or a guarantee of the current development builds.

## Source

[Windows source ZIP](https://github.com/Ponkichi0718/ChromaMatter/releases/download/sorca-cm-r2-20261022/Sorca-CM-20261022-r2-Windows-source.zip) · [Linux source tar.gz](https://github.com/Ponkichi0718/ChromaMatter/releases/download/sorca-cm-r2-20261022/Sorca-CM-20261022-r2-Linux-source.tar.gz) · [macOS source & checksums](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/sorca-cm-r2-mac-inputs-20261022)

Use the **release-specific corresponding source** for Orca builds; the repository’s older standalone source tree and version records remain historical. The [r2 release](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/sorca-cm-r2-20261022) links the build information. Previous [dev3-R8](https://github.com/Ponkichi0718/ChromaMatter/releases/tag/cm-orca-dev3-r8-20261013) and [other releases](https://github.com/Ponkichi0718/ChromaMatter/releases) remain available.

[License](LICENSE) · [Third-party notices](licenses/) · [Security](SECURITY.md)
