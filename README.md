# 飞书 × GitHub × AI 团队项目管理自动化

> 用 Git 管版本，用 AI 写摘要，用飞书做文档——三者联动，提交即同步。

---

## 为什么需要这套系统

### 团队项目管理的痛点

开发团队日常面临三个割裂：

- **代码在 GitHub**，但非技术成员看不懂
- **文档在飞书**，但和代码脱节，经常过时
- **AI 对话**有上下文，但对话结束就消失，经验无法沉淀

这套系统把三者打通：**代码提交的同时，飞书自动更新文档**，AI 生成的变更摘要也实时写入，让每个人都能看到项目的最新状态。

### 四类核心使用场景

**1. 团队项目管理**

每次 `git commit` 自动记录「改了什么 / 为什么 / 优先级」，飞书里的变更日志始终是最新的。新成员入职当天就能看到项目完整历史，不需要找人口头交接。

**2. 个人开发日志 / 周报**

每天开发结束，提交一次 `daily_log.md`，AI 自动汇总成摘要推进飞书。周五再提交一次 `weekly_report.md`，一周的工作内容一键生成。再也不用专门抽时间写周报。

**3. 知识沉淀（环境部署 / 踩坑记录）**

遇到问题，解决后把过程写进 `notes/` 目录里提交。飞书里自动有一篇「XXX 问题的解决方案」，新人遇到同样的坑直接搜索就能找到，不需要再问人。

**4. AI 上下文管理**

今天和 AI 讨论了什么、解决了什么问题，提交 `ai_context/YYYY-MM-DD.md` 记录下来。下次开新对话时把这个文件贴给 AI，它立刻知道项目背景，不需要重新解释。飞书里还能跨日期搜索，快速找到「上周那个网络问题是怎么解决的」。

---

## 系统架构

```
开发者
  │
  ├── git commit ──► post-commit hook ──► feishu_writer.py ──► 飞书 Wiki
  │                        │
  │                   ai_summarize.py ──► (OpenAI) ──► 飞书变更日志
  │
  └── git push ──► GitHub Actions ──► feishu_writer.py ──► 飞书 Wiki
                                            ▲
                                      FEISHU_WIKI_TOKEN
                                    (每个项目一个页面)
```

---

## 目录结构

```
.
├── feishu/
│   ├── feishu_writer.py      # 核心：Markdown → 飞书块（支持表格/代码/标题/列表）
│   ├── ai_summarize.py       # AI 摘要：git diff → GPT → 飞书变更日志
│   ├── create_wiki_page.py   # 工具：自动在飞书创建新子页面
│   ├── .env.example          # 环境变量模板（复制为 .env 填写）
│   ├── .gitignore            # 排除 .env，防止密钥泄露
│   └── requirements.txt      # Python 依赖
├── .github/
│   └── workflows/
│       └── feishu-sync.yml   # GitHub Actions：push 时自动同步飞书
├── .git/
│   └── hooks/
│       └── post-commit       # 本地钩子：commit 后自动推飞书（备用）
└── README.md
```

---

## 完整新项目实战：从零到飞书同步

以「新建一个 Qt 嵌入式摄像头项目」为例，完整走一遍。

### 准备工作：你需要提供什么

| 需要的东西 | 从哪里获取 | 示例 |
| --- | --- | --- |
| GitHub 账号 | github.com 注册 | `777mygit` |
| GitHub 邮箱 | 注册时填的邮箱 | `25s001027@stu.hit.edu.cn` |
| GitHub 仓库 HTTPS 地址 | 仓库页面绿色 Code 按钮 | `https://github.com/777mygit/qt-camera.git` |
| GitHub Personal Access Token | Settings → Developer settings → Tokens | `ghp_xxxxxxxxxxxxxxxx` |
| 飞书 App ID | 飞书开放平台 → 我的应用 | `cli_xxxxxxxxxxxxxxxxxxxx` |
| 飞书 App Secret | 同上（**不要提交到 Git！**） | `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| 飞书新页面 Wiki Token | 新建飞书页面后从 URL 复制 | `AbCdEfGhIjKlMnOpQrSt`（每个项目不同） |

---

### 第 1 步：GitHub 端——创建仓库

**1.1 配置 Git 身份（首次使用，只需做一次）**

```powershell
git config --global user.name "777mygit"
git config --global user.email "25s001027@stu.hit.edu.cn"
```

**1.2 在 GitHub 网站创建仓库**

1. 打开 [github.com](https://github.com) → 右上角「+」→「New repository」
2. Repository name 填：`qt-opencv-camera`
3. 选 Private（团队项目）或 Public（开源）
4. 不勾选「Initialize this repository with a README」（本地已有文件时）
5. 点「Create repository」，复制 HTTPS 地址：`https://github.com/777mygit/qt-opencv-camera.git`

