# 第 10 章 接入飞书 OpenAPI：自动把 Markdown 写入飞书文档

> 本章以本书自身的生产工具 `feishu_writer.py` 为主线，完整剖析"Markdown 文件 → 飞书云文档"的每一个环节：鉴权、地址解析、Markdown 解析、块构造、分批写入、表格嵌套树。所有代码均为本书实际在用的版本。

## 10.1 为什么要自动化

手动在飞书写文档的痛点：

- **格式不统一**：不同时间、不同人写出来结构差异大
- **更新滞后**：代码/笔记改了，文档还是旧的
- **重复劳动**：每次学完一个知识点，手动粘贴代码块、调整标题层级耗时很长
- **版本追踪弱**：飞书有历史记录，但和 Git 不联动，无法 `git diff`

本章工具链实现的效果：

```
你写 .md 文件（支持标题/代码/表格/列表/引用/行内样式）
    │
    ▼  python feishu_writer.py notes.md
    │
    ▼  飞书文档自动刷新，标题、代码块、表格全部正确渲染
```

## 10.2 飞书 OpenAPI 的核心概念

### 应用类型与 Token 体系

飞书开放平台有两大类应用，本章使用最简单的**企业自建应用**：

```
飞书开放平台 https://open.feishu.cn/app
  └─ 创建「企业自建应用」
       ├─ App ID：cli_a9636f488a789cd4       （公开标识符）
       └─ App Secret：W5hGOiHA7Lch9l...     （私密，绝不放代码里）
```

调用任何 API 前必须先换取 `tenant_access_token`（代表应用以企业名义操作，有效期 7200 秒）：

```
POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal
Body: {"app_id": "cli_xxx", "app_secret": "xxx"}

Response:
{
  "code": 0,
  "tenant_access_token": "t-xxxxxxxxxxxxxxxx",
  "expire": 7200
}
```

此后所有请求带 `Authorization: Bearer <tenant_access_token>` 头即可。

### Wiki 节点 vs docx 文档

飞书的知识库（Wiki）和云文档（docx）是两个层次：

```
知识库 Wiki
  └─ 节点（Node）—— URL 里那段 token：MLwKwZkgPiqgALkWVTEcI0Gjnmf
       └─ 底层文档（docx）—— 真正的 document_id：X30JdBRdToQb6ZxXTIbcPIifnce
```

所以写文档前必须先做一次转换：

```
GET /open-apis/wiki/v2/spaces/get_node?token=MLwKwZkgPiqgALkWVTEcI0Gjnmf&obj_type=wiki

Response:
{
  "data": {
    "node": {
      "obj_type": "docx",                     ← 必须是 docx，不是老版 doc
      "obj_token": "X30JdBRdToQb6ZxXTIbcPIifnce"  ← 这就是 document_id
    }
  }
}
```

### 飞书文档的块（Block）结构

飞书新版文档（docx）是一棵**块树**，根节点的 `block_id` 等于 `document_id`，所有内容块都挂在根节点下：

```
Document（根块 block_id = X30JdBRdToQb6ZxXTIbcPIifnce）
  ├── block_type=3  heading1："第 1 章 开发环境"
  ├── block_type=2  text："正文段落..."
  ├── block_type=14 code：C 语言代码
  ├── block_type=31 table：表格
  │    ├── block_type=32 table_cell（单元格）
  │    │    └── block_type=2  text："列标题"
  │    └── ...（行×列 个单元格）
  └── block_type=12 bullet："列表项"
```

块类型编号（本书用到的）：

| block_type | 类型名 | 说明 |
| --- | --- | --- |
| 2 | text | 普通段落 |
| 3 | heading1 | 一级标题 |
| 4~11 | heading2~9 | 二到九级标题 |
| 12 | bullet | 无序列表项 |
| 13 | ordered | 有序列表项 |
| 14 | code | 代码块 |
| 15 | quote | 引用块 |
| 31 | table | 表格 |
| 32 | table_cell | 单元格 |

## 10.3 脚本架构总览

`feishu_writer.py` 分三层：

```
┌─────────────────────────────────────────────────────┐
│  main()                                             │
│  · 解析命令行参数                                    │
│  · 读 .md 文件                                       │
│  · 调 markdown_to_blocks() 获得 unit 列表            │
│  · 驱动 FeishuClient 写入                            │
└────────────────┬────────────────────────────────────┘
                 │
  ┌──────────────▼──────────────┐
  │  Markdown 解析层             │
  │  markdown_to_blocks()        │
  │  _parse_inline()             │
  │  _heading_block()            │
  │  _simple_block()             │
  │  _code_block()               │
  │  _table_unit()               │
  └──────────────┬──────────────┘
                 │
  ┌──────────────▼──────────────┐
  │  FeishuClient               │
  │  · _tenant_token()  鉴权续期 │
  │  · wiki_node_to_doc_id()    │
  │  · list_children()          │
  │  · delete_children()        │
  │  · append_children()        │
  │  · append_descendant()      │
  └─────────────────────────────┘
```

