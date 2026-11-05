param([switch]$Release)
$ErrorActionPreference = 'Stop'
$buildOriginalPath = $env:PATH
# Resolve Windows ICU from Windows, not unrelated tools such as Poppler on PATH.
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
Push-Location $PSScriptRoot
try {
    $bundleArgs = if ($Release) { @('--onedir','--distpath','.build/release-runtime') } else { @('--onefile','--distpath','.') }
    & '.venv/Scripts/python.exe' -m PyInstaller --noconfirm --windowed @bundleArgs --optimize 2 --version-file "$PSScriptRoot/version_info.txt" --name 'Ocean Foundry' --workpath .build/work --specpath .build --add-data "$PSScriptRoot/USER_GUIDE.md;." --add-data "$PSScriptRoot/USER_GUIDE.zh-CN.md;." --add-data "$PSScriptRoot/zh_CN.json;." --add-data "$PSScriptRoot/default_settings.json;." --add-data "$PSScriptRoot/.venv/Lib/site-packages/PySide6/translations/qtbase_zh_CN.qm;translations" --add-data "$PSScriptRoot/palette_26_1_2.json;." --add-data "$PSScriptRoot/glass_26_1_2.json;." --add-data "$PSScriptRoot/lava_normals;lava_normals" --add-data "$PSScriptRoot/ocean_normals;ocean_normals" --exclude-module matplotlib --exclude-module scipy.tests --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtWebEngineQuick launcher.py
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
} finally { $env:PATH = $buildOriginalPath; Pop-Location }

