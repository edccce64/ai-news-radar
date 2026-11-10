# 测试「触发 GitHub Actions」的请求是否通。用来排查 cron-job.org 点了没反应。
#
#   .\test-dispatch.ps1
#
# 会依次做三件事，每步都把 HTTP 状态码打出来：
#   1. 用 PAT 查仓库（验证 token 有没有权限）
#   2. 用 PAT 查 workflow（验证路径对不对）
#   3. 用 PAT 发 dispatch（真正触发一次日报）
#
# token 从终端输入，不回显、不进命令行、不进历史。

param(
    [string]$Repo = "edccce64/ai-news-radar",
    [string]$Token = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if (-not $Token) {
    $sec = Read-Host "粘贴 GitHub PAT（输入不回显，需 Actions: Read and write）" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    $Token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
if ([string]::IsNullOrWhiteSpace($Token)) {
    Write-Error "token 为空，已取消"
    exit 1
}

$base = "https://api.github.com/repos/$Repo"
$headers = @{
    "Authorization"        = "Bearer $Token"
    "Accept"               = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent"           = "ai-news-radar-dispatch-test"
}

function Invoke-Step {
    param([string]$Name, [string]$Method, [string]$Url, [string]$Body)
    try {
        $args = @{
            Uri = $Url; Method = $Method; Headers = $headers
            SkipHttpErrorCheck = $true; StatusCodeVariable = "code"
        }
        if ($Body) {
            $args["Body"] = $Body
            $args["ContentType"] = "application/json"
        }
        $r = Invoke-RestMethod @args
        $status = $script:code
        $ok = ($status -ge 200 -and $status -lt 300)
        $mark = if ($ok) { "OK  " } else { "失败" }
        Write-Host ("[{0}] {1,-22} HTTP {2}" -f $mark, $Name, $status)
        if (-not $ok) {
            Write-Host ("       返回：{0}" -f ($r | ConvertTo-Json -Compress -Depth 3))
        }
        return $ok
    }
    catch {
        Write-Host ("[失败] {0,-22} {1}" -f $Name, $_.Exception.Message)
        return $false
    }
}

Write-Host ""
Write-Host "仓库：$Repo"
Write-Host ""

$step1 = Invoke-Step -Name "读仓库" -Method GET -Url $base
if (-not $step1) {
    Write-Host ""
    Write-Host "→ token 本身无效，或没有该仓库的访问权限。去 https://github.com/settings/tokens 重新生成。"
    exit 1
}

$step2 = Invoke-Step -Name "读 workflow" -Method GET -Url "$base/actions/workflows/daily.yml"
if (-not $step2) {
    Write-Host ""
    Write-Host "→ token 能读仓库但读不到 workflow，多半是 fine-grained PAT 少了 Actions 权限。"
    exit 1
}

if ($DryRun) {
    Write-Host ""
    Write-Host "前两步都通过，token 可用。-DryRun 跳过真正的触发。"
    exit 0
}

$step3 = Invoke-Step -Name "触发 dispatch" -Method POST `
    -Url "$base/actions/workflows/daily.yml/dispatches" -Body '{"ref":"master"}'

Write-Host ""
if ($step3) {
    Write-Host "→ 触发成功。去 Actions 页面看有没有新的 daily-digest 运行："
    Write-Host "  https://github.com/$Repo/actions/workflows/daily.yml"
    Write-Host ""
    Write-Host "  如果这里成功、cron-job.org 那边还是没反应，那问题 100% 在 cron-job.org 的配置。"
} else {
    Write-Host "→ 触发失败。看上面的状态码："
    Write-Host "   401 = token 无效 / 过期"
    Write-Host "   403 = token 权限不够（需要 Actions: Read and write，且仓库在 Repository access 里）"
    Write-Host "   404 = 仓库名或 workflow 路径写错"
}
