# Changelog

本文件记录 notable 变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 修复

- **评分结果带说明文字时整天不推送**：`llm._extract_json` 先找 `{`，会把 `[{"id":1},…]`
  抠成对象或半截数组，`_score_map` 判非法后重试两次仍失败，直接放弃当天推送。
  现在数组优先，并从靠后的左括号往回试。
- **开了签名校验后失败告警发不出去**：`daily.yml` 的告警原先是裸 `curl`，不带
  `timestamp` 与 `sign`，飞书返回 19021。改用 `tools/notify_failure.py`，与正式推送同一套签名。
- **安静日连发三次「今日无重要更新」**：空通知不写库，三个定时点都拦不住。
  新增 `empty_notices` 表，空通知每天只发一次，且不锁住当天的真实推送。

### 变更

- 单测从 43 条增加到 52 条，覆盖数组解析、空通知去重与告警签名一致性。

## [1.0.0] - 2026-11-10

### 修复

- **分区拆到两张卡导致标题重复**：原实现把所有区块混排后按 18 KB 一刀切，一个区被切在中间时，
  会变成「卡片 1 末尾一个区标题 + 1 条」+「卡片 2 又一个同名区标题 + 4 条」，读者误以为重复推送。
  现在**按区各自组卡**：一张卡只含一个区，续卡标题带「（续）」，多卡标题带 `(1/2)` 序号。
- **飞书 webhook 泄漏**：`feishu._post` 不再用 `raise_for_status()`。`requests` 的异常字符串自带完整 URL，
  飞书接口报错时会把 webhook token 打进终端、Actions 日志和排错聊天记录。现在错误信息只含异常类型名、
  HTTP 状态码和响应体。
- **LLM 异常泄漏凭据**：新增 `llm._redact()`，打印异常前抹掉 API key、secret 和内嵌凭据的 `MIMO_BASE_URL`。
- **鉴权失败白等**：LLM 返回 401/403 时不再重试 3 次，直接报错并提示检查 API Key。
- **日期不一致**：卡片标题改用北京自然日（`store.today_bj()`），此前用 UTC，跨日边界会差一天。
- **空条目互吞**：`_exact_dedup` 不再把空 link/title 当作「同一条」。
- **整轮抓取崩溃**：`api_fetcher` 的响应 JSON 解析纳入 `try`，对端返回非 JSON（如维护页）时跳过该源而非崩掉。

### 新增

- `set-secrets.sh`：`set-secrets.ps1` 的 Linux / macOS 版本，行为一致。
- `requirements-dev.txt`：固定 ruff 版本，本地与 CI 共用同一份。
- `tests/test_core.py`：43 个单测（标准库 unittest），覆盖判重去环、分区拆卡、字段截断、异常脱敏、签名与限流。
- `.github/workflows/tests.yml`：push 到 `master` 自动跑单测。
- **GitHub Pages 落地页**：<https://edccce64.github.io/ai-news-radar/>，由 `docs/index.html` 生成，
  `pages.yml` 自动部署。
- **卡片效果截图** `docs/screenshot.png`：由真实推送数据 + 真实 LLM 加工结果渲染，
  `tools/render_preview.py` 可复现（把 `docs/preview.json` 渲染成 `docs/preview.html`）。
- `LICENSE`（MIT）、`CONTRIBUTING.md`、`SECURITY.md`、Issue 模板、PR 模板、`.editorconfig`、`.gitattributes`。
- `pyproject.toml`：ruff 静态检查与格式化规则（行宽 100、目标 py310）。

### 变更

- 卡片字段按上限截断：单条异常超长会顶破 18 KB 拆卡线，而拆卡救不了「单条本身超限」。
- `set-secrets.ps1` 改为参数化并自动识别当前仓库，不再硬编码仓库名。
- `.gitignore` 补 `.env.*`、SQLite 侧文件、日志、OS/编辑器文件、`.pi/`。
- Actions 的 action 固定到 commit SHA，runner 固定 `ubuntu-24.04`，回写状态库改用 `git add -A data/`。
- CI 增加 `lint` job，跑 `ruff check` 与 `ruff format --check`，格式不再靠人工坚持。
- README 补齐 Linux / macOS 的安装、密钥配置、运行与开发命令。