## 10.4 第一步：鉴权与 Token 自动续期

飞书的 `tenant_access_token` 有效期是 7200 秒（2 小时）。写大文档时如果超时，后续请求会失败。脚本用**懒续期**策略：每次调用 API 前检查是否快过期，是则重新换取：

```python
class FeishuClient:
    def __init__(self, app_id: str, app_secret: str,
                 domain: str = "https://open.feishu.cn"):
        self.app_id = app_id
        self.app_secret = app_secret
        self.domain = domain.rstrip("/")
        self._token: str | None = None
        self._token_expire_at: float = 0   # Unix 时间戳

    def _tenant_token(self) -> str:
        # 提前 60 秒判断过期，避免临界时刻 token 刚好失效
        if self._token and time.time() < self._token_expire_at - 60:
            return self._token

        r = requests.post(
            f"{self.domain}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败: {data}")

        self._token = data["tenant_access_token"]
        # expire 字段是秒数，加上当前时间得到绝对过期时刻
        self._token_expire_at = time.time() + int(data.get("expire", 7200))
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._tenant_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _call(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.domain}{path}"
        r = requests.request(method, url,
                             headers=self._headers(), timeout=30, **kwargs)
        try:
            data = r.json()
        except ValueError:
            r.raise_for_status()
            raise
        # 飞书所有接口：code=0 成功，其他为错误
        if data.get("code") not in (0, None):
            raise RuntimeError(f"{method} {path} 失败: {data}")
        return data
```

**为什么用 `_call` 统一封装？**  
飞书 API 返回的 HTTP 状态码不完全可信（部分错误返回 200 但 body 里 code≠0）。统一在 `_call` 里检查 `data["code"]`，避免每个调用点重复判断。

## 10.5 第二步：Wiki Token → Document ID

从 URL 取到的是 Wiki 节点 token，但文档块操作 API 需要 `document_id`。这两者不同：

```python
def wiki_node_to_doc_id(self, wiki_token: str) -> str:
    """
    参考 API：
    GET /open-apis/wiki/v2/spaces/get_node
    https://open.feishu.cn/document/server-docs/docs/wiki-v2/space-node/get_node
    """
    data = self._call(
        "GET",
        f"/open-apis/wiki/v2/spaces/get_node"
        f"?token={wiki_token}&obj_type=wiki",
    )
    node = data["data"]["node"]
    obj_type = node.get("obj_type")

    # 飞书有新版文档（docx）和老版文档（doc），块 API 只支持 docx
    if obj_type != "docx":
        raise RuntimeError(
            f"该 wiki 节点类型为 {obj_type!r}，"
            f"当前脚本只支持新版文档 docx。"
            f"请在飞书里把文档迁移到新版。"
        )
    return node["obj_token"]   # 这就是 document_id
```

本书这个文档转换结果：

```
wiki_token  = MLwKwZkgPiqgALkWVTEcI0Gjnmf
document_id = X30JdBRdToQb6ZxXTIbcPIifnce
```

## 10.6 第三步：可选清空（--clear 模式）

`--clear` 先获取文档根块的所有直接子块，再批量删除，然后再写入。这样能保证文档内容是最新版，不会有残留旧内容。

### 列出子块（带分页）

飞书列表接口默认分页，用 `page_token` 循环取完：

```python
def list_children(self, document_id: str, block_id: str) -> list[dict]:
    """
    参考 API：
    GET /open-apis/docx/v1/documents/{document_id}/blocks/{block_id}/children
    https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document-block/list
    """
    blocks = []
    page_token = ""
    while True:
        q = "?page_size=500"
        if page_token:
            q += f"&page_token={page_token}"
        data = self._call(
            "GET",
            f"/open-apis/docx/v1/documents/{document_id}"
            f"/blocks/{block_id}/children{q}",
        )
        blocks.extend(data["data"].get("items", []))
        page_token = data["data"].get("page_token", "")
        if not data["data"].get("has_more") or not page_token:
            break
    return blocks
```

### 批量删除子块

```python
def delete_children(self, document_id: str, block_id: str,
                    start: int, end: int) -> None:
    """
    参考 API：
    DELETE /open-apis/docx/v1/documents/{document_id}/blocks/{block_id}/children/batch_delete
    https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document-block/batch_delete
    Body: {"start_index": 0, "end_index": N}   # [start, end) 左闭右开
    """
    self._call(
        "DELETE",
        f"/open-apis/docx/v1/documents/{document_id}"
        f"/blocks/{block_id}/children/batch_delete",
        json={"start_index": start, "end_index": end},
    )
```

