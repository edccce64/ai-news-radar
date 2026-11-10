# 参与贡献

感谢参与。这个项目很小，改动前请先读 [README](README.md) 的「关键取舍」一节 —— 里面的结论都是踩过坑换来的，别凭直觉推翻。

## 开发环境

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

需要 Python 3.10+。

## 跑测试

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

只跑测试不推送、不写库：

```powershell
.venv\Scripts\python.exe main.py --dry-run
```

提交前两步都要跑。

## 代码约定

- **扁平结构，单入口 `main.py`。** 不新建 `src/`、`utils.py`、`models.py`。
- **非密钥配置进 `config.py`，密钥只进 `.env`。** 密钥永远不进代码、不进 commit、不进日志。
- **日志用 `print`**，前缀沿用 `[INFO]` / `[OK]` / `[警告]` / `[跳过]`。
- **一个函数只做一件事**，不为只用一次的代码建抽象层。
- **错误信息里不许出现密钥或 URL。** `requests` 的异常字符串自带完整 URL，直接抛会把凭据打进日志 —— 参考 `feishu._post` 的写法。
- **注释写「为什么」，不写「做了什么」。** 尤其是踩坑原因，改代码的人需要知道。

## 提交信息

沿用现有风格：

```
feat: 新增 GitHub Trending 工具源
fix: 飞书 webhook 出现在错误信息里
docs: README 补第三方条款
chore: 更新 requirements
```

## 提 Issue 前先想清楚

- 源挂了（RSS 503、镜像限流）—— 先看是不是已知问题，README「常见问题」有列表。
- 想要新功能 —— 先说清场景，别只说「加个 XX」。
- **不要在公开 issue 里贴 webhook URL、API key、`.env` 内容。** 贴了等于公开凭据，请立刻去平台重置。

## 改数据源时

加源之前先确认：是不是已经有同类的源覆盖了？RSS 源会不会限流？条目有没有摘要（没有摘要的条目只能靠模型背景知识，容易产出空洞分析）？

在 `config.py` 的 `RSS_FEEDS` / `TOOL_FEEDS` 里加，并在 `README.md` 的「数据源」表里补一行。
