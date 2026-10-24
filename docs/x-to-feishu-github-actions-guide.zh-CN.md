# 不买服务器：用 GitHub Actions 监控 X 动态并推送到飞书

> 目标：监控 X（原 Twitter）账号 `@YOUR_X_USERNAME`。只要有新帖子，就自动把内容和原文链接发到飞书群。整个方案没有常驻电脑、没有云服务器；GitHub Actions 每 15 分钟运行一次短任务。

本文对应的完整可运行代码在本仓库。复制这个仓库后，按下面的步骤配置即可复现。

> 模板使用占位符 `YOUR_X_USERNAME`。运行前请在 `.github/workflows/x-monitor.yml` 中将 `X_ACCOUNT` 和 `RSS_URL` 里的两处占位符替换为要监控的账号名，不要带 `@`。

## 1. 最终效果

完成配置后，飞书群会收到一张卡片，包含：

- `@YOUR_X_USERNAME` 的帖子正文。
- “查看原文”按钮，点击后跳转 X。
- 只发送新帖子，不会反复发送同一条。

首次启动时，程序只记住当前已有的帖子，不会把历史动态一次性刷到飞书群。

## 2. 这套方案是怎么工作的

下面是一次检查的完整流程：

```text
GitHub 的定时器
        |
        v
GitHub Actions 临时运行一台 Ubuntu 机器
        |
        v
启动 RSSHub Docker 容器，并从 GitHub Secret 读取 X 认证信息
        |
        v
RSSHub 把 X 动态转换为 RSS
        |
        v
Python 读取 RSS，和 state.json 中的已读 ID 比较
        |
        +--> 没有新帖子：正常结束
        |
        +--> 有新帖子：发送飞书卡片，更新 state.json
                                      |
                                      v
                         GitHub Actions 自动提交 state.json
```

关键点是：每次任务完成后，临时机器和 RSSHub 容器都会消失；只有 `state.json` 被提交回仓库，所以下一次任务仍然知道哪些帖子已经处理过。

## 3. 需要准备什么

1. 一个 GitHub 账号和一个 GitHub 仓库。
2. 一个飞书群，并且你有添加“自定义机器人”的权限。
3. 一个已登录的 X 账号。本方案目前使用它的 `auth_token` Cookie 让 RSSHub 读取 X 动态。

不要把 Webhook、飞书签名密钥或 X Cookie 写进代码、截图、Issue 或聊天记录。它们都是登录或发送消息的敏感凭据。

## 4. 创建仓库文件

最省事的方式是直接使用本仓库。目录结构如下：

```text
AlanFans/
├── .github/workflows/x-monitor.yml   # GitHub Actions 定时任务
├── monitor.py                        # RSS、去重、飞书推送逻辑
├── requirements.txt                  # Python 依赖
├── state.json                        # 去重状态，必须被 Git 跟踪
└── README.md
```

如果从零新建仓库，把这四个关键文件复制进去后执行：

```bash
git add .
git commit -m "feat: add X to Feishu monitor"
git push -u origin main
```

GitHub Actions 的定时任务只会读取默认分支上的工作流文件，因此请确认默认分支是 `main`，并且 `.github/workflows/x-monitor.yml` 已推送成功。

## 5. 在飞书创建自定义机器人

1. 打开目标飞书群。
2. 打开群设置，选择添加机器人或群机器人。
3. 选择“自定义机器人”。
4. 复制机器人生成的 Webhook 完整地址。
5. 在安全设置中开启“签名校验”，复制签名密钥（Secret）。

程序发送的是飞书交互式卡片。它会用当前 Unix 时间戳和签名密钥计算 HMAC-SHA256 签名，再随消息提交；飞书可以据此确认消息不是伪造的。

## 6. 取得 X 的 `auth_token`

> 这是一个会话凭据，不是普通公开信息。请只放进 GitHub Secret。

以 Chrome 或 Edge 为例：

