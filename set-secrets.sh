#!/usr/bin/env bash
# 把 .env 的值写入 GitHub Secrets。只需跑一次。
# 值经 stdin 传给 gh，不出现在命令行参数 / shell 历史 / 日志里。
#
#   ./set-secrets.sh                 # 自动识别当前仓库
#   ./set-secrets.sh <owner>/<repo>  # 指定仓库
#
# 行为与 set-secrets.ps1 一致。

set -euo pipefail

REPO="${1:-}"
if [ -z "$REPO" ]; then
    # 自动识别：必须在 git 仓库里跑
    REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
    if [ -z "$REPO" ]; then
        echo "定位不到当前仓库，请显式指定：./set-secrets.sh <owner>/<repo>" >&2
        exit 1
    fi
    echo "目标仓库：$REPO"
fi

KEYS="LLM_PROVIDER DEEPSEEK_API_KEY MIMO_API_KEY MIMO_BASE_URL MIMO_MODEL FEISHU_WEBHOOK_URL FEISHU_SECRET"

if [ ! -f .env ]; then
    echo "找不到 .env" >&2
    exit 1
fi

# 取 KEY=VALUE 里的值，忽略注释与空行，去掉 CR 与首尾空白。
value_of() {
    awk -v key="$1" '
        {
            line = $0
            sub(/\r$/, "", line)
            if (match(line, "^[ \t]*" key "[ \t]*=")) {
                v = substr(line, RLENGTH + 1)
                sub(/^[ \t]+/, "", v)
                sub(/[ \t]+$/, "", v)
                print v
                exit
            }
        }
    ' .env
}

for k in $KEYS; do
    v="$(value_of "$k")"
    if [ -z "$v" ]; then
        printf '%-22s 跳过（.env 里为空）\n' "$k"
        continue
    fi
    printf '%s' "$v" | gh secret set "$k" -R "$REPO"
    printf '%-22s 已设置\n' "$k"
done

echo
echo "完成。核对：gh secret list -R $REPO"
