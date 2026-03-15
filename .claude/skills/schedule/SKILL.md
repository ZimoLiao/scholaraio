---
name: schedule
description: Set up a recurring paper notification digest. Fetches new papers from OpenAlex matching a research topic, scores by relevance, and delivers to Telegram/email/Slack via Apprise. Use when the user wants to subscribe to a research topic, set up paper alerts, or schedule periodic literature updates.
---

# 论文推送订阅

设置定期论文推送任务。每次运行从 OpenAlex 拉取与研究兴趣匹配的新论文，语义评分过滤后推送到配置的频道（Telegram、邮件、Slack 等）。

## 执行逻辑

### 第一步：确认参数

从用户描述中提取：
- **研究主题**：用于 OpenAlex 检索和语义评分的查询词（英文效果更好）
- **推送频道**：询问用户想用哪种方式接收（Telegram / 邮件 / 其他）
- **推送频率**：每天 / 每周 / 每两周（转换为 cron 表达式）
- **工作区名称**：建议从主题推导，如 `protein-folding-watch`

如果用户没有提供频道信息，先创建任务，后续补充。

### 第二步：创建任务

```bash
scholaraio notify init <名称> \
  --query "<研究主题英文描述>" \
  --schedule "<cron表达式>" \
  [--channel "<Apprise URL>"] \
  [--threshold 0.65] \
  [--max-papers 10]
```

**常用 cron 表达式（5 字段）：**
- 每周一上午 8 点：`"0 8 * * 1"`（默认）
- 每天上午 9 点：`"0 9 * * *"`
- 每周五下午 6 点：`"0 18 * * 5"`

> **注意**：systemd 定时器转换仅支持简单表达式（固定星期 + 时间，如上例）。含步进（`1/2`）或范围的复杂 cron 会自动回退为每周执行。如需精确控制频率，建议直接用 crontab。

**Apprise URL 格式（常用）：**
- Telegram：`tgram://BOT_TOKEN/CHAT_ID`
  - 获取 TOKEN：Telegram 搜索 @BotFather → /newbot
  - 获取 CHAT_ID：@userinfobot 或 https://api.telegram.org/bot<TOKEN>/getUpdates
- 邮件（Gmail）：`mailto://user:APP_PASSWORD@gmail.com`
  - Gmail 需使用"应用专用密码"
- 邮件（通用 SMTP）：`mailtos://user:pass@smtp.example.com`
- Slack webhook：`slack://TokenA/TokenB/TokenC/`
- Discord webhook：`discord://webhook_id/webhook_token`

如果用户需要帮助获取 Apprise URL，引导他们完成对应平台的配置步骤。

### 第三步：预览效果

```bash
scholaraio notify run <名称> --dry-run
```

dry-run 会生成 `workspace/<名称>/draft.md` 但不发送。展示给用户确认摘要格式。

### 第四步：安装定时器（可选）

如果用户希望自动运行：

```bash
scholaraio notify install <名称>
```

这会安装 systemd user timer，在系统后台定期执行。

如果不在 Linux/systemd 环境，告知用户可以用 crontab 手动设置：
```bash
# crontab -e 中添加（根据 schedule 调整）：
0 8 * * 1 /path/to/scholaraio notify run <名称>
```

## 管理任务

### 查看所有通知任务
```bash
scholaraio notify list
```

### 手动触发一次推送
```bash
scholaraio notify run <名称>
```

### 查看推送历史
```bash
scholaraio notify history <名称>
```

### 修改任务配置
重新运行 `notify init`，会覆盖现有配置中的对应字段：
```bash
scholaraio notify init <名称> --query "<新查询词>" --threshold 0.7
```

## 技术说明

- **去重**：已推送过的论文 DOI 记录在 `data/index.db` 的 `notify_seen` 表，不会重复出现
- **评分**：使用与主库相同的 Qwen3-Embedding 模型进行语义相关性评分
- **来源**：默认从 OpenAlex 拉取，也支持监控本地库新增论文（`--sources library`）
- **摘要文件**：每次运行生成 `workspace/<名称>/digests/YYYY-MM-DD-HHMMSSz.md`（时间戳防覆盖）和 `draft.md`（最新预览用）

## 示例

用户说："帮我每周推送蛋白质结构预测相关新论文到 Telegram"

```bash
# 1. 创建任务（先不加 channel，等用户提供 token）
scholaraio notify init protein-watch \
  --query "protein structure prediction diffusion model" \
  --schedule "0 8 * * 1"

# 用户提供 token 后：
scholaraio notify init protein-watch \
  --channel "tgram://7823456789:AAxxxxxx/123456789"

# 2. 预览
scholaraio notify run protein-watch --dry-run

# 3. 安装定时器
scholaraio notify install protein-watch
```

用户说："帮我每天把 diffusion model 相关论文发到我邮箱"

```bash
scholaraio notify init diffusion-daily \
  --query "score-based diffusion model generative" \
  --schedule "0 8 * * *" \
  --channel "mailto://user:apppassword@gmail.com"
scholaraio notify run diffusion-daily --dry-run
scholaraio notify install diffusion-daily
```
