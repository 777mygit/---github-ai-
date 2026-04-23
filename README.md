# 飞书 × GitHub × AI 团队项目管理自动化

> 用 Git 管版本，用 AI 写摘要，用飞书做文档——三者联动，提交即同步。

## 项目简介

本项目提供一套开箱即用的自动化工具链，实现：

- `git commit` → **自动把改动的 Markdown 章节推送到飞书文档**
- `git push` → **GitHub Actions 云端同步**，团队成员提交自动触发
- `git diff` → **AI（GPT/本地模型）生成变更摘要**，写入飞书变更日志
- 飞书 Bitable 看板记录每次改动的优先级、负责人、问题状态

```
开发者 ──commit──► Git/GitHub ──Actions──► feishu_writer.py ──► 飞书 Wiki
                       │                        ▲
                  post-commit hook ─────────────┘
                       │
                  ai_summarize.py ──► OpenAI ──► 飞书变更日志
```

## 目录结构

```
.
├── feishu/
│   ├── feishu_writer.py      # 核心：Markdown → 飞书块，支持表格/代码/标题/列表
│   ├── ai_summarize.py       # AI 摘要：git diff → GPT → 飞书变更日志
│   ├── .env.example          # 环境变量模板
│   ├── .gitignore            # 排除 .env
│   └── requirements.txt      # Python 依赖
├── .github/
│   └── workflows/
│       └── feishu-sync.yml   # GitHub Actions 自动同步
├── .git/
│   └── hooks/
│       └── post-commit       # 本地钩子（提交后自动推飞书）
├── book/
│   └── chapters/             # Markdown 章节文件
└── README.md
```

## 快速开始

### 第 1 步：创建飞书企业自建应用

1. 进入 [飞书开放平台](https://open.feishu.cn/app) → **创建企业自建应用**
2. 复制 **App ID** 和 **App Secret**
3. 申请以下权限并发布：
   - `wiki:wiki` — 读写知识库
   - `docx:document` — 读写文档块
4. 打开目标飞书文档 → **分享** → 添加应用为「可编辑」协作者

### 第 2 步：本地配置

```bash
# 克隆项目
git clone https://github.com/777mygit/---github-ai-.git
cd ---github-ai-

# 安装 Python 依赖
pip install -r feishu/requirements.txt

# 配置环境变量
cp feishu/.env.example feishu/.env
```

编辑 `feishu/.env`：

```env
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FEISHU_WIKI_TOKEN=MLwKwZkgPiqgALkWVTEcI0Gjnmf   # URL 中 wiki/ 后面那段
FEISHU_OPEN_DOMAIN=https://open.feishu.cn
```

### 第 3 步：验证连通性

```bash
# 把某个 md 文件推到飞书（追加模式）
python feishu/feishu_writer.py book/chapters/06_信号.md

# 预期输出：
# [parse] 解析出 N 个单元
# [auth] 获取 tenant_access_token ... ok
# [wiki] node=MLwK... -> document_id=X30J...
# [write] 追加 N 个单元 ...
# [done] 完成，去飞书刷新文档看看吧。
```

### 第 4 步：启用本地 post-commit 钩子

把 `.git/hooks/post-commit` 设为可执行（Linux/Mac）：

```bash
chmod +x .git/hooks/post-commit
```

Windows 下直接生效（Git for Windows 自带 bash 执行钩子）。

之后每次 `git commit`，钩子自动检测改动的 `.md` 文件并推飞书。

### 第 5 步：配置 GitHub Actions（团队协作）

在 GitHub 仓库 **Settings → Secrets and variables → Actions** 添加：

| Secret 名称 | 值 |
|---|---|
| `FEISHU_APP_ID` | 飞书 App ID |
| `FEISHU_APP_SECRET` | 飞书 App Secret |
| `FEISHU_WIKI_TOKEN` | 飞书 Wiki Token |
| `OPENAI_API_KEY` | OpenAI Key（可选，用于 AI 摘要） |

之后 `git push` 时，Actions 自动把改动章节同步到飞书。

---

## 完整实例演示

### 场景：学完第 6 章信号，补充内容后同步飞书

**第 1 步：在编辑器里更新章节**

```markdown
<!-- book/chapters/06_信号.md 末尾新增 -->

## 补充：查看所有信号

`kill -l` 列出系统支持的全部信号编号与名称：

```
 1) SIGHUP    2) SIGINT    3) SIGQUIT   4) SIGILL
 9) SIGKILL  15) SIGTERM  17) SIGCHLD  19) SIGSTOP