**1.3 本地初始化并推送**

```powershell
# 进入项目目录
cd Z:\qt_demo\EmbeddedQtTutorial\05_opencv_camera

# 初始化 Git
git init

# 第一次提交
git add .
git commit -m "init: 初始化 Qt OpenCV 摄像头项目"

# 关联远程仓库并推送
git remote add origin https://github.com/777mygit/qt-opencv-camera.git
git push -u origin main
```

> 推送时会弹出身份验证窗口，用户名填 GitHub 账号，密码填 Personal Access Token（不是登录密码）。

---

### 第 2 步：飞书端——创建项目页面

**2.1 新建空白页面**

1. 打开飞书知识库，左侧「+」→「新建页面」
2. 标题填：`Qt OpenCV 摄像头项目`
3. 创建后复制浏览器 URL：
   ```
   https://ncnte6r0dba2.feishu.cn/wiki/AbCdEfGhIjKlMnOpQrSt
   ```
   Token 就是 `wiki/` 后面的部分：`AbCdEfGhIjKlMnOpQrSt`

**2.2 给应用授权（只需做一次）**

1. 打开新页面 → 右上角「分享」→「添加协作者」
2. 搜索框输入应用名（如 `linux`）→ 选带橙色「应用」标签的那个
3. 权限选「可编辑」→ 确认

> 以后在同一知识库下新建的页面，如果父页面已授权，子页面自动继承，不需要重复操作。

---

### 第 3 步：本地配置——接入自动化工具

**3.1 克隆本工具仓库（首次使用）**

```powershell
# 把本工具克隆到本地（只需一次）
git clone https://github.com/777mygit/---github-ai-.git C:\tools\feishu-sync
cd C:\tools\feishu-sync
pip install -r feishu/requirements.txt
```

**3.2 配置环境变量**

```powershell
copy feishu\.env.example feishu\.env
```

编辑 `feishu\.env`，填入项目对应的值：

```env
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx   # ← 绝对不要提交这个文件！
FEISHU_WIKI_TOKEN=AbCdEfGhIjKlMnOpQrSt   ← 刚才复制的新页面 token
FEISHU_OPEN_DOMAIN=https://open.feishu.cn
```

**3.3 验证连通性**

```powershell
cd C:\tools\feishu-sync
python feishu/feishu_writer.py Z:\qt_demo\EmbeddedQtTutorial\05_opencv_camera\README.md

# 预期输出：
# [parse] 解析出 N 个单元
# [auth] 获取 tenant_access_token ... ok
# [wiki] node=AbCdEfGhIjKlMnOpQrSt -> document_id=xxxxxxxxxxxxxxx
# [write] 追加 N 个单元 ...
# [done] 完成，去飞书刷新文档看看吧。
```

---

### 第 4 步：配置 GitHub Actions——云端自动同步

在项目仓库里添加 GitHub Secrets（Settings → Secrets and variables → Actions → New repository secret）：

| Secret 名称 | 值 |
| --- | --- |
| `FEISHU_APP_ID` | `cli_xxxxxxxxxxxxxxxxxxxx` |
| `FEISHU_APP_SECRET` | `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| `FEISHU_WIKI_TOKEN` | `AbCdEfGhIjKlMnOpQrSt` |
| `OPENAI_API_KEY` | `sk-xxx`（可选，用于 AI 摘要） |

把 `.github/workflows/feishu-sync.yml` 复制到新项目仓库的对应目录，推送后 Actions 自动激活。

---

### 第 5 步：日常使用——提交即同步

**场景一：更新项目文档**

```powershell
cd Z:\qt_demo\EmbeddedQtTutorial\05_opencv_camera

# 修改 README 或文档后提交
git add docs\camera_setup.md
git commit -m "docs: 补充 OV5640 摄像头初始化流程"

