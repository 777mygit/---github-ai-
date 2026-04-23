# 飞书 × GitHub × AI 团队项目管理自动化

> 用 Git 管版本，用 AI 写摘要，用飞书做文档——三者联动，提交即同步。

---

## 为什么需要这套系统

开发团队日常面临三个割裂：

- **代码在 GitHub**，但非技术成员看不懂
- **文档在飞书**，但和代码脱节，经常过时
- **AI 对话**有上下文，但对话结束就消失，经验无法沉淀

这套系统把三者打通：**代码提交的同时，飞书自动更新文档**，AI 生成的变更摘要也实时写入，让每个人都能看到项目的最新状态。

---

## 两类使用模式

本系统支持两类使用模式，覆盖团队协作和个人使用的不同需求：

| 模式 | 推送目标 | 适用场景 |
| --- | --- | --- |
| **飞书 + GitHub 联动** | 飞书文档 + GitHub 仓库 | 团队项目管理，代码和文档同步 |
| **只推飞书** | 仅飞书文档 | 个人日志、踩坑记录、AI 上下文，不污染 Git 历史 |

---

## 核心设计：一个项目 = 一个仓库 = 一个飞书页面

**这是最推荐的使用方式，每个仓库只需配置一次，以后永远不用改。**

```
GitHub 仓库                    飞书页面
─────────────────────────────────────────────────────
qt-opencv-camera      ──►  飞书「Qt OpenCV 摄像头项目」页面
linux-learning        ──►  飞书「Linux 应用开发大全」页面
---github-ai-         ──►  飞书「飞书×GitHub×AI 团队管理」页面
your-next-project     ──►  飞书「你的下一个项目」页面
```

每个仓库在 GitHub Secrets 里单独配置 `FEISHU_WIKI_TOKEN`，指向对应的飞书页面。推送时，Actions 自动同步到**这个项目专属的飞书页面**，和其他项目完全隔离。

---

## 系统架构

```
开发者
  │
  ├─ 飞书 + GitHub 联动（团队项目管理）
  │    git commit ──► post-commit hook ──► feishu_writer.py ──► 飞书 Wiki
  │                        │
  │                   ai_summarize.py ──► OpenAI（可选）──► 飞书变更日志
  │    git push  ──► GitHub Actions  ──► feishu_writer.py ──► 飞书 Wiki
  │                        ▲
  │             读取 secrets.FEISHU_WIKI_TOKEN（每仓库设一次）
  │
  └─ 只推飞书（个人日志/踩坑/AI上下文）
       python feishu/feishu_writer.py 文件.md ──► 飞书 Wiki
       （无需 git push，也不会走 GitHub Actions）
```

---

## 目录结构

```
.
├── feishu/
│   ├── feishu_writer.py      # 核心：Markdown → 飞书块（含重试逻辑）
│   ├── ai_summarize.py       # AI 摘要：git diff → GPT → 飞书变更日志
│   ├── create_wiki_page.py   # 工具：自动在飞书创建新子页面
│   ├── .env.example          # 环境变量模板（复制为 .env 填写真实值）
│   └── requirements.txt      # Python 依赖
├── .github/
│   └── workflows/
│       └── feishu-sync.yml   # GitHub Actions：push 时自动同步飞书
├── .git/hooks/post-commit    # 本地钩子：commit 后自动推飞书
│
├── book/chapters/            # 团队项目文档（联动模式）
├── daily_log/                # 每日开发日志（只推飞书）
│   └── YYYY-MM-DD.md
├── weekly/                   # 每周总结（只推飞书）
│   └── YYYY-WXX.md
├── notes/                    # 踩坑记录 / 知识沉淀（只推飞书）
│   └── YYYY-MM-DD_问题标题.md
├── ai_context/               # AI 对话上下文（只推飞书）
│   └── YYYY-MM-DD.md
└── README.md
```

---

## 安全须知（重要，请先读）

> **App Secret 是最高机密，泄露后必须立即重置。**

| 文件 | 能提交到 Git 吗 | 说明 |
| --- | --- | --- |
| `feishu/.env` | **绝对不能** | 含真实密钥，已加入 `.gitignore` |
| `feishu/.env.example` | 可以 | 只含占位符，无真实值 |
| GitHub Secrets | 安全 | 加密存储，Actions 读取，日志中不显示 |