```

实时场景：调试时用 `kill -SIGTERM <pid>` 优雅终止进程。
```

**第 2 步：提交**

```powershell
cd d:\linux
git add book\chapters\06_信号.md
git commit -m "ch06: 补充 kill -l 信号列表及实战说明"
```

**第 3 步：钩子自动触发，终端输出**

```
==========================================
[feishu-hook] post-commit 触发
==========================================
[feishu-hook] 改动的章节文件：
book/chapters/06_信号.md
------------------------------------------
[feishu-hook] 推送章节: book/chapters/06_信号.md
[parse] 解析出 42 个单元（块/标题/列表等 40，表格 2）
[auth] 获取 tenant_access_token ... ok
[wiki] node=MLwKwZkgPiqgALkWVTEcI0Gjnmf -> document_id=X30JdBRdToQb6ZxXTIbcPIifnce
[write] 追加 42 个单元 ...
[done] 完成，去飞书刷新文档看看吧。
------------------------------------------
[feishu-hook] 生成 AI 变更摘要...
[ai_summarize] 正在生成 AI 摘要...
[ai_summarize] 摘要：
1. **改动内容**：在第 6 章末尾新增「查看所有信号」一节，补充 kill -l 命令输出示例及实战终止场景说明
2. **改动原因**：完善信号章节的实用性，帮助读者快速查阅信号编号与实际调试用法
3. **优先级评估**：P2（一般）——属于内容补充，不影响现有功能，可随时合并
[ai_summarize] 摘要已推送到飞书
==========================================
[feishu-hook] 完成
==========================================
```

**第 4 步：去飞书刷新，新内容已出现在文档末尾**

---

## 核心脚本说明

### feishu_writer.py

```
用法：
  python feishu_writer.py <file.md>           # 追加模式
  python feishu_writer.py <file.md> --clear   # 清空后重写（覆盖整页）
  python feishu_writer.py <file.md> --dry-run # 只解析不发网络请求

支持的 Markdown 元素：
  # ~ ###### 标题   → 飞书 heading1~heading9 块
  正文段落          → text 块，支持 **粗体** *斜体* `code` [链接](url)
  - 无序列表        → bullet 块
  1. 有序列表       → ordered 块
  > 引用            → quote 块
  ``` 代码块        → code 块（自动识别语言高亮）
  | 表格 |          → 飞书原生 table 块（嵌套结构）
```

### ai_summarize.py

```
用法（在 post-commit 钩子中）：
  git diff HEAD~1 | python feishu/ai_summarize.py

输出三段摘要：
  1. 改动内容
  2. 改动原因
  3. 优先级评估（P0/P1/P2）

无 OPENAI_API_KEY 时自动降级为 commit message 原文
```

---

## 常见问题

| 现象 | 原因 | 解决方案 |
|---|---|---|
| `401 Unauthorized` | App Secret 错误或 token 过期 | 检查 `.env`，重新获取 token |
| `403 Forbidden` | 应用没有文档编辑权限 | 飞书文档分享 → 添加应用为协作者 |
| 表格显示为文本 | 旧版 feishu_writer.py | 更新到最新版（支持 `/descendant` API） |
| 速度很慢 | 飞书 5 QPS 限制 | 正常现象，500 块约需 100 秒 |
| 钩子没有触发 | Windows 权限问题 | 确认 `.git/hooks/post-commit` 无扩展名 |

---

## 扩展路线图

- [x] Markdown → 飞书块转换（含表格）
- [x] 本地 post-commit 钩子
- [x] GitHub Actions 云端同步
- [x] AI 变更摘要（OpenAI）
- [ ] 每章独立 Wiki 子页面（章节级覆盖）
- [ ] GitHub Issue ↔ 飞书 Bitable 双向同步
- [ ] 每日站会摘要定时发送到飞书群
- [ ] PR 合并自动生成版本说明

---

## 许可

MIT License — 自由使用，欢迎 PR。
