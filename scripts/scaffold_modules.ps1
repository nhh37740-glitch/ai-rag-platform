param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"

$modules = @(
    @{ id = "rag-core";      pkg = "rag_core";      delivery = "mypyc"   },
    @{ id = "memory";        pkg = "memory";        delivery = "mypyc"   },
    @{ id = "llm-gateway";   pkg = "llm_gateway";   delivery = "mypyc"   },
    @{ id = "tool-runtime";  pkg = "tool_runtime";  delivery = "mypyc"   },
    @{ id = "mcp-gateway";   pkg = "mcp_gateway";   delivery = "mypyc"   },
    @{ id = "skill-runtime"; pkg = "skill_runtime"; delivery = "mypyc"   },
    @{ id = "agent-runtime"; pkg = "agent_runtime"; delivery = "mypyc"   },
    @{ id = "observability"; pkg = "observability"; delivery = "mypyc"   },
    @{ id = "evaluation";    pkg = "evaluation";    delivery = "mypyc"   },
    @{ id = "ingestion";     pkg = "ingestion";     delivery = "mypyc + worker" },
    @{ id = "mcp-servers";   pkg = "mcp_servers";   delivery = "nuitka-exe" }
)

$contractsDir  = Join-Path $Root "contracts"
$modulesSrcDir = Join-Path $Root "modules-src"
$artifactsDir  = Join-Path $Root "artifacts"
$registryPath  = Join-Path $Root "registry.json"

$registry = Get-Content $registryPath -Raw | ConvertFrom-Json

foreach ($m in $modules) {
    $id     = $m.id
    $pkg    = $m.pkg
    $repo   = Join-Path $modulesSrcDir $id
    $srcDir = Join-Path $repo ("src/" + $pkg)
    $testsDir = Join-Path $repo "tests"

    New-Item -ItemType Directory -Force -Path $repo | Out-Null
    New-Item -ItemType Directory -Force -Path $srcDir | Out-Null
    New-Item -ItemType Directory -Force -Path $testsDir | Out-Null

    $interfacesRaw = Get-Content (Join-Path $contractsDir "INTERFACES.md") -Raw
    $sectionKey = $id -replace "-", "_"
    if ($id -eq "mcp-servers") { $sectionKey = "mcp_servers" }
    $span = [regex]::Match($interfacesRaw, "(?ms)^## $([regex]::Escape($sectionKey))\b.*?(?=^## |\z)")
    $section = if ($span.Success) { $span.Value.Trim() } else { "## $sectionKey`n`n(interface TBD - see contracts/INTERFACES.md)" }

    $schemaRaw = Get-Content (Join-Path $contractsDir "API_SCHEMA.json") -Raw | ConvertFrom-Json
    $sub = [ordered]@{
        format       = 2
        context      = $schemaRaw.context
        shared_types = $schemaRaw.shared_types
        rules        = $schemaRaw.rules
        module       = $schemaRaw.modules.$id
    }
    $subJson = $sub | ConvertTo-Json -Depth 20

    Set-Content -Path (Join-Path $repo "VERSION")         -Value "0.0.0" -NoNewline
    Set-Content -Path (Join-Path $repo "INTERFACE.md")    -Value "# $id - 接口契约`n`n$section`n"
    Set-Content -Path (Join-Path $repo "API_SCHEMA.json") -Value $subJson -Encoding UTF8
    Set-Content -Path (Join-Path $repo "CHANGELOG.md")    -Value "# Changelog`n`n## [0.0.0]`n- 初始化版本。`n"
    Set-Content -Path (Join-Path $repo "README.md")       -Value ("# $id`n`n$($m.delivery) 交付。`n`n对应契约见本仓库 \`INTERFACE.md\` / \`API_SCHEMA.json\`；任务书见 \`contracts/INTERFACES.md\`。`n`n**只允许改动本仓库，不得修改 \`contracts/\`、其他模块或 \`docs/PLAN.md\`。**`n")
    Set-Content -Path (Join-Path $repo "src\README.md")   -Value "Package: $pkg`n"
    Set-Content -Path (Join-Path $repo "tests\__init__.py") -Value ""
    Set-Content -Path (Join-Path $repo "tests\test_smoke.py") -Value "import unittest`n`nclass Smoke(unittest.TestCase):`n    def test_import(self):`n        import $pkg`n        self.assertTrue(hasattr($pkg, '__version__'))`n`nif __name__ == '__main__':`n    unittest.main()`n"

    if ($m.delivery -eq "nuitka-exe") {
        Set-Content -Path (Join-Path $srcDir "__main__.py") -Value "from . import run_stdio`n`nif __name__ == '__main__':`n    raise SystemExit(run_stdio())`n"
        Set-Content -Path (Join-Path $repo "pyproject.toml") -Value "[project]`nname = '$pkg'`nversion = '0.0.0'`nrequires-python = '>=3.11'`n`n[tool.nuitka]`nstandalone = true`n"
    } else {
        Set-Content -Path (Join-Path $srcDir "__init__.py") -Value "from __future__ import annotations`n__version__ = '0.0.0'`n`nraise NotImplementedError('${id}: implementation pending in modules-src')`n"
        Set-Content -Path (Join-Path $repo "pyproject.toml") -Value "[project]`nname = '$pkg'`nversion = '0.0.0'`nrequires-python = '>=3.11'`n`n[tool.mypyc]`npackage = '$pkg'`n"
    }

    $artNs = Join-Path $artifactsDir $id
    $verNs = Join-Path $artNs "0.0.0"
    New-Item -ItemType Directory -Force -Path $verNs | Out-Null
    New-Item -ItemType File -Force -Path (Join-Path $verNs ".gitkeep") | Out-Null

    if (-not $registry.modules.PSObject.Properties.Name -contains $id) {
        $registry.modules | Add-Member -NotePropertyName $id -NotePropertyValue ([pscustomobject]@{
            version    = "0.0.0"
            checksum   = ""
            status     = "draft"
            delivery   = $m.delivery
            updated_at = (Get-Date).ToString("yyyy-MM-dd")
        })
    }

    Push-Location $repo
    if (-not (Test-Path ".git")) {
        git init -q -b main
        git add -A
        git -c user.email="codex-local@example.com" -c user.name="codex" commit -q -m "chore: scaffold $id contract-first skeleton"
    }
    Pop-Location

    Write-Output ("scaffolded modules-src/$id")
}

$registry | ConvertTo-Json -Depth 20 | Set-Content -Path $registryPath -Encoding UTF8
Write-Output ("registry.json updated (" + $registry.modules.PSObject.Properties.Count + " modules)")
