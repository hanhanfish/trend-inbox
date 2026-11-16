# 榜上早报

自托管邮件早报。日刊收录 2 篇 Hugging Face Agent 论文，以及 GitHub Trending Python 日榜前 5 个项目。周刊另外推送 Python 周榜前 5 个项目。项目顺序跟随 GitHub 原榜。

论文导读从具体场景切入，摘要译文保留原段落并拆开长句。GitHub 卡片显示仓库名及链接、榜单原简介的译文、语言、总星标、Fork 数、新增星标和榜单提供的贡献者头像。简介翻译失败时显示原文。

## Windows 快速开始

1. 解压完整 ZIP 到准备长期保留的文件夹，双击 `setup-windows.bat`。安装脚本会复用已有 Python 3.11+。找不到时，可通过 `uv` 把 Python 安装在项目目录里。
2. 在向导选择模型服务，输入 API 密钥，再填写发件邮箱、邮箱授权码和收件地址。QQ、163、126 和 Gmail 的 SMTP 配置会自动填写。向导会分别验证模型和 SMTP 登录，成功后才保存配置。
3. 确认发送一封测试信。收件箱看到「榜上早报 · 发信测试」后，按提示填写每天发送时间、每周发送时间和星期几。向导会注册 Windows 任务并显示下次运行时间。

安装时需要联网。模型连通性测试会发起一次小模型调用，可能产生用量。你可以随时重新运行向导更新配置。

本地安装和邮箱自动识别参考了 [TrendRadar 的 Windows 脚本](https://github.com/sansan0/TrendRadar/blob/master/setup-windows.bat) 和 [邮箱配置](https://github.com/sansan0/TrendRadar/blob/master/README.md#L1564-L1588)。先验证再设置定时的流程参考 [rss2email 的首次运行说明](https://github.com/rss2email/rss2email/blob/master/README.rst#L104-L144)。

## 手动安装与排错

安装 Python 3.11 或更新版本，在项目目录打开 PowerShell。`.venv` 是项目专用环境。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
Copy-Item config.example.yml config.yml
```

编辑 `.env`，填写以下配置：

| 用途 | 配置 |
| --- | --- |
| 模型 | `LLM_API_KEY`、`LLM_MODEL`、`LLM_BASE_URL`。服务需兼容 Chat Completions JSON object 模式，使用所填供应商支持的模型 ID |
| 邮箱 | `SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`MAIL_FROM`、`MAIL_TO`。587 默认使用 STARTTLS，465 默认使用隐式 TLS |

如果用 Gmail 的应用专用密码，按 Gmail 账号显示的要求创建后填入 `SMTP_PASSWORD`。`MAIL_TO` 可以填自己的常用邮箱。模型服务可能按调用计费。

### 先预览，再试发

```powershell
.\.venv\Scripts\python.exe -m agent_digest daily --dry-run
.\.venv\Scripts\python.exe -m agent_digest weekly --dry-run
```

预览保存在 `preview/` 下，有 `.html` 和 `.txt` 两个版本。预览会实时抓榜和调用模型。检查内容后，在手机上验证一次真实邮件：

```powershell
.\.venv\Scripts\python.exe -m agent_digest daily --send
```

这条命令会发出今天的正式早报。当天的定时任务会识别为已发。

### 设定每天和每周的推送时间

```powershell
.\install-schedule.ps1 -DailyAt '08:10' -WeeklyDay Monday -WeeklyAt '08:30' -WhatIf
.\install-schedule.ps1 -DailyAt '08:10' -WeeklyDay Monday -WeeklyAt '08:30'
```

第一行预览即将注册的任务，第二行才写入 Windows 任务计划程序。两项独立设置，时间按 Windows 的本地时钟。以后用新时间重新运行第二行即可更新。同一台电脑上这两个任务名分别是 `Agent Digest Daily` 和 `Agent Digest Weekly`。如果任务注册后移动了项目目录，请在新位置重跑脚本。

执行时电脑需开机、联网，并保留当前 Windows 用户登录。锁屏可以，关机期间不会发信。任务会在 Windows 允许的下一次机会补跑，以实际运行当天或当周为期号。若希望从睡眠唤醒，可用 `-WakeToRun`，是否能唤醒取决于设备和电源设置。想全天停止发送，可以在任务计划程序里禁用这两项。

## 排错与补发

- 日刊和周刊日志在 `.digest/daily.log` 与 `.digest/weekly.log`。SQLite 状态保存在 `.digest/state.sqlite3`，用于同一期去重和跳过已发送的论文。
- 正式发送需要显式传 `--send`。默认命令生成预览。全部数据源失败时本次报错；部分失败时仍发可用栏目，邮件标明缺失。
- 邮件传输若遇到结果不确定的中断，系统保留发送记录。先确认原任务已退出，再检查邮箱。确认已到达时用 `--resolve sent`，确认需要重试时用 `--resolve retry`。

```powershell
.\.venv\Scripts\python.exe -m agent_digest daily --edition 2026-11-16 --resolve retry
.\.venv\Scripts\python.exe -m agent_digest daily --edition 2026-11-16 --send
```

这里的日期只是示例。周刊的期号格式为 `2026-W47`。补发会重新生成内容，GitHub 项目使用补发时读到的榜单，实际抓取时间在邮件中显示。

macOS 或 Linux 用户也可以在本地用 Python 运行，用 cron 或 systemd 定时调用同一个 `python -m agent_digest daily --send` / `weekly --send`。工作目录须是项目根目录，日志可通过 `--log` 指定。
