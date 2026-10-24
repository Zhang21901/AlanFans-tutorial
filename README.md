# X to Feishu Monitor

Template repository for monitoring a chosen X account with GitHub Actions,
RSSHub, and a Feishu custom bot. No always-on server is required.

For a complete Chinese walkthrough, see
[不买服务器：用 GitHub Actions 监控 X 动态并推送到飞书](docs/x-to-feishu-github-actions-guide.zh-CN.md).

An X Article draft is also available at
[不用服务器，15 分钟监控 X 动态并自动推送到飞书](docs/x-article.zh-CN.md).

Before the first run, replace both `YOUR_X_USERNAME` values in
`.github/workflows/x-monitor.yml` with the account name to monitor, without
the `@` symbol.

## Setup

1. Create a GitHub repository from this directory and push it to GitHub.
2. In the repository, open **Settings -> Secrets and variables -> Actions** and
   create these repository secrets:
   - `FEISHU_WEBHOOK`: the complete Feishu custom-bot webhook URL.
   - `FEISHU_SIGNING_SECRET`: the bot's signing secret. Leave the secret empty
     only when signing is disabled for the bot.
   - `TWITTER_AUTH_TOKEN`: the `auth_token` cookie value from a logged-in X
     account. This is used only by the temporary RSSHub container running on
     the GitHub Actions runner.
3. Enable Actions for the repository. The workflow needs **Read and write
   permissions** for `GITHUB_TOKEN` so it can commit `state.json`.
4. Run **Actions -> Monitor X posts -> Run workflow**. Select `check-rss` to
   validate the RSSHub URL, `monitor` for the initial state setup, or
   `test-message` to verify the Feishu webhook and signing secret.

The first `monitor` run stores the posts currently present in the feed without
sending them. Later runs, scheduled every 15 minutes, send only unseen posts.

## Configuration

The settings are in `.github/workflows/x-monitor.yml`:

- RSSHub starts as a temporary Docker container on each `monitor` or
  `check-rss` run. It listens only on `127.0.0.1:1200` and is removed when the
  job ends; no server or public RSSHub instance is required.
- The workflow pins RSSHub to `diygod/rsshub:2026-10-23`. Review and update this
  tag deliberately when upgrading RSSHub.
- `FILTER_RETWEETS`: `"true"` sends original posts only. Change it to `"false"`
  to include reposts.

`state.json` is deliberately tracked in Git. Do not add it to `.gitignore`:
the workflow commits this file after each successful observation so the next
runner can deduplicate posts.

## Notes

- GitHub Actions scheduled jobs are best-effort. GitHub can delay scheduled
  runs during periods of high load.
- An RSSHub or Feishu failure makes the workflow fail and leaves unsent post IDs
  out of the state, allowing the next run to retry them.
- Workflow logs contain operational errors but never print the webhook URL or
  signing secret.
- Run the `check-rss` workflow mode after configuring `TWITTER_AUTH_TOKEN`. A
  successful run confirms that the GitHub Actions runner can fetch and parse
  the account feed without sending a Feishu message or modifying `state.json`.
