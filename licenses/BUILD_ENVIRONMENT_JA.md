# Windows版の正確なビルド環境

バイナリリリースでは対応ソースアーカイブを正しい入力とします。固定した依存
関係、スクリプト、構成表、ソースを一組で使用し、新しいcheckoutを古い
バイナリの対応ソースとして扱わないでください。

## 固定する基本環境

- Windows x64
- Python 3.13
- PyInstaller 6.20.0、one-folder形式、UPX無効
- `source/fixed_app/requirements-build.txt`の固定バージョン

## ビルドとテスト

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\BOOTSTRAP_WINDOWS.ps1
powershell.exe -ExecutionPolicy Bypass -File .\BUILD_AND_TEST.ps1 `
  -RuntimeRoot .\.venv `
  -Build `
  -BuildOutputRoot C:\ChromaMatterBuild
```

`BUILD_AND_TEST.ps1`はPython 3.13確認、テスト、固定specでのビルド、必須
ランタイム資材、パッケージ版self-testを確認します。

## バイナリ配布ステージ

`BUILD_AND_TEST.ps1`は正確なone-folder出力から
`compliance/BINARY_COMPONENT_MAP.json`と`compliance/SBOM.cdx.json`を生成
します。配布ステージは両方と正確な対応ソースのHTTPS URLを必須にします。
ネイティブファイルの対応漏れ、未入力、プレースホルダー、EXEハッシュ不一致が
あれば停止します。

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\tooling\stage_software_package.ps1 `
  -BuiltAppRoot C:\ChromaMatterBuild\dist\ChromaMatter `
  -BinaryComponentMapPath C:\release\BINARY_COMPONENT_MAP.json `
  -SbomPath C:\release\SBOM.cdx.json `
  -CorrespondingSourceUrl https://github.com/OWNER/REPO/releases/download/TAG/SOURCE.zip
```

バイナリと正確なソースを同時に公開してください。ローカルでの成功は、そのURL
へのアップロードや公開到達性までは証明しません。