1. 打开 `x.com`，确认已登录自己的 X 账号。
2. 按 `Option + Command + I`（macOS）或 `F12`（Windows）打开开发者工具。
3. 打开 **Application** 面板；若没有这个标签，按 `Command + Shift + P`，搜索 `Show Application`。
4. 左侧选择 **Storage -> Cookies -> https://x.com**。
5. 搜索 `auth_token`。
6. 只复制该行 **Value** 列的内容。

不要复制 `auth_token=` 这几个字符，不要复制整段 Cookie，也不要复制 `ct0`。

## 7. 配置 GitHub Secrets

进入仓库页面：

```text
Settings -> Secrets and variables -> Actions -> Secrets -> New repository secret
```

依次创建以下三个 Repository Secret：

| Name | 填什么 |
| --- | --- |
| `FEISHU_WEBHOOK` | 飞书机器人 Webhook 的完整地址 |
| `FEISHU_SIGNING_SECRET` | 飞书机器人开启签名校验后得到的 Secret |
| `TWITTER_AUTH_TOKEN` | 第 6 节复制的 `auth_token` Value |

名称必须完全一致，大小写也不能变。GitHub 会在运行时把它们注入环境变量；日志会把 Secret 脱敏显示为 `***`。

然后检查仓库权限：

```text
Settings -> Actions -> General -> Workflow permissions
```

选择 **Read and write permissions**。这是为了让任务可以把更新后的 `state.json` 提交回仓库。

## 8. 三次手动验证

打开仓库的 **Actions** 标签，选择 **Monitor X posts**，点击 **Run workflow**。第一次建议按以下顺序执行。

### 第一次：`test-message`

选择 `mode = test-message`。

预期结果：飞书收到一条“X 监控测试消息”。这个模式不会访问 X，也不会修改 `state.json`。

如果失败，优先检查 `FEISHU_WEBHOOK` 和 `FEISHU_SIGNING_SECRET` 是否复制完整，飞书机器人是否已开启签名校验。

### 第二次：`check-rss`

选择 `mode = check-rss`。

预期日志类似：

```text
RSSHub is ready.
RSS feed is reachable and parsed successfully; found 20 item(s).
```

这说明 GitHub Runner 能启动 RSSHub，并且 X 认证信息可以读取目标账号。该模式不会发送飞书消息，也不会修改 `state.json`。

### 第三次：`monitor`

选择 `mode = monitor`。

这是正式初始化。第一次会看到类似日志：

```text
Initial run: recorded 20 existing posts without notification.
```

这一步会更新并提交 `state.json`，但不会向飞书发送历史帖子。以后再有新帖子才会推送。

## 9. 为什么不用一直手动点“Run workflow”

工作流中已经有这段配置：

```yaml
schedule:
  - cron: "*/15 * * * *"
```

它的意思是每 15 分钟由 GitHub Actions 自动创建一次新的短任务。每次任务一般只运行几十秒，然后结束；这不是一个一直运行的程序。

在 Actions 页面里：

- 手动启动的任务显示为 `workflow_dispatch`。
- 定时启动的任务显示为 `schedule`。

GitHub 的定时任务是尽力执行的，繁忙时可能比设定时间晚几分钟启动，这是正常现象。

## 10. 去重是如何避免重复推送的

`state.json` 大致长这样：

```json
{
  "initialized": true,
  "seen_ids": [
    "https://x.com/YOUR_X_USERNAME/status/123456789",
    "https://x.com/YOUR_X_USERNAME/status/123456788"
  ]
}
```

程序逻辑：

1. RSSHub 返回一批帖子，每条都有唯一 ID 或链接。
2. 程序拿这些 ID 和 `seen_ids` 比较。
3. 已存在的 ID 不发送。
4. 新 ID 发送到飞书后，立即写入 `state.json`。
5. GitHub Actions 把 `state.json` 提交回仓库。

“立即写入”很重要：如果一次出现多条新帖，但第 2 条飞书发送失败，第 1 条已经保存，下次重试时不会再重复发第 1 条。

