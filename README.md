# Trend Inbox

主动收集每天Agent开发的热门趋势到你的邮箱。

- **日刊**收录 2 篇 Hugging Face Agent 论文和 GitHub Trending Python 日榜前 5 个项目。论文附中文导读、题目和摘要译文。项目按原榜顺序显示简介和榜单数据。
- **周刊**推送 GitHub Trending Python 周榜前 5 个项目。

## 本地安装

下载并解压发行包。Windows 双击 `setup-windows.bat`，macOS 在项目目录运行 `bash setup-mac.sh`。如果还没有 `uv`，按提示确认后，脚本会把它下载到当前项目目录并继续安装。

已有 `uv` 的用户也可以在项目根目录直接运行：

```text
uv sync --locked
uv run --locked python -m agent_digest.setup_wizard
```

`uv` 会选择可用的 Python 3.12 或更高版本，并按锁文件安装依赖。

向导里选择模型服务，再填写该服务商控制台里的模型 ID 和 API 密钥。重新配置同一服务商时，可以回车沿用自己上次保存的模型 ID。填写发件和收件地址及邮箱授权码，QQ、163、126 和 Gmail 会自动带出 SMTP 参数。向导会检查模型、邮箱和两个榜单来源。确认收到测试邮件后，Windows 可在向导里登记定时任务，macOS 和 Linux 按下面的 cron 步骤设置。

### 手动配置

需要手动配置时，把 `.env.example` 复制为项目根目录的 `.env`，然后填写下列配置。

| 用途 | 配置 |
| --- | --- |
| 模型 | `LLM_API_KEY`、`LLM_MODEL`、`LLM_BASE_URL`。服务需兼容 Chat Completions JSON object 模式，使用所填供应商支持的模型 ID |
| 邮箱 | `SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`MAIL_FROM`、`MAIL_TO`。587 默认使用 STARTTLS，465 默认使用隐式 TLS |

如果用 Gmail 的应用专用密码，按 Gmail 账号显示的要求创建后填入 `SMTP_PASSWORD`。`MAIL_TO` 可以填自己的常用邮箱。模型服务可能按调用计费。

### 先预览，再试发

安装完成后，在项目根目录运行下面的 Windows PowerShell 命令。macOS 和 Linux 改用 `./.venv/bin/python`，后续参数照抄。

```powershell
.\.venv\Scripts\python.exe -m agent_digest daily --dry-run
.\.venv\Scripts\python.exe -m agent_digest weekly --dry-run
```

预览保存在 `preview/` 下，有 `.html` 和 `.txt` 两个版本。预览会实时抓榜和调用模型。检查内容后，在手机上验证一次真实邮件：

```powershell
.\.venv\Scripts\python.exe -m agent_digest daily --send
```

如果今天的正式早报尚未发送，这条命令会发出本期邮件。当日定时任务会跳过已发送的期号。

## 定时发送

### Windows

```powershell
.\install-schedule.ps1 -DailyAt '08:10' -WeeklyDay Monday -WeeklyAt '08:30' -WhatIf
.\install-schedule.ps1 -DailyAt '08:10' -WeeklyDay Monday -WeeklyAt '08:30'
```

第一行预览即将注册的任务，第二行才写入 Windows 任务计划程序。两项独立设置，时间按 Windows 的本地时钟。以后用新时间重新运行第二行即可更新。同一台电脑上这两个任务名分别是 `Agent Digest Daily` 和 `Agent Digest Weekly`。如果任务注册后移动了项目目录，请在新位置重跑脚本。

执行时电脑需开机、联网，并保留当前 Windows 用户登录。锁屏可以，关机期间不会发信。任务会在 Windows 允许的下一次机会补跑，以实际运行当天或当周为期号。若希望从睡眠唤醒，可用 `-WakeToRun`，是否能唤醒取决于设备和电源设置。想全天停止发送，可以在任务计划程序里禁用这两项。

### macOS 和 Linux

在项目根目录运行 `pwd` 取得项目的绝对路径，再用 `crontab -e` 编辑当前用户的计划任务。把示例中的 `/absolute/path/trend-inbox` 换成 `pwd` 显示的路径。

```cron
10 8 * * * cd "/absolute/path/trend-inbox" && .venv/bin/python -m agent_digest daily --send --log .digest/daily.log
30 8 * * 1 cd "/absolute/path/trend-inbox" && .venv/bin/python -m agent_digest weekly --send --log .digest/weekly.log
```

示例按电脑本地时钟每天 08:10 发日刊，每周一 08:30 发周刊。保存后用 `crontab -l` 检查两行是否生效。使用项目里的 `.venv/bin/python` 可以避免 cron 找不到 `uv` 或装错环境。执行时电脑需要开机、联网并保持唤醒。搬动项目目录后需要改 `crontab` 中的路径。

## 排错与补发

- 日刊和周刊日志在 `.digest/daily.log` 与 `.digest/weekly.log`。SQLite 状态保存在 `.digest/state.sqlite3`，用于同一期去重和跳过已发送的论文。
- 正式发送需要显式传 `--send`。默认命令生成预览。榜单连接失败时，程序分别等 30 秒、90 秒和 3 分钟后重试。所需榜单仍无法获取时，本期不发信，也不会记为已发。网络恢复后可以手动重跑本期。
- 入选论文的译文生成失败且其他候选不足以补齐时，程序停止本期发送，并在日志里指出原因。
- 访问 Hugging Face 需要代理时，可以在 `.env` 设置 `HF_PROXY_URL` 为你的 HTTP(S) 代理地址。它只用于 Hugging Face 请求。定时运行时代理也需要在线。
- 邮件传输若遇到结果不确定的中断，系统保留发送记录。先确认原任务已退出，再检查邮箱。确认已到达时用 `--resolve sent`，确认需要重试时用 `--resolve retry`。

```powershell
.\.venv\Scripts\python.exe -m agent_digest daily --edition 2026-11-16 --resolve retry
.\.venv\Scripts\python.exe -m agent_digest daily --edition 2026-11-16 --send
```

这里的日期只是示例。周刊的期号格式为 `2026-W47`。补发会重新生成内容，GitHub 项目使用补发时读到的榜单，实际抓取时间在邮件中显示。

