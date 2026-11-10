# 安全策略

## 报告漏洞

**请不要用公开 Issue 报告安全问题。** 用 GitHub 的 Private vulnerability reporting（仓库页 → Security → Report a vulnerability），或直接联系维护者。

已公开仓库默认开启 Private vulnerability reporting；若该入口不可用，请开一个只描述影响、不含利用细节的 Issue 私信维护者。

## 什么算漏洞

- **密钥泄漏**：`.env`、Webhook URL、API key、GitHub token 进入代码、commit 或日志
- **日志注入凭据**：错误信息、异常堆栈、Actions 日志里出现可用的凭据
- **任意代码执行**：未经授权能在 Actions runner 或本地执行代码
- **越权访问**：能读写他人仓库的 Secrets 或状态库

## 什么不算漏洞

- 源站自身的可用性问题（RSSHub 镜像挂了、微信桥失效）
- 配置错误导致自己推送失败
- 飞书自定义机器人的已知限制（20KB 请求体、限频）—— 代码已做拆卡与间隔

## 响应

- 3 个工作日内确认收到
- 7 个工作日内给出修复或缓解方案
- 修复发布后会在 Release notes 里说明受影响版本

## 使用者自查

- `.env` **必须**在 `.gitignore` 里（仓库已配好）
- **不要**把 `.env`、`.env.*`、webhook 截图贴进 Issue 或聊天
- 飞书 Webhook 地址等同密码 —— 泄漏后立刻在飞书机器人后台重置
- API key 泄漏后立刻去对应平台重置
- 建议开启飞书机器人的**签名校验**（把 Secret 填进 `FEISHU_SECRET`）
