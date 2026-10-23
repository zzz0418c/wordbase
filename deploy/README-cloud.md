# 云端推送：让电脑关机也能收到微信

目标：每天北京时间 07:25，由 GitHub 的机器算一次今天的任务，推到你的微信。
整个过程只需要你的 GitHub 账号和一个微信推送地址，**不需要你电脑开机**。

---

## 一、先选一个"微信推送地址"

三种都行，选一个：

| 方式 | 拿到什么 | 适合谁 |
| --- | --- | --- |
| **企业微信群机器人** | `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx` | 有企业微信（可以自己建一个只有自己的群，免费） |
| **Server酱** | `https://sctapi.ftqq.com/SCTxxxx.send` | 不想装企业微信；微信扫码登录 [sct.ftqq.com](https://sct.ftqq.com) 就能拿 SendKey |
| **ntfy** | `https://ntfy.sh/你的私密topic` | 不介意多装一个 App（手机装 ntfy 订阅同名 topic） |

拿到地址后，本地先验证一次（这一步不发真实消息，只打印）：

```powershell
.\vv.cmd push --dry-run
.\vv.cmd push --url "你的地址" --format wecom
```

`--format` 跟着地址选：企业微信 `wecom`、Server酱 `serverchan`、ntfy `ntfy`。

---

## 二、把仓库推上 GitHub

1. 在 GitHub 网页上新建一个**私有**仓库，名字随便（比如 `vocabcurve`），**不要**勾选 README/.gitignore。
2. 在本目录执行（把地址换成你的）：

```powershell
.\setup-cloud.ps1 -RepoUrl "https://github.com/你的用户名/vocabcurve.git"
```

脚本会：初始化 git → 提交 → 推送 → 打开"新建 Secret"的网页。

3. 在那个网页里，Name 填 `VOCAB_PUSH_URL`，Secret 填第一步拿到的地址，保存。

---

## 三、开启定时任务

1. 打开仓库的 **Actions** 标签页，第一次会问要不要启用 workflows → 点 **I understand my workflows, go ahead and enable them**。
2. 左侧选 **每日单词复习提醒** → 右侧 **Run workflow** 手动跑一次。
3. 跑完看日志：出现 `✓ 已推送（wecom）` 就通了，微信应该立刻收到一条。

之后每天 UTC 23:25（北京时间 07:25）自动跑。GitHub 的免费定时任务**可能延迟 5–15 分钟**，通常 07:30 前后到，介意的话可以把 cron 改成 `20 23 * * *`。

---

## 四、它每天发什么

内容就是 `vocabcurve brief` 的输出，例如：

```
📚 10月21日 周三 · 今天 2 项
· L01 雅思词汇真经01  第 1 轮
· L02 雅思词汇真经02  首次学习
⚠️ 补做：L03 第 2 轮
（22 篇在册，共 0 词）
```

它是**只读**的：云端只读你提交的 `book.json`，不会写回。你在本地打卡后，重新 `import --merge`
或直接编辑 `book.json` 后提交一次，云端看到的就是最新的。

---

## 五、常见问题

- **失败：`VOCAB_PUSH_URL` 为空** → 第二步的 Secret 没建或名字拼错。
- **企业微信返回 93000** → 机器人被移出群了，重新建一个。
- **Server酱返回 40001** → SendKey 错了。
- **想改时间** → 改 `.github/workflows/daily.yml` 里的 `cron`，注意是 UTC。
- **不想让代码公开** → 仓库设成 Private；Actions 在私有仓库每月有 2000 分钟免费额度，这个任务每天只用十几秒。