**如果密钥不小心推到了 GitHub：**
1. 立即去飞书开放平台重置 App Secret（旧的立刻失效）
2. 用 `git log --all -S "旧密钥"` 找到涉及的 commit
3. 联系 GitHub Support 清除历史记录，或直接删库重建

---

## 完整新项目实战：从零到飞书同步

以「新建一个 Qt 嵌入式摄像头项目」为完整示例。

### 你需要准备什么

| 需要的东西 | 从哪里获取 | 示例（请替换为你自己的） |
| --- | --- | --- |
| GitHub 账号 | github.com 注册 | `yourname` |
| GitHub 邮箱 | 注册时填写的邮箱 | `you@example.com` |
| GitHub 仓库 HTTPS 地址 | 仓库页面绿色 Code 按钮复制 | `https://github.com/yourname/qt-camera.git` |
| GitHub Personal Access Token | Settings → Developer settings → Tokens (classic) → 勾选 repo | `ghp_xxxxxxxxxxxx` |
| 飞书 App ID | 飞书开放平台 → 我的应用 → 凭证与基础信息 | `cli_xxxxxxxxxxxxxxxxxxxx` |
| 飞书 App Secret | 同上（**不要截图、不要发给别人**） | `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| 飞书新页面 Wiki Token | 新建飞书页面后从 URL 复制 | 见下方飞书端操作 |

---

### 前置步骤：创建飞书企业自建应用（只需做一次）

**这是整套系统的基础，所有项目共用同一个飞书应用。做过一次之后，以后新项目只需要新建飞书页面并授权即可。**

**A. 创建应用**

1. 打开 [飞书开放平台](https://open.feishu.cn/app) → 点「创建企业自建应用」
2. 填写应用名称（如 `linux`）和描述，点「确定创建」
3. 进入应用页面 → 左侧「凭证与基础信息」→ 复制 **App ID** 和 **App Secret**

> ⚠ App Secret 只显示一次（或点「重置」才能看到新值），立刻保存到本地 `feishu/.env`，不要截图发送。

**B. 申请权限**

1. 左侧点「权限管理」→ 搜索并勾选以下两个权限：
   - `wiki:wiki` — 读写知识库节点（**必选**）
   - `docx:document` — 读写文档内容块（**必选**）
2. 勾选后点「批量申请」

> ⚠ 如果是个人飞书（非企业版），这两个权限可能需要管理员审批。管理员是你自己时，直接在「审批」里通过即可。

**C. 发布应用版本**

1. 左侧点「版本管理与发布」→「创建版本」→ 填写版本号（如 `1.0.0`）→「保存」
2. 点「申请发布」→「确认发布」
3. 如果弹出「需要管理员审批」，用同一账号进入飞书管理后台审批通过

> ⚠ 常见问题：应用未发布时，在飞书文档的「分享」搜索框里**搜不到**这个应用。必须先发布才能作为协作者被添加。

---

### 第 1 步：GitHub 端——创建仓库

**1.1 配置 Git 身份（首次使用只需做一次，之后所有仓库自动继承）**

```powershell
git config --global user.name "yourname"
git config --global user.email "you@example.com"
```

> ⚠ 常见问题：`user.email` 必须和 GitHub 账号注册的邮箱一致，否则 commit 不会显示在贡献图上。

**1.2 在 GitHub 网站创建仓库**

1. 打开 [github.com](https://github.com) → 右上角「+」→「New repository」
2. Repository name 填：`qt-opencv-camera`
3. Private（团队项目）或 Public（开源）按需选择
4. **不要勾选**「Add a README file」（本地已有文件时勾了会冲突）
5. 点「Create repository」，复制页面上的 HTTPS 地址

**1.3 本地初始化并推送**

```powershell
cd Z:\qt_demo\EmbeddedQtTutorial\05_opencv_camera
git init
git add .
git commit -m "init: 初始化 Qt OpenCV 摄像头项目"
git remote add origin https://github.com/yourname/qt-opencv-camera.git
git push -u origin main
```

> ⚠ 常见问题 1：推送时弹出身份验证窗口，**密码处必须填 Personal Access Token**（不是 GitHub 登录密码）。
>
> ⚠ 常见问题 2：如果提示 `src refspec main does not match any`，说明还没有 commit，先执行 `git add .` 和 `git commit`。
>
> ⚠ 常见问题 3：如果提示 `remote: Repository not found`，检查仓库 URL 是否正确，以及 Token 是否有 `repo` 权限。

---

### 第 2 步：飞书端——创建项目专属页面

**2.1 新建空白页面**

1. 打开飞书知识库，左侧「+」→「新建页面」
2. 标题填：`Qt OpenCV 摄像头项目`
3. 创建后，浏览器地址栏会显示：
   ```
   https://your-tenant.feishu.cn/wiki/AbCdEfGhIjKlMnOpQrSt
   ```
   复制 `wiki/` 后面那段：`AbCdEfGhIjKlMnOpQrSt`，这就是本项目的 `FEISHU_WIKI_TOKEN`

**2.2 给应用授权**

1. 打开刚创建的新页面（确认浏览器地址栏里是这个页面的 URL）
2. 右上角「**···**」→「**分享**」→「**添加协作者**」
3. 搜索框里输入你的应用名称（就是在飞书开放平台里起的名字，如 `linux`）
4. 结果列表里找到带橙色「**应用**」标签的那条 → 右侧权限选「**可编辑**」→ 点「确认」

授权成功后，协作者列表里会出现应用名称和「可编辑」标记。

> ⚠ 常见问题 1：搜索框输入应用名但**没有结果** → 应用还没有发布。回飞书开放平台 → 版本管理与发布 → 申请发布 → 通过审批后再来搜。
>
> ⚠ 常见问题 2：授权完成但推送仍返回 **403 forBidden** → 授权的页面不对。必须打开**推送目标页面本身**去授权，在父页面或知识库根目录授权不会自动继承。
>
> ⚠ 常见问题 3：有很多页面都要授权，每次手动加太麻烦 → 在知识库根目录的「···」→「知识库设置」→「成员管理」→ 添加应用为「编辑者」，之后这个知识库里所有页面都自动有权限。

---

### 第 3 步：本地配置——接入自动化工具

**3.1 克隆本工具仓库（首次，只需做一次）**

```powershell
git clone https://github.com/777mygit/---github-ai-.git C:\tools\feishu-sync
cd C:\tools\feishu-sync
pip install -r feishu/requirements.txt
```

**3.2 配置本项目的环境变量**

```powershell
copy feishu\.env.example feishu\.env
```

用编辑器打开 `feishu\.env`，填入**本项目**的值：

```env
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FEISHU_WIKI_TOKEN=AbCdEfGhIjKlMnOpQrSt
FEISHU_OPEN_DOMAIN=https://open.feishu.cn
```

> ⚠ `.env` 文件已在 `.gitignore` 里，不会被 Git 追踪。如果 `git status` 里看到 `.env` 出现在「Changes to be committed」里，立刻 `git rm --cached feishu/.env` 取消追踪。

**3.3 验证连通性（干跑，不写入飞书）**

```powershell
python feishu/feishu_writer.py README.md --dry-run
```

预期输出：
```
[parse] 解析出 N 个单元（块/标题/列表等 X，表格 Y）
... (dry-run，未请求飞书)
```

如果解析没问题，正式推送：
```powershell
python feishu/feishu_writer.py README.md
```

预期输出：
```
[parse] 解析出 N 个单元
[auth] 获取 tenant_access_token ... ok
[wiki] node=AbCdEfGhIjKlMnOpQrSt -> document_id=xxxxxxxxxxxxxx
[write] 追加 N 个单元 ...
[done] 完成，去飞书刷新文档看看吧。
```

---

### 第 4 步：配置 GitHub Actions——云端自动同步

把 `.github/workflows/feishu-sync.yml` 复制到新项目仓库的相同路径下，然后在 **新项目仓库** 的 GitHub 页面配置 Secrets：

```
仓库 → Settings → Secrets and variables → Actions → New repository secret
```

| Secret 名称 | 值 | 每个仓库一样吗 |
| --- | --- | --- |
| `FEISHU_APP_ID` | 你的 App ID | **一样**（同一个飞书应用） |
| `FEISHU_APP_SECRET` | 你的 App Secret | **一样** |
| `FEISHU_WIKI_TOKEN` | 本项目飞书页面的 token | **每个仓库不同** ← 核心 |
| `OPENAI_API_KEY` | OpenAI Key（可选） | 按需 |

> **关键点**：`FEISHU_APP_ID` 和 `FEISHU_APP_SECRET` 在所有仓库里填一样的值（同一个飞书应用）。只有 `FEISHU_WIKI_TOKEN` 每个仓库填对应飞书页面的 token，**设置一次永远不用改**。
>
> ⚠ 常见问题：Actions 失败提示 `exit code 1` → 99% 是 Secrets 没配置或配置错误。去 Actions 日志里看具体报错，通常是 `401`（Secret 错）或 `403`（飞书页面没授权应用）。

---

## 一、飞书 + GitHub 联动：团队项目管理

> 适用于：团队协作项目，需要代码版本管理 + 飞书文档同步双轨并行。
> 每次 `git push`，GitHub Actions 自动把改动的 `.md` 文件同步到飞书，AI 同时生成变更摘要。

### 工作流程

```
写文档 → git add → git commit → git push
                        │               │
               post-commit 钩子      GitHub Actions
                        │               │
                   推送飞书（本地）  推送飞书（云端，团队共享）
                        └───────────────┘
                             飞书文档自动更新
