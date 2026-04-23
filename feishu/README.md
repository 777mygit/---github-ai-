# 把 Markdown 写入飞书 Wiki 文档

本目录提供一个 Python 脚本 `feishu_writer.py`，用飞书开放平台 OpenAPI 把一份本地 Markdown
追加写入指定的 Wiki 文档（新版文档 docx）。

## 一、在飞书开放平台创建自建应用

1. 打开 <https://open.feishu.cn/app>，点击「创建企业自建应用」。
2. 填名称、图标后进入应用，在「凭证与基础信息」里拿到：
   - `App ID`（形如 `cli_xxxxxxxxxxxxxxxx`）
   - `App Secret`
3. 左侧「权限管理」里勾选并发布以下权限（最小集）：
   - `wiki:wiki`（或更细的 `wiki:node:read`）：读取 wiki 节点，用来把链接里的 token 解析成文档 ID
   - `docx:document`：读写云文档
   - （可选）`drive:drive`：读 drive 元数据
4. 左侧「版本管理与发布」里创建一个版本并提交发布，等管理员审批通过；如果你自己就是管理员，直接通过即可。

## 二、把文档授权给这个应用

OpenAPI 使用 `tenant_access_token` 调用时，应用必须对该文档有权限。两种做法任选：

- **推荐**：打开目标文档（你的链接
  <https://ncnte6r0dba2.feishu.cn/wiki/MLwKwZkgPiqgALkWVTEcI0Gjnmf>），右上角「共享」→ 把你的自建应用添加为**可编辑**协作者。
- 或：在 Wiki 的知识库「设置 → 管理应用」里把该应用加到知识库。

> 如果报 `permission denied` 之类错误，99% 都是这一步没做或权限不够。

## 三、本地配置环境

```powershell
cd d:\linux\feishu
pip install -r requirements.txt
copy .env.example .env
notepad .env        # 填 App ID / App Secret，WIKI_TOKEN 默认已填好
```

`FEISHU_WIKI_TOKEN` 就是 URL 最后一段：
```
https://ncnte6r0dba2.feishu.cn/wiki/MLwKwZkgPiqgALkWVTEcI0Gjnmf
                                     ^^^^^^^^^^^^^^^^^^^^^^^^^^
```

## 四、写入文档

```powershell
# 先用 dry-run 验证 Markdown 能被正确解析成飞书块
python feishu_writer.py ..\Linux应用开发大全.md --dry-run

# 正式写入（追加到文档末尾）
python feishu_writer.py ..\Linux应用开发大全.md

# 或者：先清空原有内容再写（慎用）
python feishu_writer.py ..\Linux应用开发大全.md --clear
```

## 五、脚本支持的 Markdown 语法

| Markdown                | 飞书块类型   |
| ----------------------- | ------------ |
| `# ~ #########`         | heading1-9   |
| 普通段落                | text         |
| `- / * / +` 开头        | bullet 列表  |
| `1. / 2.` 开头          | ordered 列表 |
| `> ...`                 | quote        |
| ` ```lang ... ``` `     | code，自动识别语言 |
| `**bold**` `*italic*`   | 行内加粗/斜体 |
| `` `code` ``            | 行内代码     |
| `[label](url)`          | 超链接       |

不支持的语法（图片、表格、嵌套列表）会被当纯文本处理——如果 Linux 文档里没用到这些，就完全够。

## 六、常见错误

| 报错 | 原因 | 处理 |
| --- | --- | --- |
| `99991663 app ticket not found` | 应用还未发布 | 到开放平台「版本管理」里发布 |
| `1254040 permission denied` | 没把应用加为协作者 | 文档→共享→加入应用为可编辑 |
| `obj_type='doc'` 报错 | 节点是老版文档（云文档 doc），不是 docx | 在飞书里把老文档迁到新版文档 docx |
| 写入成功但没内容 | 很可能写到别的文档了 | 检查 `FEISHU_WIKI_TOKEN` 是不是 URL 里那段 |