为了避免状态文件无限增长，程序只保留最近 1000 个帖子 ID。

## 11. 常见问题

| 现象 | 原因和处理方法 |
| --- | --- |
| `TWITTER_AUTH_TOKEN is not configured` | 没有在 GitHub Secrets 中创建同名 Secret，或名称拼错。 |
| `RSSHub did not become ready` | 临时容器启动超时。重新运行一次；若反复失败，查看 Actions 日志中的 RSSHub 输出。 |
| `RSS request failed: 401/403/429` | X Cookie 失效、被要求重新验证，或请求受限。停止频繁重试，重新登录 X 后更新 Secret。 |
| 飞书返回签名错误 | `FEISHU_SIGNING_SECRET` 与机器人当前签名密钥不一致，或机器人安全设置发生变化。 |
| 任务成功但没有飞书消息 | 如果日志是 `No new posts found.`，表示没有新帖子；如果刚完成第一次 `monitor`，历史帖子按设计不会发送。 |
| `state.json` 没有更新 | 检查 Actions 的 `GITHUB_TOKEN` 是否有 Read and write permissions。 |

## 12. 常见修改

### 改成监控另一个账号

编辑 `.github/workflows/x-monitor.yml` 中的：

```yaml
RSS_URL: http://127.0.0.1:1200/twitter/user/YOUR_X_USERNAME
```

把用户名换成目标账号。再编辑 `monitor.py` 顶部的：

```python
ACCOUNT = "YOUR_X_USERNAME"
```

将其改成同一个账号，以便飞书卡片标题和备用链接正确显示。然后删除或重置 `state.json` 中的 `initialized` 和 `seen_ids`，再运行一次 `monitor`，让新账号完成静默初始化。

### 也推送转推

默认配置是：

```yaml
FILTER_RETWEETS: "true"
```

改成 `"false"`，提交并推送后，转推也会发送到飞书。

### 调整检查频率

把：

```yaml
- cron: "*/15 * * * *"
```

改成例如 `*/30 * * * *`，就是每 30 分钟检查一次。不要把频率调得太高；除了增加 GitHub Actions 用量，也会增加对 X 的请求频率。

## 13. X 账号风险与更稳妥的替代方案

这里必须讲清楚：`TWITTER_AUTH_TOKEN` 是登录会话凭据。将它交给自动化程序从 GitHub Runner 发起请求，存在 Cookie 失效、额外验证、访问限制，甚至账号处罚的风险。每 15 分钟一次的低频只会降低请求量，**不能保证没有风险**。

建议：

1. 仅将 Cookie 放在 GitHub Repository Secret，绝不写入仓库。
2. 不要提高轮询频率，也不要并发运行多个同类工作流。
3. 一旦 X 出现异常登录、验证或限制提示，删除 `TWITTER_AUTH_TOKEN` Secret 并停止工作流。
4. 需要长期、稳定、合规地运行时，改用 X 官方 API。GitHub Actions 仍然可以按 15 分钟调度，不需要自己购买服务器，但需要按 X 官方 API 的权限、套餐和配额配置。

## 14. 参考资料

- [GitHub Actions: schedule 事件](https://docs.github.com/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule)
- [GitHub Actions: 使用 Secrets](https://docs.github.com/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)
- [RSSHub 项目与 X 路由源码](https://github.com/DIYgod/RSSHub/tree/master/lib/routes/twitter)
- [飞书：添加自定义机器人](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)
- [X Terms of Service](https://x.com/tos)

## 15. 上线检查清单

- [ ] 三个 GitHub Secrets 都已创建。
- [ ] `test-message` 已收到飞书测试卡片。
- [ ] `check-rss` 显示能够解析 RSS。
- [ ] 首次 `monitor` 成功，并提交了 `state.json`。
- [ ] 下一次自动任务显示为 `schedule`。
- [ ] 已理解并接受 Cookie 自动化访问 X 的风险，或已规划迁移到官方 API。