```

### 文件示例：`book/chapters/bugfix-2026-04-23.md`

```markdown
## 修复：飞书 API 网络抖动导致推送中断

### 问题现象

推送大文档到飞书时，偶发 `ConnectionResetError(10054)` 导致脚本中断：
WinError 10054: 远程主机强迫关闭了一个现有的连接

频率约 1/5 次大文档推送，网络状况差时更高。

### 根本原因

飞书 API 服务器会主动关闭空闲过久的 HTTPS 连接。
当脚本处理 Markdown 解析耗时较长，再发请求时连接已被服务端回收。

### 解决方案

在 `feishu_writer.py` 的 `_call()` 方法中加入指数退避重试，
捕获 `ConnectionError / SSLError / OSError`，最多重试 4 次：

```python
for attempt in range(4):
    try:
        r = requests.request(...)
        return r.json()
    except (ConnectionError, SSLError, OSError) as e:
        wait = 3 * (attempt + 1)
        print(f"[retry] 网络错误，{wait}s 后重试（第{attempt+1}次）")
        time.sleep(wait)
raise RuntimeError("连续4次网络错误")
```

### 验证

连续推送 5 次 600+ 块的大文档，均在 1～2 次重试后成功，不再中断。

### 关键词

飞书 API、ConnectionResetError、网络抖动、重试、feishu_writer
```

**提交并同步**：

```powershell
git add book/chapters/bugfix-2026-04-23.md
git commit -m "fix: feishu_writer 加网络重试，解决大文档推送中断问题"
git push
# GitHub Actions 自动把这个文件推飞书
# AI 自动生成摘要：「修复飞书 API 网络抖动问题，加指数退避重试，P2 优先级」
```

**飞书里会出现**：
- 文件完整内容（含代码块、列表）自动追加到飞书文档
- AI 摘要块：改了什么 / 为什么 / 优先级，让不看代码的成员也能理解

---

## 二、只推飞书：个人三大场景

> 适用于：不需要 GitHub 版本管理的个人记录。
> 直接运行 `python feishu/feishu_writer.py 文件.md` 推送，**不走 Git，不走 Actions**。

### 快速命令

```powershell
# 推单个文件到飞书
python feishu/feishu_writer.py daily_log/2026-04-23.md

