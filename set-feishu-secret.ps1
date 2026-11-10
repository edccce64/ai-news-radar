# 把飞书「签名校验」的秘钥同时写进本地 .env 和 GitHub Secret。
#
#   .\set-feishu-secret.ps1                    # 自动识别当前仓库
#   .\set-feishu-secret.ps1 -Repo owner/repo   # 指定仓库
#
# 秘钥从终端输入，不回显、不进命令行、不进 shell 历史、不落盘到临时文件。
# 值经 stdin 传给 gh，不出现在进程列表里。
#
# 脚本会自动切到自身所在目录（项目根），从任何路径调用都能工作。

param(
    [string]$Repo = ""
)

$ErrorActionPreference = "Stop"

# 切到脚本所在目录（项目根），这样 .env 与 git 仓库都能找到
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir
try {
    if (-not $Repo) {
        $Repo = (gh repo view --json nameWithOwner -q .nameWithOwner 2>$null)
        if (-not $Repo) {
            Write-Error "定位不到当前仓库，请显式指定：.\set-feishu-secret.ps1 -Repo <owner>/<repo>"
            exit 1
        }
    }
    Write-Host "目标仓库：$Repo"
    Write-Host ""

    $sec = Read-Host "粘贴飞书签名校验秘钥（输入不回显）" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

    if ([string]::IsNullOrWhiteSpace($plain)) {
        Write-Error "秘钥为空，已取消"
        exit 1
    }

    # —— 1. 写本地 .env（必须 UTF-8 无 BOM，python-dotenv 对 BOM 容错差）——
    if (-not (Test-Path ".env")) {
        Write-Error "找不到 .env，请先 copy .env.example .env"
        exit 1
    }
    $enc = New-Object System.Text.UTF8Encoding($false)
    $content = [System.IO.File]::ReadAllText((Resolve-Path ".env"))
    if ($content -match '(?m)^FEISHU_SECRET=.*$') {
        $content = [System.Text.RegularExpressions.Regex]::Replace(
            $content, '(?m)^FEISHU_SECRET=.*$', "FEISHU_SECRET=$plain")
    } else {
        if (-not $content.EndsWith("`n")) { $content += "`n" }
        $content += "FEISHU_SECRET=$plain`n"
    }
    [System.IO.File]::WriteAllText((Resolve-Path ".env"), $content, $enc)
    Write-Host "本地 .env      已写入 FEISHU_SECRET"

    # —— 2. 写 GitHub Secret（值经 stdin，不进命令行/历史）——
    $plain | gh secret set FEISHU_SECRET -R $Repo
    if ($LASTEXITCODE -ne 0) {
        Write-Error "GitHub Secret 设置失败"
        exit 1
    }
    Write-Host "GitHub Secret  已写入 FEISHU_SECRET"

    Write-Host ""
    Write-Host "接下来："
    Write-Host "  1) 飞书群里打开机器人 → 安全设置 → 勾选「签名校验」"
    Write-Host "  2) 本地跑一次验证（会往群里发一条测试消息）："
    Write-Host "       .venv\Scripts\python.exe main.py --test-push"
    Write-Host "  3) 报 19021 就是秘钥没对，回头核对；报成功就完成了"
}
finally {
    Pop-Location
}