## 10.7 第四步：Markdown 解析器

这是脚本的核心部分。解析器把 Markdown 文本转换成两种 unit：

```python
# unit 类型 1：普通块（段落/标题/列表/代码/引用）
{"kind": "simple", "block": <飞书块字典>}

# unit 类型 2：嵌套块（表格，需要用 /descendant API）
{"kind": "descendant", "children_id": [...], "descendants": [...]}
```

### 主扫描循环

`markdown_to_blocks` 按行逐一识别，优先级从高到低：

```python
TABLE_SEP_RE = re.compile(
    r"^\s*\|?(\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$"
)

def markdown_to_blocks(md: str) -> list[dict]:
    lines = md.splitlines()
    units: list[dict] = []
    i = 0
    while i < len(lines):
        raw = lines[i]

        # 优先级 1：代码围栏 ```lang
        m = re.match(r"^```(\w*)\s*$", raw)
        if m:
            lang = m.group(1).lower()
            i += 1
            buf = []
            # 收集代码块内容，直到遇到结束 ```
            while i < len(lines) and not re.match(r"^```\s*$", lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1   # 跳过结束 ```
            units.append({"kind": "simple",
                          "block": _code_block("\n".join(buf), lang)})
            continue

        # 优先级 2：ATX 标题 # ~ #########
        m = re.match(r"^(#{1,9})\s+(.*)$", raw)
        if m:
            level = len(m.group(1))
            units.append({"kind": "simple",
                          "block": _heading_block(level, m.group(2).strip())})
            i += 1
            continue

        # 优先级 3：引用 > ...
        if raw.startswith("> "):
            units.append({"kind": "simple",
                          "block": _simple_block(15, raw[2:])})
            i += 1
            continue

        # 优先级 4：表格（当前行有 | 且下一行是 --- 分隔行）
        if "|" in raw and i + 1 < len(lines) and TABLE_SEP_RE.match(lines[i+1]):
            header = _split_table_row(raw)
            rows = [header]
            j = i + 2   # 跳过分隔行
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                rows.append(_split_table_row(lines[j]))
                j += 1
            units.append(_table_unit(rows))
            i = j
            continue

        # 优先级 5：无序列表 - / * / +
        m = re.match(r"^[\-\*\+]\s+(.*)$", raw)
        if m:
            units.append({"kind": "simple",
                          "block": _simple_block(12, m.group(1))})
            i += 1
            continue

        # 优先级 6：有序列表 1. / 2) ...
        m = re.match(r"^\d+[\.\)]\s+(.*)$", raw)
        if m:
            units.append({"kind": "simple",
                          "block": _simple_block(13, m.group(1))})
            i += 1
            continue

        # 优先级 7：空行，跳过
        if raw.strip() == "":
            i += 1
            continue

        # 优先级 8：普通段落（合并相邻普通行）
        para = [raw]
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if (nxt.strip() == ""
                    or re.match(r"^```", nxt)
                    or re.match(r"^#{1,9}\s+", nxt)
                    or nxt.startswith("> ")
                    or re.match(r"^[\-\*\+]\s+", nxt)
                    or re.match(r"^\d+[\.\)]\s+", nxt)
                    or ("|" in nxt and j+1 < len(lines)
                        and TABLE_SEP_RE.match(lines[j+1]))):
                break
            para.append(nxt)
            j += 1
        units.append({"kind": "simple",
                      "block": _simple_block(2, " ".join(s.strip() for s in para))})
        i = j

    return units
```

### 行内样式解析：_parse_inline

每个块的文本内容不是简单字符串，而是 `text_run` 元素列表。`_parse_inline` 用正则提取行内样式：

```python
def _parse_inline(text: str) -> list[dict]:
    """
    支持：**bold** | *italic* | `inline_code` | [label](url)
    未匹配的部分输出为纯文本 text_run。
    """
    pattern = re.compile(
        r"(\*\*(?P<b>[^*]+)\*\*)"           # **加粗**
        r"|(\*(?P<i>[^*\n]+)\*)"             # *斜体*
        r"|(`(?P<c>[^`\n]+)`)"               # `行内代码`
        r"|(\[(?P<l>[^\]]+)\]\((?P<u>[^)]+)\))"  # [链接文字](url)
    )
    elements = []
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            elements.append(_run(text[pos:m.start()]))   # 中间的纯文本
        if m.group("b"):
            elements.append(_run(m.group("b"), bold=True))
        elif m.group("i"):
            elements.append(_run(m.group("i"), italic=True))
        elif m.group("c"):
            elements.append(_run(m.group("c"), inline_code=True))
        elif m.group("l"):
            elements.append(_run(m.group("l"), link=m.group("u")))
        pos = m.end()
    if pos < len(text):
        elements.append(_run(text[pos:]))
    if not elements:
        elements.append(_run(""))   # 空行也要有至少一个元素
    return elements
```

`_run` 构造单个 `text_run` 字典（飞书 docx 的原子文本单元）：

```python
def _run(content: str, *, bold=False, italic=False,
         inline_code=False, link: str | None = None) -> dict:
    style = {}
    if bold:        style["bold"]        = True
    if italic:      style["italic"]      = True
    if inline_code: style["inline_code"] = True
    if link:
        from urllib.parse import quote
        # 飞书要求 link.url 必须百分号编码
        style["link"] = {"url": quote(link, safe="")}
    return {"text_run": {"content": content, "text_element_style": style}}
```

### 标题块构造

飞书 heading1~9 的 block_type 是 3~11（规律：`block_type = level + 2`）：

```python
HEADING_TYPE = {i: i + 2 for i in range(1, 10)}  # {1:3, 2:4, ..., 9:11}

def _heading_block(level: int, text: str) -> dict:
    level = min(max(level, 1), 9)
    bt  = HEADING_TYPE[level]       # 3~11
    key = f"heading{level}"         # "heading1"~"heading9"
    return {
        "block_type": bt,
        key: {"elements": _parse_inline(text), "style": {}},
    }
```

示例：`## 第 2 章` → `block_type=4, heading2:{elements:[...], style:{}}`

### 代码块构造

飞书代码块的语言用整数枚举，脚本维护一张映射表把字符串转成枚举值：

```python
LANG_MAP = {
    "c": 10, "cpp": 9, "c++": 9, "python": 49, "py": 49,
    "bash": 7, "sh": 60, "shell": 60, "go": 22, "rust": 53,
    "java": 29, "javascript": 30, "js": 30, "typescript": 63,
    "makefile": 38, "cmake": 68, "yaml": 67, "json": 28,
    # ... 共 70+ 种语言
}

def _code_block(content: str, lang: str) -> dict:
    language = LANG_MAP.get(lang.lower(), 1)   # 1 = plain text
    return {
        "block_type": 14,
        "code": {
            "elements": [_run(content)],       # 代码块里只有一个 text_run
            "style": {"language": language, "wrap": True},
        },
    }
```

### 表格块构造（最复杂的部分）

表格在飞书里是三层嵌套结构：`table → table_cell → text`。普通的 `/children` 接口无法一次性创建这种嵌套，必须用 `/descendant` 接口提交整棵子树：

```python
def _tmp_id() -> str:
    """生成临时 block_id，飞书 /descendant 接口需要提前分配好 ID"""
    return "t_" + uuid.uuid4().hex[:16]

def _table_unit(rows: list[list[str]]) -> dict:
    row_size = len(rows)
    col_size = max(len(r) for r in rows)
    # 补齐每行到相同列数
    rows = [r + [""] * (col_size - len(r)) for r in rows]

    table_id  = _tmp_id()
    cell_ids  = []
    descendants = []   # 所有后代块的扁平列表

    # 按行主序遍历：每个单元格 = table_cell + text
    for r in rows:
        for cell_text in r:
            cid = _tmp_id()    # table_cell 的临时 ID
            tid = _tmp_id()    # 单元格内 text 块的临时 ID
            cell_ids.append(cid)

            # table_cell 块
            descendants.append({
                "block_id":   cid,
                "block_type": 32,           # table_cell
                "children":   [tid],        # 声明子块
                "table_cell": {},
            })
            # text 块（在单元格内）
            descendants.append({
                "block_id":   tid,
                "block_type": 2,            # text
                "text": {
                    "elements": _parse_inline(cell_text),  # 支持行内样式
                    "style": {},
                },
            })

    # table 块本身
    table_block = {
        "block_id":   table_id,
        "block_type": 31,                   # table
        "children":   cell_ids,             # 所有 table_cell 的 ID
        "table": {
            "property": {
                "row_size":     row_size,
                "column_size":  col_size,
                "column_width": [120] * col_size,
                "header_row":   True,       # 第一行设为表头样式
            }
        },
    }

    return {
        "kind":        "descendant",
        "children_id": [table_id],          # 直接挂到文档根块的子节点
        "descendants": [table_block, *descendants],  # 整棵子树
    }
```

## 10.8 第五步：分批写入飞书

飞书 `/children` 接口单次最多接受 **50 个块**，超出会报错。`append_children` 自动分批：

```python
def append_children(self, document_id: str, block_id: str,
                    children: list[dict]) -> None:
    """
    参考 API：
    POST /open-apis/docx/v1/documents/{document_id}/blocks/{block_id}/children
    https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document-block/create
    Body: {"children": [...最多50个...], "index": -1}
    index=-1 表示追加到末尾
    """
    CHUNK = 50
    for i in range(0, len(children), CHUNK):
        batch = children[i : i + CHUNK]
        self._call(
            "POST",
            f"/open-apis/docx/v1/documents/{document_id}"
            f"/blocks/{block_id}/children?document_revision_id=-1",
            json={"children": batch, "index": -1},
        )
        # 飞书写接口约 5 QPS 限制，sleep 0.2s 规避
        time.sleep(0.2)
```

**`document_revision_id=-1` 是什么？**  
飞书文档有乐观锁：每次修改后版本号 +1，写入时可以带上当前版本号做校验（传错会报 409 冲突）。`-1` 是特殊值，表示"不校验版本，直接追加"，适合脚本这种强制覆盖的场景。

### 表格专用的 /descendant 接口

```python
def append_descendant(self, document_id: str, parent_block_id: str,
                      children_id: list[str], descendants: list[dict]) -> None:
    """
    参考 API：
    POST /open-apis/docx/v1/documents/{document_id}/blocks/{parent_block_id}/descendant
    https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document-block/create-descendant
    Body:
    {
      "children_id":  ["t_table_id"],          ← 直接子块 ID
      "index": -1,                              ← 追加位置
      "descendants": [table_block, cell, text, cell, text, ...]  ← 整棵子树
    }
    """
    self._call(
        "POST",
        f"/open-apis/docx/v1/documents/{document_id}"
        f"/blocks/{parent_block_id}/descendant?document_revision_id=-1",
        json={
            "children_id": children_id,
            "index": -1,
            "descendants": descendants,
        },
    )
    time.sleep(0.2)
```

**为什么表格不能用 /children？**  
`/children` 只能创建单层块，无法同时指定子树结构。表格的 table_cell 和 table_cell 里的 text 块必须一次性提交，否则飞书会报"孤立块"错误。`/descendant` 接口接受一个扁平列表，但每个块都声明了自己的 `children`，内核重新组装成树。

## 10.9 第六步：主流程驱动

主流程是一个**flush 缓冲模式**：普通块累积到 buf 里批量发，遇到表格（descendant）就先 flush 普通块，再单独发表格：

```python
def main():
    load_dotenv()   # 从 .env 文件读环境变量
    # ...参数解析、读文件...

    units = markdown_to_blocks(md)
    # units 是 simple 和 descendant 的混合列表

    cli = FeishuClient(app_id, app_secret, domain)

    # 步骤 1：wiki token → document_id
    document_id = cli.wiki_node_to_doc_id(wiki_token)

    # 步骤 2：可选清空
    if args.clear:
        children = cli.list_children(document_id, document_id)
        if children:
            cli.delete_children(document_id, document_id, 0, len(children))

    # 步骤 3：分类写入
    buf: list[dict] = []

    def flush():
        """把缓冲区里的普通块批量发出去"""
        if buf:
            cli.append_children(document_id, document_id, buf)
            buf.clear()

    for u in units:
        if u["kind"] == "simple":
            buf.append(u["block"])   # 普通块先入缓冲
        else:
            flush()                  # 先把之前的普通块发出去
            cli.append_descendant(   # 再单独发表格
                document_id, document_id,
                u["children_id"], u["descendants"]
            )
    flush()   # 最后再 flush 一次，发送末尾的普通块
```

**为什么要这个 flush 缓冲？**  
如果把普通块和表格混在一个列表里调 `/children`，飞书会报错（因为表格的子块还不存在）。把普通块攒在一起批发，表格单独用 `/descendant`，就能保证每次调用的数据结构是合法的。

## 10.10 完整的执行流程日志

本书这份文档写入时的实际日志（本章单独写入时）：

```
[parse] 解析出 72 个单元（段落/标题/列表等 68，表格 4）
[auth] 获取 tenant_access_token ... ok
[wiki] node=MLwKwZkgPiqgALkWVTEcI0Gjnmf -> document_id=X30JdBRdToQb6ZxXTIbcPIifnce
[write] 追加 72 个单元 ...
[done] 完成，去飞书刷新文档看看吧。
```

总耗时约 24 秒，其中网络 IO 约 12 秒，`sleep(0.2)` 累计约 12 秒（60 次批次 × 0.2s）。

## 10.11 飞书 API 参考文档索引

| 功能 | API | 文档链接 |
| --- | --- | --- |
| 换取 tenant_access_token | POST /auth/v3/tenant_access_token/internal | [链接](https://open.feishu.cn/document/server-docs/authentication-management/access-token/tenant_access_token_internal) |
| Wiki 节点信息 | GET /wiki/v2/spaces/get_node | [链接](https://open.feishu.cn/document/server-docs/docs/wiki-v2/space-node/get_node) |
| 列出块的子块 | GET /docx/v1/documents/{id}/blocks/{id}/children | [链接](https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document-block/list) |
| 批量删除子块 | DELETE .../children/batch_delete | [链接](https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document-block/batch_delete) |
| 追加子块 | POST .../children | [链接](https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document-block/create) |
| 追加嵌套子树 | POST .../descendant | [链接](https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document-block/create-descendant) |
| 块类型枚举 | 块类型说明 | [链接](https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document-block/block-overview) |

## 10.12 从零到写入：完整搭建步骤

### 步骤 1：创建企业自建应用

在 [飞书开放平台](https://open.feishu.cn/app) 点「创建企业自建应用」，任意命名，进入应用后在「凭证与基础信息」取到：

```
App ID:     cli_a9636f488a789cd4
App Secret: W5hGOiHA7Lch9l...   ← 保密，只写在 .env 里
```

### 步骤 2：申请权限并发布

左侧「权限管理」搜索并勾选：

- `wiki:wiki`（或更细粒度的 `wiki:node:read`）
- `docx:document`

然后「版本管理与发布」→「创建版本」→「发布」。自己是管理员就直接通过。

### 步骤 3：给文档加协作者

打开目标飞书文档 → 右上角「共享」→ 搜索应用名称 → 设为**可编辑**。  
若不做这步，调用写入 API 会收到 `1254040 permission denied`。

### 步骤 4：本地配置

```powershell
cd d:\linux\feishu
pip install -r requirements.txt    # requests + python-dotenv
copy .env.example .env
```

`.env` 内容（不要提交到 Git）：

```
FEISHU_APP_ID=cli_a9636f488a789cd4
FEISHU_APP_SECRET=W5hGOiHA7Lch...
FEISHU_WIKI_TOKEN=MLwKwZkgPiqgALkWVTEcI0Gjnmf
FEISHU_OPEN_DOMAIN=https://open.feishu.cn
```

### 步骤 5：验证连通性

```powershell
# 只解析 Markdown，不请求飞书
python feishu_writer.py ..\book\chapters\07_多线程与同步.md --dry-run

# 连通性探针（实际写入 5 个块）
echo "# 测试`n`n- 连通正常" | python feishu_writer.py /dev/stdin
```

### 步骤 6：写入文档

```powershell
# 追加到现有文档末尾
python feishu_writer.py ..\book\chapters\02_文件IO与标准IO.md

# 清空后重写（慎用，会删除文档里所有现有内容）
python feishu_writer.py ..\book\chapters\02_文件IO与标准IO.md --clear
```

## 10.13 自动化集成方案

### Git Hook：push 时自动同步

```bash
# .git/hooks/pre-push  （chmod +x）
#!/bin/bash
set -e
cd "$(git rev-parse --show-toplevel)"
source .env

# 只同步被修改的 .md 文件
for f in $(git diff --name-only HEAD~1 HEAD | grep '\.md$'); do
    echo "同步 $f → 飞书..."
    python feishu/feishu_writer.py "$f"
done
```

### GitHub Actions：PR 合并自动刷新

```yaml
name: Sync to Feishu
on:
  push:
    branches: [main]
    paths: ['book/chapters/**.md']

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install requests python-dotenv
      - run: |
          for f in $(git diff --name-only HEAD~1 HEAD | grep '\.md$'); do
            python feishu/feishu_writer.py "$f" --clear
          done
        env:
          FEISHU_APP_ID:     ${{ secrets.FEISHU_APP_ID }}
          FEISHU_APP_SECRET: ${{ secrets.FEISHU_APP_SECRET }}
          FEISHU_WIKI_TOKEN: ${{ secrets.FEISHU_WIKI_TOKEN }}
```

### 文件监听：实时同步（watchdog）

```python
# watch_sync.py
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import subprocess, time

class Handler(FileSystemEventHandler):
    def on_modified(self, ev):
        if ev.src_path.endswith('.md'):
            print(f"变化: {ev.src_path}")
            subprocess.run(['python', 'feishu/feishu_writer.py',
                            ev.src_path])

obs = Observer()
obs.schedule(Handler(), 'book/chapters/', recursive=False)
obs.start()
try:
    while True: time.sleep(1)
except KeyboardInterrupt:
    obs.stop()
obs.join()
```

## 10.14 常见问题排查

| 现象 | 原因 | 解决方案 |
| --- | --- | --- |
| `99991663 app ticket not found` | 应用未发布版本 | 开放平台→版本管理→创建并发布 |
| `1254040 permission denied` | 应用未加为文档协作者 | 文档右上角「共享」加入应用为可编辑 |
| `obj_type='doc'` 报错 | 老版云文档，不支持块 API | 在飞书里点「升级到新版文档」 |
| 写入成功但内容乱序 | 并发写入冲突 | 确保单线程串行写，不要并发调 `/children` |
| 表格显示为文本 `\| a \| b \|` | Markdown 表格没有对齐分隔行 | 检查 `\| --- \| --- \|` 那行是否存在且格式正确 |
| 中文乱码 | .md 文件不是 UTF-8 | `file -i notes.md` 确认编码，用 iconv 转换 |
| 速度很慢 | 飞书 5 QPS 限制 + sleep 0.2s | 正常现象，500 个块约需 100 秒，可把 sleep 调到 0.1s 碰运气 |
| `EINPROGRESS` 网络超时 | 网络问题或飞书服务波动 | 脚本已有 timeout=30，重跑即可 |

## 10.15 完整实战演示：从新建笔记到出现在飞书

本节以"写一篇 Linux 信号学习笔记并推到飞书"为例，完整走一遍每一条命令。

### 环境假设

```
工作区：d:\linux\
脚本：  d:\linux\feishu\feishu_writer.py
笔记：  d:\linux\notes\signal_note.md   （待创建）
目标飞书文档：https://ncnte6r0dba2.feishu.cn/wiki/MLwKwZkgPiqgALkWVTEcI0Gjnmf
```

### 第 1 步：写好 Markdown 笔记

在任意编辑器里创建 `d:\linux\notes\signal_note.md`，写入以下内容并保存：

```
# Linux 信号学习笔记

## 什么是信号

信号是内核向进程发送的**异步通知**，只携带一个整数编号，不携带数据。

## 常用信号

| 信号    | 编号 | 默认动作              |
| ---     | ---  | ---                  |
| SIGINT  | 2    | 终止（Ctrl+C）        |
| SIGKILL | 9    | 强制终止，不可捕获    |
| SIGTERM | 15   | 终止，可捕获          |
| SIGCHLD | 17   | 子进程退出时发给父进程 |

## 注册处理器的正确方式

用 sigaction 而不是 signal，关键字段：
- sa_handler：处理函数指针
- sa_flags = SA_RESTART：系统调用被打断后自动重启
- sigemptyset(&sa.sa_mask)：处理期间不额外屏蔽其他信号

## 信号屏蔽

- sigprocmask(SIG_BLOCK)：屏蔽信号集
- sigprocmask(SIG_UNBLOCK)：解除屏蔽
- sigsuspend(&mask)：原子地解除屏蔽并等待
```

### 第 2 步：先用 --dry-run 验证解析结果

`--dry-run` 只做 Markdown → 飞书块的转换，**不发任何网络请求**，用来确认解析正确：

```powershell
cd d:\linux\feishu
python feishu_writer.py ..\notes\signal_note.md --dry-run
```

预期输出：

```
[parse] 解析出 12 个单元（段落/标题/列表等 10，表格 1）
{'kind': 'simple', 'block': {'block_type': 3, 'heading1': {'elements': [{'text_run': {'content': 'Linux 信号学习笔记', ...}}], 'style': {}}}}
{'kind': 'simple', 'block': {'block_type': 4, 'heading2': {'elements': [{'text_run': {'content': '什么是信号', ...}}], ...}}}
{'kind': 'simple', 'block': {'block_type': 2, 'text': {'elements': [...加粗"异步通知"...]}}}
... (dry-run, 未请求飞书)
```

你能看到：
- `block_type=3` 是一级标题（`# Linux 信号学习笔记`）
- `block_type=4` 是二级标题
- `block_type=2` 是正文，其中"异步通知"会出现 `bold: true`
- 表格被识别为 `kind: descendant`（独立处理）

如果解析有问题（比如代码块没闭合），这一步就能发现，不会浪费 API 调用次数。

### 第 3 步：追加写入飞书（不清空已有内容）

确认解析正确后，正式写入。不加 `--clear` 表示**追加到文档末尾**，之前的内容保留：

```powershell
python feishu_writer.py ..\notes\signal_note.md
```

实际输出：

```
[parse] 解析出 12 个单元（段落/标题/列表等 10，表格 1）
[auth] 获取 tenant_access_token ... ok
[wiki] node=MLwKwZkgPiqgALkWVTEcI0Gjnmf -> document_id=X30JdBRdToQb6ZxXTIbcPIifnce
[write] 追加 12 个单元 ...
[done] 完成，去飞书刷新文档看看吧。
```

逐行解读：

- `[parse]`：Markdown 解析完成，12 个单元，其中 1 个是表格（用 `/descendant` 接口）
- `[auth]`：用 `.env` 里的 App ID/Secret 换取了 `tenant_access_token`，有效 7200 秒
- `[wiki]`：把 URL 里的 `MLwKwZkgPiqgALkWVTEcI0Gjnmf` 转成了底层文档 ID `X30JdBRdToQb6ZxXTIbcPIifnce`
- `[write]`：开始追加，普通块分批（每批≤50个）用 `/children` 接口，表格用 `/descendant` 接口
- `[done]`：全部成功

这时去飞书刷新那个文档，就能看到笔记出现在末尾。

### 第 4 步：修改笔记后重新同步（覆盖模式）

如果笔记内容改了，想用新版本**替换**飞书里旧的内容，加 `--clear`：

```powershell
python feishu_writer.py ..\notes\signal_note.md --clear
```

实际输出（多了一行 clear）：

```
[parse] 解析出 12 个单元（段落/标题/列表等 10，表格 1）
[auth] 获取 tenant_access_token ... ok
[wiki] node=MLwKwZkgPiqgALkWVTEcI0Gjnmf -> document_id=X30JdBRdToQb6ZxXTIbcPIifnce
[clear] 删除原有 187 个一级块
[write] 追加 12 个单元 ...
[done] 完成，去飞书刷新文档看看吧。
```

`[clear]` 那行说明：文档里原来有 187 个块（之前所有章节累积的），全部删除后再写入新的 12 个块。

> **慎用 --clear**：它会删除文档里的**所有内容**，包括你在飞书里手动添加的评论、标注等。如果只想更新部分内容，推荐改为用子页面（每个章节单独一个 wiki 页面），每次只 `--clear` 那一页。

### 第 5 步：把本书所有章节批量写入

实际工作中，本书是这样批量推的（PowerShell）：

```powershell
cd d:\linux\book

# 把所有章节合并成一个文件再推（文档是单页 wiki，所有内容在一起）
$files = Get-ChildItem chapters\*.md | Sort-Object Name
$all = $files | ForEach-Object { Get-Content $_ -Encoding UTF8 }
$all | Set-Content -Encoding UTF8 _push_all.md

python ..\feishu\feishu_writer.py _push_all.md --clear

Remove-Item _push_all.md
```

或者逐章追加（每次学完一章就推，不清空之前的）：

```powershell
# 只推第 7 章（多线程），追加到文档末尾
python ..\feishu\feishu_writer.py chapters\07_多线程与同步.md
```

### 第 6 步：调用关系总结

用一张图把整个调用链路串起来：

```
你在命令行输入：
  python feishu_writer.py signal_note.md --clear
         │
         ▼
  main() 函数
    ├─ load_dotenv()
    │    └─ 读 .env → FEISHU_APP_ID / APP_SECRET / WIKI_TOKEN
    │
    ├─ 读取 signal_note.md 文件内容（UTF-8）
    │
    ├─ markdown_to_blocks(md)
    │    ├─ 逐行扫描，优先级识别
    │    ├─ 代码块 → _code_block() → LANG_MAP 查枚举 → block_type=14
    │    ├─ 标题   → _heading_block() → block_type = level+2
    │    ├─ 表格   → _table_unit() → kind=descendant（三层嵌套）
    │    ├─ 列表   → _simple_block(12/13)
    │    ├─ 引用   → _simple_block(15)
    │    └─ 正文   → _simple_block(2) + _parse_inline()（行内样式）
    │         └─ 正则匹配 **bold** *italic* `code` [url]
    │              └─ 每段生成 text_run 列表
    │
    ├─ FeishuClient(app_id, app_secret)
    │
    ├─ cli._tenant_token()
    │    └─ POST /auth/v3/tenant_access_token/internal
    │         └─ 返回 token，缓存到 _token，记录过期时间
    │
    ├─ cli.wiki_node_to_doc_id(wiki_token)
    │    └─ GET /wiki/v2/spaces/get_node?token=MLwK...
    │         └─ 返回 node.obj_token = X30J...（document_id）
    │
    ├─ cli.list_children(doc_id, doc_id)  ← --clear 时
    │    └─ GET /docx/v1/documents/X30J.../blocks/X30J.../children
    │         └─ 返回现有所有一级块列表
    │
    ├─ cli.delete_children(doc_id, doc_id, 0, 187)  ← --clear 时
    │    └─ DELETE .../children/batch_delete
    │         Body: {"start_index": 0, "end_index": 187}
    │
    └─ 主写入循环（buf flush 模式）
         ├─ 普通块进 buf（每满 50 个自动 flush）
         │    └─ cli.append_children(doc_id, doc_id, buf)
         │         └─ POST .../children?document_revision_id=-1
         │              Body: {"children": [...≤50个块...], "index": -1}
         │              sleep(0.2)  ← 控制 QPS
         │
         └─ 表格（kind=descendant）先 flush 普通块，再单独发
              └─ cli.append_descendant(doc_id, doc_id, children_id, descendants)
                   └─ POST .../descendant?document_revision_id=-1
                        Body: {
                          "children_id": ["t_table_id"],
                          "index": -1,
                          "descendants": [
                            {table块},
                            {cell_0_0块}, {text_0_0块},
                            {cell_0_1块}, {text_0_1块},
                            ...
                          ]
                        }
                        sleep(0.2)
```