# 清空飞书文档后全量重写
python feishu/feishu_writer.py notes/2026-04-23_xxx.md --clear

# 只验证解析，不实际推送
python feishu/feishu_writer.py weekly/2026-W17.md --dry-run
```

> 什么时候用「只推飞书」：
> - 临时记录，不想污染 Git 历史
> - 个人日志、踩坑笔记、AI 上下文——这类内容只需要飞书可检索，不需要版本对比
> - 批量把旧文档迁移到飞书

---

### 场景二：个人开发日志 / 周报自动生成

**目标**：每天写几行日志，周五把本周日志汇总一下，周报就完成了。再也不需要专门抽时间写周报。

#### ① 每日日志：`daily_log/2026-04-23.md`

```markdown
# 2026-04-23 开发日志

## 今天做了什么

- 调通了 OV5640 摄像头 I2C 通信，根因是 RESET 引脚时序不够（<20ms）
- 写了字符设备驱动的 ioctl 接口，支持曝光和白平衡设置
- 阅读了正点原子 V4L2 章节，了解 VIDIOC_REQBUFS 的用法

## 遇到的问题

- v4l2-ctl 采图时偶发 EAGAIN，暂时用 select + 超时处理规避
  - 怀疑是 DMA 缓冲区分配不足（count=4），待查
