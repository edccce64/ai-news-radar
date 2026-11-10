# 把 .env 的值写入 GitHub Secrets。只需跑一次。
# 值经 stdin 传给 gh，不出现在命令行参数 / shell 历史 / 日志里。
#
#   .\set-secrets.ps1                    # 自动识别当前仓库
#   .\set-secrets.ps1 -Repo owner/repo   # 指定仓库

param(
    [string]$Repo = ""
)

$ErrorActionPreference = "Stop"

if (-not $Repo) {
    # 自动识别：必须在 git 仓库里跑
    $Repo = (gh repo view --json nameWithOwner -q .nameWithOwner 2>$null)
    if (-not $Repo) {
        Write-Error "定位不到当前仓库，请显式指定：.\set-secrets.ps1 -Repo <owner>/<repo>"
        exit 1
    }
    Write-Host "目标仓库：$Repo"
}

$keys = @(
    "LLM_PROVIDER",
    "DEEPSEEK_API_KEY",
    "MIMO_API_KEY",
    "MIMO_BASE_URL",
    "MIMO_MODEL",
    "FEISHU_WEBHOOK_URL",
    "FEISHU_SECRET"
)

if (-not (Test-Path ".env")) {
    Write-Error "找不到 .env"
    exit 1
}

# 解析 KEY=VALUE，忽略注释与空行
$map = @{}
foreach ($line in (Get-Content ".env" -Encoding UTF8)) {
    if ($line -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$') {
        $map[$Matches[1]] = $Matches[2].Trim()
    }
}

foreach ($k in $keys) {
    $v = $map[$k]
    if ([string]::IsNullOrWhiteSpace($v)) {
        Write-Host ("{0,-22} 跳过（.env 里为空）" -f $k)
        continue
    }
    $v | gh secret set $k -R $Repo
    if ($LASTEXITCODE -ne 0) {
        Write-Error "$k 设置失败"
        exit 1
    }
    Write-Host ("{0,-22} 已设置" -f $k)
}

Write-Host ""
Write-Host "完成。可用 gh secret list -R $Repo 核对（只显示名字，不显示值）"