# 钩子自动触发，终端输出：
# [feishu-hook] 推送章节: docs/camera_setup.md
# [done] 完成，去飞书刷新文档看看吧。

# 同时推到 GitHub
git push
# Actions 触发，云端再同步一次（确保团队成员的推送也能同步）
```

**场景二：记录今天踩的坑**

```powershell
# 新建笔记文件
New-Item notes\2026-04-23_opencv_link_error.md

# 写入内容后提交
git add notes\
git commit -m "note: 记录 OpenCV 链接错误的解决方案"
# AI 自动生成摘要：「修复了 OpenCV 动态库路径问题，P2 优先级，影响所有 Linux 构建环境」
```

**场景三：写周报**

```powershell
New-Item weekly\2026-W17.md

# 内容可以很粗糙，AI 会帮你整理
git add weekly\
git commit -m "weekly: 第17周工作总结"
# 飞书里自动出现格式化的周报
```

**场景四：全量重建飞书文档**

```powershell
# 在 GitHub Actions 手动触发（适合文档结构大改之后）
# GitHub 仓库 → Actions → Sync to Feishu → Run workflow → clear=true
```

---

## 常见问题

| 现象 | 原因 | 解决方案 |
| --- | --- | --- |
| `401 Unauthorized` | App Secret 错误或 token 过期 | 检查 `.env`，重新获取 token |
| `403 forBidden` | 新页面没有单独给应用授权 | 飞书新页面 → 分享 → 搜应用名 → 可编辑 |
| 表格显示为文本 | 旧版 feishu_writer.py | 更新到最新版（支持 `/descendant` API） |
| 速度很慢 | 飞书 5 QPS 限制 | 正常现象，500 块约需 100 秒 |
| 钩子没有触发 | Windows 权限问题 | 确认 `.git/hooks/post-commit` 无文件扩展名 |
| git push 要求输入密码 | 没有配置 Token | 密码处填 GitHub Personal Access Token |

---

## 这套系统的意义

### 对团队

- **零成本交接**：新成员入职，打开飞书就能看到项目完整历史和踩坑记录，第一天就能上手
- **文档永远最新**：文档和代码同一个仓库，提交代码的同时文档自动更新，不会出现「文档说A但代码是B」的情况
- **问题有迹可查**：每个 bug 修复都有对应的 AI 摘要（改了什么/为什么/优先级），Code Review 时有据可依
- **会议效率提升**：站会前 AI 自动汇总昨天所有 commit，不需要每个人口头汇报「我昨天做了什么」

### 对个人

- **知识不再流失**：每次解决问题后写一行提交，AI 帮你整理成文章，几个月后翻飞书就能找到当初的解决思路
- **周报自动生成**：平时正常提交，周五把本周 commit 汇总一下，周报就写完了
- **AI 上下文延续**：把历史对话总结提交到仓库，下次开新对话把文件贴给 AI，它立刻接上上下文，不需要重新介绍项目

### 对知识管理

- **飞书全文检索**：所有文档在飞书里，搜索「OpenCV 链接错误」秒出历史解决方案，比翻聊天记录快 10 倍
- **结构化沉淀**：`notes/` 目录自动变成知识库，`weekly/` 目录自动变成周报存档，不需要额外维护
- **跨项目复用**：A 项目踩过的坑，B 项目的人在飞书里搜一下就能找到，知识在团队内流动

---

## 扩展路线图

- [x] Markdown → 飞书块转换（含表格、代码高亮）
- [x] 本地 post-commit 钩子（提交即同步）
- [x] GitHub Actions 云端同步（支持手动全量重建）
- [x] AI 变更摘要（OpenAI，无 Key 时降级为 commit message）
- [x] 创建新飞书子页面工具（create_wiki_page.py）
- [ ] 每章/每文件独立 Wiki 子页面（实现章节级覆盖）
- [ ] GitHub Issue ↔ 飞书 Bitable 双向同步（看板管理）
- [ ] 每日站会摘要定时发送到飞书群
- [ ] PR 合并自动生成版本说明推送飞书群消息
- [ ] 飞书 Bitable 问题优先级看板（P0/P1/P2 分级管理）

---

## 许可

MIT License — 自由使用，欢迎 PR。