- CMakeLists.txt 里 OpenCV 路径在 Ubuntu 22.04 上不对，已修复

## 明天计划

- 继续排查 EAGAIN 根因（DMA count 从 4 改到 8 试试）
- 实现自动曝光控制逻辑
```

**推送飞书**：

```powershell
# 方式一：只推飞书，不走 Git（最快）
python feishu/feishu_writer.py daily_log/2026-04-23.md

# 方式二：同时记录到 Git + 推飞书（post-commit 钩子自动触发推送）
git add daily_log/2026-04-23.md
git commit -m "log: 2026-04-23 日志，摄像头 I2C 调通"
# 不需要 git push，钩子已推飞书
```

#### ② 每周总结：`weekly/2026-W17.md`

```markdown
# 2026 年第 17 周工作总结（2026-04-20 ～ 2026-04-25）

## 本周完成

- OV5640 摄像头驱动调通，支持 I2C 控制曝光和白平衡
- 字符设备 ioctl 接口实现，已合入 main
- V4L2 流式采图接口验证通过（连续 1000 帧无丢帧）
- 解决 CMakeLists 在 Ubuntu 22.04 的兼容性问题
- 修复飞书 API 网络抖动问题（feishu_writer 加重试逻辑）

## 遗留问题

- 偶发 EAGAIN（频率约 1/500 帧），根因待查（P2 优先级）

## 下周计划

- 调查并修复偶发 EAGAIN（DMA 缓冲区数量问题）
- 实现自动曝光控制（AEC）
- 编写 V4L2 驱动使用文档
```

**推送飞书**：

```powershell
python feishu/feishu_writer.py weekly/2026-W17.md
# 飞书里自动归档，以后搜索「第17周」或「摄像头」就能找到
```

---

### 场景三：知识沉淀（踩坑记录）

**目标**：遇到问题解决后花 10 分钟写下来推飞书。新人遇到同样的坑，搜飞书直接找到，不需要再问人。

#### 文件示例：`notes/2026-04-23_feishu-api-retry.md`

```markdown
# 飞书 API 网络抖动导致推送中断 — 解决记录

## 环境

- OS：Windows 10
- Python：3.14
- 目标：feishu_writer.py 推送 600+ 块的大文档

## 问题现象

```bash
python feishu/feishu_writer.py _push_all.md --clear
# [parse] 解析出 614 个单元
# [auth] 获取 tenant_access_token ... ok
# [wiki] node=IZjQwbvTkixGMlkuoRVcRrVOnAh -> document_id=XhmDdU1...
# Traceback (most recent call last):
#   File ".../urllib3/connectionpool.py", line 464, in _make_request
#     self._validate_conn(conn)
# ConnectionResetError: [WinError 10054] 远程主机强迫关闭了一个现有的连接
```

出现概率：约 1/5 次大文档推送，网络状况差时更高。

## 排查过程

1. 首次出错以为是代码 bug，反复检查无误
2. 加日志发现错误发生在 `auth` 之后第一次 API 调用
3. 怀疑是服务端主动关闭了空闲连接：Markdown 解析耗时 > 连接 Keep-Alive 超时
4. 用 Wireshark 抓包确认：服务端发了 TCP RST

## 根本原因

飞书 API 服务端会关闭长时间空闲的 HTTPS 连接（约 30s）。
脚本解析 Markdown 时不发请求，连接被服务端回收，下次请求时报 `WinError 10054`。

## 解决方案

在 `feishu_writer.py` 的 `_call()` 方法加指数退避重试：

```python
for attempt in range(4):
    try:
        r = requests.request(method, url, headers=self._headers(), timeout=30, **kwargs)
        data = r.json()
        if data.get("code") not in (0, None):
            raise RuntimeError(f"API 失败: {data}")
        return data
    except (requests.exceptions.ConnectionError,
            requests.exceptions.SSLError,
            OSError) as e:
        wait = 3 * (attempt + 1)   # 3s, 6s, 9s, 12s
        print(f"[retry] 网络错误，{wait}s 后重试（第{attempt+1}次）: {e}")
        time.sleep(wait)
raise RuntimeError("连续4次网络错误，放弃")
```

