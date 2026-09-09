# 把独立进程入口编译成 .exe（Nuitka，Windows）。
# 注意：Nuitka 在含中文的路径下 MSVC 链接会失败(LNK1104)，故先编译到纯 ASCII 临时目录，再拷回 .\bin。
param(
    [switch]$All   # 含 ingestion_worker（捆绑 numpy/fastembed，体积较大、较耗时）
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$AsciiDir = Join-Path $env:TEMP "nuitka_build"
if (Test-Path $AsciiDir) { Remove-Item -LiteralPath $AsciiDir -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force -Path $AsciiDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Root "bin") | Out-Null

function Invoke-Nuitka([string]$Entry, [string]$Name) {
    $cmdline = 'call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1 && set PATH=' + (Join-Path $Root ".venv\Scripts") + ';%PATH% && "' + $VenvPython + '" -m nuitka --standalone --onefile --assume-yes-for-downloads --output-dir=' + $AsciiDir + ' --output-filename=' + $Name + '.exe ' + $Entry
    cmd /c $cmdline
    if (-not (Test-Path (Join-Path $AsciiDir "$Name.exe"))) { throw "$Name build failed" }
    Copy-Item -LiteralPath (Join-Path $AsciiDir "$Name.exe") -Destination (Join-Path $Root "bin\$Name.exe") -Force
    Write-Host "OK -> bin\$Name.exe"
}

Push-Location $Root
try {
    Invoke-Nuitka "modules-src\mcp-servers\mcp_servers\__main__.py" "mcp_servers"
    if ($All) { Invoke-Nuitka "modules-src\ingestion\ingestion\__main__.py" "ingestion_worker" }
} finally { Pop-Location }
