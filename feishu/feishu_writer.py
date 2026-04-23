"""
把一份 Markdown 写入指定的飞书 Wiki 文档。

用法：
    python feishu_writer.py path/to/文档.md
    python feishu_writer.py path/to/文档.md --clear     # 先清空原有正文再写
    python feishu_writer.py path/to/文档.md --dry-run   # 只解析不请求
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import requests
from dotenv import load_dotenv


# ---------- 飞书 OpenAPI 薄封装 ----------


class FeishuClient:
    def __init__(self, app_id: str, app_secret: str, domain: str = "https://open.feishu.cn"):
        self.app_id = app_id
        self.app_secret = app_secret
        self.domain = domain.rstrip("/")
        self._token: str | None = None
        self._token_expire_at: float = 0

    def _tenant_token(self) -> str:
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
        self._token_expire_at = time.time() + int(data.get("expire", 7200))
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._tenant_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _call(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        url = f"{self.domain}{path}"
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                r = requests.request(method, url, headers=self._headers(), timeout=30, **kwargs)
                try:
                    data = r.json()
                except ValueError:
                    r.raise_for_status()
                    raise
                if data.get("code") not in (0, None):
                    raise RuntimeError(f"{method} {path} 失败: {data}")
                return data
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.SSLError,
                    requests.exceptions.Timeout,
                    ConnectionResetError,
                    OSError) as e:
                last_err = e
                wait = 3 * (attempt + 1)
                print(f"[retry] 网络错误，{wait}s 后重试（第{attempt+1}次）: {e}", file=sys.stderr)
                time.sleep(wait)
        raise RuntimeError(f"连续4次网络错误: {last_err}")

    # ---- Wiki / Docx ----

    def wiki_node_to_doc_id(self, wiki_token: str) -> str:
        """把 wiki 节点 token 解析成 docx 的 document_id。"""
        data = self._call(
            "GET",
            f"/open-apis/wiki/v2/spaces/get_node?token={wiki_token}&obj_type=wiki",
        )
        node = data["data"]["node"]
        obj_type = node.get("obj_type")
        if obj_type != "docx":
            raise RuntimeError(
                f"该 wiki 节点类型为 {obj_type!r}，当前脚本只支持新版文档 docx。"
            )
        return node["obj_token"]

    def list_children(self, document_id: str, block_id: str) -> list[dict]:
        """列出某个块的直接子块。"""
        blocks = []
        page_token = ""
        while True:
            q = f"?page_size=500"
            if page_token:
                q += f"&page_token={page_token}"
            data = self._call(
                "GET",
                f"/open-apis/docx/v1/documents/{document_id}/blocks/{block_id}/children{q}",
            )
            blocks.extend(data["data"].get("items", []))
            page_token = data["data"].get("page_token", "")
            if not data["data"].get("has_more") or not page_token:
                break
        return blocks

    def delete_children(self, document_id: str, block_id: str, start: int, end: int) -> None:
        """按索引区间 [start, end) 删除子块。"""
        self._call(
            "DELETE",
            f"/open-apis/docx/v1/documents/{document_id}/blocks/{block_id}/children/batch_delete",
            json={"start_index": start, "end_index": end},
        )

    def append_children(
        self, document_id: str, block_id: str, children: list[dict]
    ) -> None:
        """追加子块。单次最多 50 个，超出自动分批。"""
        CHUNK = 50
        for i in range(0, len(children), CHUNK):
            batch = children[i : i + CHUNK]
            self._call(
                "POST",
                f"/open-apis/docx/v1/documents/{document_id}/blocks/{block_id}/children?document_revision_id=-1",
                json={"children": batch, "index": -1},
            )
            # 给 QPS 一点喘息
            time.sleep(0.2)

    def append_descendant(
        self,
        document_id: str,
        parent_block_id: str,
        children_id: list[str],
        descendants: list[dict],
    ) -> None:
        """用 /descendant 接口一次性创建嵌套子树（用于表格等多层结构）。

        children_id: 直接挂在 parent_block_id 下的节点 ID
        descendants: 所有后代节点（含直接子）扁平列表；每个节点必须带临时 block_id
        """
        self._call(
            "POST",
            f"/open-apis/docx/v1/documents/{document_id}/blocks/{parent_block_id}/descendant?document_revision_id=-1",
            json={
                "children_id": children_id,
                "index": -1,
                "descendants": descendants,
            },
        )
        time.sleep(0.2)


# ---------- Markdown -> Feishu blocks ----------
#
# 块类型（飞书 docx v1）：
#   2  text       正文段落
#   3  heading1   ...  11 heading9
#   12 bullet     无序列表项
#   13 ordered    有序列表项
#   14 code       代码块
#   15 quote      引用


HEADING_TYPE = {i: i + 2 for i in range(1, 10)}  # h1->3 ... h9->11


@dataclass
class Line:
    kind: str  # heading / code_fence / bullet / ordered / quote / blank / text
    level: int = 0
    text: str = ""
    lang: str = ""


def _parse_inline(text: str) -> list[dict]:
    """把一行正文里的行内样式解析成 text_run 列表。
    支持：**bold** / *italic* / `code` / [label](url)
    未匹配的部分按纯文本处理。
    """
    pattern = re.compile(
        r"(\*\*(?P<b>[^*]+)\*\*)"
        r"|(\*(?P<i>[^*\n]+)\*)"
        r"|(`(?P<c>[^`\n]+)`)"
        r"|(\[(?P<l>[^\]]+)\]\((?P<u>[^)]+)\))"
    )
    elements: list[dict] = []
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            elements.append(_run(text[pos : m.start()]))
        if m.group("b") is not None:
            elements.append(_run(m.group("b"), bold=True))
        elif m.group("i") is not None:
            elements.append(_run(m.group("i"), italic=True))
        elif m.group("c") is not None:
            elements.append(_run(m.group("c"), inline_code=True))
        elif m.group("l") is not None:
            elements.append(_run(m.group("l"), link=m.group("u")))
        pos = m.end()
    if pos < len(text):
        elements.append(_run(text[pos:]))
    if not elements:
        elements.append(_run(""))
    return elements


def _run(content: str, *, bold=False, italic=False, inline_code=False, link: str | None = None) -> dict:
    style: dict[str, Any] = {}
    if bold:
        style["bold"] = True
    if italic:
        style["italic"] = True
    if inline_code:
        style["inline_code"] = True
    if link:
        style["link"] = {"url": _percent_encode(link)}
    return {"text_run": {"content": content, "text_element_style": style}}


def _percent_encode(url: str) -> str:
    # 飞书对 link.url 要求百分号编码
    from urllib.parse import quote
    return quote(url, safe="")


TABLE_SEP_RE = re.compile(r"^\s*\|?(\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")


def _is_table_header(line: str) -> bool:
    return line.count("|") >= 2 and line.strip().startswith("|") or (
        "|" in line and not line.strip().startswith("|")
    )


def _split_table_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def markdown_to_blocks(md: str) -> list[dict]:
    """返回 unit 列表。每个 unit 是以下之一：
      {"kind": "simple",     "block": <block_dict>}
      {"kind": "descendant", "children_id": [...], "descendants": [...]}  # 表格用
    """
    lines = md.splitlines()
    units: list[dict] = []

    i = 0
    while i < len(lines):
        raw = lines[i]

        # 代码块 ```lang ... ``` 或 ````lang ... ````（支持嵌套）
        # 开头有几个反引号，关闭行就必须是同样数量，防止内层 ``` 提前截断
        m = re.match(r"^(`{3,})(\w*)\s*$", raw)
        if m:
            fence = m.group(1)        # "```" 或 "````" 等
            lang  = m.group(2).lower()
            close_re = re.compile(r"^" + re.escape(fence) + r"\s*$")
            i += 1
            buf: list[str] = []
            while i < len(lines) and not close_re.match(lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1  # 跳过收尾围栏
            units.append({"kind": "simple", "block": _code_block("\n".join(buf), lang)})
            continue

        # 标题 # ~ ######
        m = re.match(r"^(#{1,9})\s+(.*)$", raw)
        if m:
            level = len(m.group(1))
            units.append({"kind": "simple", "block": _heading_block(level, m.group(2).strip())})
            i += 1
            continue

        # 引用 > ...
        if raw.startswith("> "):
            units.append({"kind": "simple", "block": _simple_block(15, raw[2:])})
            i += 1
            continue

        # 表格：当前行有管道 + 下一行是分隔行
        if (
            "|" in raw
            and i + 1 < len(lines)
            and TABLE_SEP_RE.match(lines[i + 1])
        ):
            header = _split_table_row(raw)
            rows: list[list[str]] = [header]
            j = i + 2
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                rows.append(_split_table_row(lines[j]))
                j += 1
            units.append(_table_unit(rows))
            i = j
            continue

        # 无序列表 - / * / +
        m = re.match(r"^[\-\*\+]\s+(.*)$", raw)
        if m:
            units.append({"kind": "simple", "block": _simple_block(12, m.group(1))})
            i += 1
            continue

        # 有序列表 1. / 2) ...
        m = re.match(r"^\d+[\.\)]\s+(.*)$", raw)
        if m:
            units.append({"kind": "simple", "block": _simple_block(13, m.group(1))})
            i += 1
            continue

        # 空行：只在连续正文之间起分段作用，直接跳过
        if raw.strip() == "":
            i += 1
            continue

        # 普通段落：合并相邻非空、非结构行
        para = [raw]
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if (
                nxt.strip() == ""
                or re.match(r"^`{3,}", nxt)
                or re.match(r"^#{1,9}\s+", nxt)
                or nxt.startswith("> ")
                or re.match(r"^[\-\*\+]\s+", nxt)
                or re.match(r"^\d+[\.\)]\s+", nxt)
                or ("|" in nxt and j + 1 < len(lines) and TABLE_SEP_RE.match(lines[j + 1]))
            ):
                break
            para.append(nxt)
            j += 1
        units.append({"kind": "simple", "block": _simple_block(2, " ".join(s.strip() for s in para))})
        i = j

    return units


def _tmp_id() -> str:
    return "t_" + uuid.uuid4().hex[:16]


def _table_unit(rows: list[list[str]]) -> dict:
    """把一张表格的行构造成 descendant unit。
    - 第一行作为表头（header_row = True）
    - 所有单元格宽度统一为 120
    """
    row_size = len(rows)
    col_size = max(len(r) for r in rows)
    # 规整每一行到相同列数
    rows = [r + [""] * (col_size - len(r)) for r in rows]

    table_id = _tmp_id()
    descendants: list[dict] = []
    cell_ids: list[str] = []

    # 扁平化：table -> cells (row-major) -> text per cell
    for r in rows:
        for cell_text in r:
            cid = _tmp_id()
            tid = _tmp_id()
            cell_ids.append(cid)
            descendants.append(
                {
                    "block_id": cid,
                    "block_type": 32,  # table_cell
                    "children": [tid],
                    "table_cell": {},
                }
            )
            descendants.append(
                {
                    "block_id": tid,
                    "block_type": 2,  # text
                    "text": {"elements": _parse_inline(cell_text), "style": {}},
                }
            )

    table_block = {
        "block_id": table_id,
        "block_type": 31,  # table
        "children": cell_ids,
        "table": {
            "property": {
                "row_size": row_size,
                "column_size": col_size,
                "column_width": [120] * col_size,
                "header_row": True,
            }
        },
    }

    return {
        "kind": "descendant",
        "children_id": [table_id],
        "descendants": [table_block, *descendants],
    }


def _simple_block(block_type: int, text: str) -> dict:
    elements = _parse_inline(text)
    # 飞书 docx：段落=text，引用=quote，列表=bullet/ordered，字段都叫 text / quote / bullet / ordered
    key = {
        2: "text",
        12: "bullet",
        13: "ordered",
        15: "quote",
    }[block_type]
    return {
        "block_type": block_type,
        key: {"elements": elements, "style": {}},
    }


def _heading_block(level: int, text: str) -> dict:
    bt = HEADING_TYPE[min(max(level, 1), 9)]
    key = f"heading{min(max(level,1),9)}"
    return {
        "block_type": bt,
        key: {"elements": _parse_inline(text), "style": {}},
    }


LANG_MAP = {
    "": 1, "plain": 1, "text": 1,
    "abap": 2, "ada": 3, "apache": 4, "apex": 5, "assembly": 6, "bash": 7, "csharp": 8,
    "c++": 9, "cpp": 9, "c": 10, "clojure": 11, "coffeescript": 12, "css": 13, "cuda": 14,
    "dart": 15, "delphi": 16, "django": 17, "dockerfile": 18, "erlang": 19, "fortran": 20,
    "foxpro": 21, "go": 22, "groovy": 23, "html": 24, "htmlbars": 25, "http": 26, "haskell": 27,
    "json": 28, "java": 29, "javascript": 30, "js": 30, "julia": 31, "kotlin": 32, "latex": 33,
    "lisp": 34, "logo": 35, "lua": 36, "matlab": 37, "makefile": 38, "make": 38, "markdown": 39,
    "nginx": 40, "objective-c": 41, "objectivec": 41, "objc": 41, "openedgeabl": 42, "php": 44,
    "perl": 45, "postscript": 46, "power shell": 47, "powershell": 47, "prolog": 48, "protobuf": 49,
    "python": 49, "py": 49, "r": 50, "rpg": 51, "ruby": 52, "rust": 53, "sas": 54, "scss": 55,
    "sql": 56, "scala": 57, "scheme": 58, "scratch": 59, "shell": 60, "sh": 60, "swift": 61,
    "thrift": 62, "typescript": 63, "ts": 63, "vbscript": 64, "visual basic": 65, "vb": 65,
    "xml": 66, "yaml": 67, "yml": 67, "cmake": 68, "diff": 69, "gherkin": 70, "graphql": 71,
    "basic": 72, "opengl shading language": 73, "glsl": 73, "perl6": 75,
}


def _code_block(content: str, lang: str) -> dict:
    language = LANG_MAP.get(lang.lower(), 1)
    return {
        "block_type": 14,
        "code": {
            "elements": [_run(content)],
            "style": {"language": language, "wrap": True},
        },
    }


# ---------- 主流程 ----------


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="把 Markdown 写入飞书 Wiki 文档")
    parser.add_argument("markdown", help="要写入的 .md 文件路径")
    parser.add_argument("--clear", action="store_true", help="写入前先清空文档正文")
    parser.add_argument("--dry-run", action="store_true", help="只解析不请求飞书")
    args = parser.parse_args()

    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    wiki_token = os.environ.get("FEISHU_WIKI_TOKEN")
    domain = os.environ.get("FEISHU_OPEN_DOMAIN") or "https://open.feishu.cn"

    if not os.path.exists(args.markdown):
        sys.exit(f"找不到文件: {args.markdown}")

    with open(args.markdown, "r", encoding="utf-8") as f:
        md = f.read()

    units = markdown_to_blocks(md)
    n_simple = sum(1 for u in units if u["kind"] == "simple")
    n_table = sum(1 for u in units if u["kind"] == "descendant")
    print(f"[parse] 解析出 {len(units)} 个单元（段落/标题/列表等 {n_simple}，表格 {n_table}）")

    if args.dry_run:
        for u in units[:5]:
            print(u)
        print("... (dry-run, 未请求飞书)")
        return

    if not (app_id and app_secret and wiki_token):
        sys.exit("缺少环境变量：请先复制 .env.example 为 .env 并填写 FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_WIKI_TOKEN")

    cli = FeishuClient(app_id, app_secret, domain)
    print(f"[auth] 获取 tenant_access_token ... ok")

    document_id = cli.wiki_node_to_doc_id(wiki_token)
    print(f"[wiki] node={wiki_token} -> document_id={document_id}")

    if args.clear:
        # 飞书 batch_delete 每次最多删 50 个，必须循环直到全部清空
        total_deleted = 0
        while True:
            children = cli.list_children(document_id, document_id)
            if not children:
                break
            batch = min(50, len(children))
            cli.delete_children(document_id, document_id, 0, batch)
            total_deleted += batch
            time.sleep(0.3)
        if total_deleted:
            print(f"[clear] 已清空全部 {total_deleted} 个一级块")

    print(f"[write] 追加 {len(units)} 个单元 ...")
    buf: list[dict] = []

    def flush():
        if buf:
            cli.append_children(document_id, document_id, buf)
            buf.clear()

    for u in units:
        if u["kind"] == "simple":
            buf.append(u["block"])
        else:
            flush()
            cli.append_descendant(
                document_id, document_id, u["children_id"], u["descendants"]
            )
    flush()
    print("[done] 完成，去飞书刷新文档看看吧。")


if __name__ == "__main__":
    main()