## 验证

连续推送 5 次 600+ 块的大文档，均能在 1～2 次重试后成功，不再因网络抖动中断。

## 关键词

飞书 API、ConnectionResetError、WinError 10054、网络重试、feishu_writer、Windows
```

**推送飞书**：

```powershell
python feishu/feishu_writer.py notes/2026-04-23_feishu-api-retry.md
# 飞书里生成一篇完整的知识文章，搜索「ConnectionResetError」即可找到
```

> **最佳实践**：
> - 文件名格式：`YYYY-MM-DD_关键词.md`，方便按时间或关键词检索
> - 文末加「关键词」行，飞书全文搜索时命中率更高
> - 排查过程越详细越好，三个月后的你会感谢现在的自己

---

### 场景四：AI 上下文管理

**目标**：把每天和 AI 的讨论要点记录下来推飞书。下次开新对话时把记录文件贴给 AI，它立刻知道项目背景，不需要重新介绍。

#### 文件示例：`ai_context/2026-04-23.md`

```markdown
# AI 对话上下文记录 — 2026-04-23

## 项目背景

i.MX6ULL 开发板，编写 OV5640 MIPI 摄像头的 V4L2 驱动。
内核 5.15，工具链 arm-linux-gnueabihf-gcc 10.3。
本套 feishu_writer 自动把开发日志同步到飞书。

## 今日讨论要点

### 问题 1：飞书 API 网络抖动（已解决）
- **根因**：服务端关闭空闲 HTTPS 连接，脚本解析 Markdown 时不发请求
- **解法**：feishu_writer._call() 加指数退避重试（最多 4 次）
- **状态**：已验证，推 600+ 块大文档不再中断 ✅

### 问题 2：V4L2 采图偶发 EAGAIN（未解决）
- **现象**：VIDIOC_DQBUF 在约 1/500 帧返回 EAGAIN
- **AI 建议**：检查 VIDIOC_REQBUFS 的 count 参数，从 4 改到 8 试试
- **状态**：待验证，下次对话继续 ⏳

## 当前代码状态

```bash
git log --oneline -3
# a1b2c3d fix: feishu_writer 加网络重试逻辑
# 9e8f7a6 feat: ioctl 接口支持曝光和白平衡设置
# 5c4d3b2 init: 初始化项目
```

## 下次对话告诉 AI

1. 把这个文件内容贴给 AI 作为背景
2. EAGAIN 问题还没解决，DMA count=4 改到 8 还没试
3. 贴上 `dmesg | grep alloc` 的输出请 AI 分析
```

**推送飞书**：

```powershell
python feishu/feishu_writer.py ai_context/2026-04-23.md
# 飞书里按日期归档，跨日期搜索「EAGAIN」就能找到历史讨论结论
```

**下次开新对话时使用**：

```
[把 ai_context/2026-04-23.md 的内容粘贴给 AI]

"这是我昨天的项目上下文记录，请先读完再回答我的问题。
我今天想继续解决 EAGAIN 问题……"
```

---

## 切换到新项目时的完整清单

每开一个新项目，只需做以下事情：

```
✅ GitHub：创建新仓库，配置三个 Secrets
   - FEISHU_APP_ID    （和其他仓库一样）
   - FEISHU_APP_SECRET（和其他仓库一样）
   - FEISHU_WIKI_TOKEN（填这个项目飞书页面的 token ← 唯一不同的）

✅ 飞书：新建页面，把应用加为「可编辑」协作者，复制 token

✅ 本地：更新 feishu/.env 里的 FEISHU_WIKI_TOKEN

✅ 复制 .github/workflows/feishu-sync.yml 到新仓库

完成。以后每次 git push 自动同步飞书，无需任何额外操作。
```

---

## 常见问题速查

| 现象 | 原因 | 解决方案 |
| --- | --- | --- |
| `401 Unauthorized` | App Secret 错误或已重置 | 更新 `.env` 和 GitHub Secrets |
| `403 forBidden` | 该飞书页面没有单独给应用授权 | 打开**该页面**分享 → 搜应用名 → 可编辑 |
| Actions `exit code 1` | Secrets 未配置或配置错误 | 检查仓库 Secrets 是否齐全 |
| `ConnectionResetError 10054` | 飞书服务端关闭了空闲连接 | 已内置重试逻辑，最多重试 4 次自动恢复 |
| 表格显示为纯文本 | 旧版 feishu_writer.py | 更新到最新版（`git pull` 本工具仓库） |
| 速度很慢 | 飞书 5 QPS 限制 + sleep 0.2s | 正常，500 块约需 100 秒 |
| 钩子没有触发 | Windows 下钩子文件名问题 | 确认 `.git/hooks/post-commit` **没有**文件扩展名 |
| `git push` 要求输入密码 | 没有配置 Token | 密码处填 GitHub Personal Access Token，不是登录密码 |
| 密钥不小心提交了 | 未加 `.gitignore` 或手动 add 了 .env | 立刻重置飞书 App Secret，删掉含密钥的 commit 记录 |

---

## 这套系统的意义

### 对团队

- **零成本交接**：新成员入职打开飞书就能看到项目完整历史和踩坑记录，第一天就能上手
- **文档永远最新**：文档和代码同一仓库，提交代码的同时文档自动更新，消灭「文档说 A 但代码是 B」
- **问题有迹可查**：每个 bug 修复都有 AI 摘要（改了什么 / 为什么 / 优先级），Code Review 有据可依
- **会议效率提升**：AI 自动汇总昨天所有 commit，站会前不需要每个人口头汇报「我昨天做了什么」

### 对个人

- **知识不再流失**：每次解决问题后花 10 分钟写踩坑记录推飞书，几个月后搜索就能找回思路
- **周报自动生成**：平时正常写日志，周五把本周日志汇总一下，周报就写完了
- **AI 上下文延续**：把历史对话总结推飞书，下次开新对话把文件贴给 AI，不需要重新介绍项目背景

### 对知识管理

- **飞书全文检索**：所有文档在飞书里，搜索「ConnectionResetError」秒出历史解决方案，比翻聊天记录快 10 倍
- **结构化沉淀**：`notes/` 自动变成知识库，`weekly/` 自动变成周报存档，不需要额外维护
- **跨项目复用**：A 项目踩过的坑，B 项目的人在飞书里搜一下就能找到，知识在团队内流动

---

## 更新日志

| 版本 | 日期 | 变更内容 |
| --- | --- | --- |
| v1.4 | 2026-04-23 | `feishu_writer --clear` 改为循环分批删除（每次 50 个），解决飞书 `batch_delete` 单次上限导致大文档清空不彻底、内容重复的问题 |
| v1.3 | 2026-04-23 | `feishu_writer._call()` 加指数退避重试（最多 4 次），解决大文档推送时网络抖动中断问题 |
| v1.3 | 2026-04-23 | Actions 和 post-commit 钩子新增监控 `daily_log/` `weekly/` `notes/` `ai_context/` 目录 |
| v1.3 | 2026-04-23 | 文档重构：两类使用模式分类，新增个人三大场景详细示例 |
| v1.2 | 2026-04-20 | 加入知识库级别授权说明，完善常见问题速查 |
| v1.1 | 2026-04-18 | 修复 Actions 正则匹配 README.md，升级 pip cache |
| v1.0 | 2026-04-15 | 初始版本：Markdown → 飞书、本地钩子、GitHub Actions、AI 摘要 |

---

## 扩展路线图

- [x] Markdown → 飞书块转换（含表格、代码高亮）
- [x] 本地 post-commit 钩子（提交即同步）
- [x] GitHub Actions 云端同步（支持手动全量重建）
- [x] AI 变更摘要（OpenAI，无 Key 时降级为 commit message）
- [x] 创建新飞书子页面工具（create_wiki_page.py）
- [x] 一个项目一个仓库一个飞书页面的标准化模式
- [x] 网络抖动自动重试（指数退避，最多 4 次）
- [x] 个人三大场景（日志/踩坑/AI上下文）目录监控
- [x] `--clear` 分批删除，彻底清空不留残块
- [ ] 每章/每文件独立 Wiki 子页面（实现文件级覆盖）
- [ ] GitHub Issue ↔ 飞书 Bitable 双向同步
- [ ] 每日站会摘要定时发送到飞书群
- [ ] PR 合并自动生成版本说明推送飞书群消息

---

## 许可

MIT License — 自由使用，欢迎 PR。
