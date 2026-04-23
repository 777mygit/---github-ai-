"""
create_wiki_page.py
在指定 Wiki 节点下创建一个新子页面，返回新页面的 wiki_token。
然后把指定 md 文件推送到这个新页面。

用法：
    python feishu/create_wiki_page.py README.md "飞书×GitHub×AI 团队项目管理"
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import feishu_writer
import requests
import time

APP_ID     = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
# 父页面的 wiki token（URL 中 wiki/ 后面那段）
PARENT_TOKEN = os.getenv("FEISHU_WIKI_TOKEN", "")
DOMAIN = os.getenv("FEISHU_OPEN_DOMAIN", "https://open.feishu.cn")


def get_tenant_token() -> str:
    r = requests.post(
        f"{DOMAIN}/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["tenant_access_token"]


def get_space_id(token: str, wiki_node_token: str) -> tuple[str, str]:
    """返回 (space_id, parent_node_token)"""
    r = requests.get(
        f"{DOMAIN}/open-apis/wiki/v2/spaces/get_node",
        params={"token": wiki_node_token, "obj_type": "wiki"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    r.raise_for_status()
    node = r.json()["data"]["node"]
    return node["space_id"], node["node_token"]


def create_wiki_page(token: str, space_id: str, title: str, parent_node_token: str = "") -> str:
    """
    在 Wiki 空间里创建新页面。
    parent_node_token 为空 → 根目录（与其他 wiki 页面平级）
    parent_node_token 非空 → 指定页面的子页面
    """
    body: dict = {
        "obj_type": "docx",
        "node_type": "origin",
        "title": title,
    }
    if parent_node_token:
        body["parent_node_token"] = parent_node_token

    r = requests.post(
        f"{DOMAIN}/open-apis/wiki/v2/spaces/{space_id}/nodes",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=15,
    )
    data = r.json()
    if data.get("code", 0) != 0:
        raise RuntimeError(f"创建页面失败: {data}")
    new_token = data["data"]["node"]["node_token"]
    loc = f"子页面（parent={parent_node_token}）" if parent_node_token else "根目录页面"
    print(f"[create] 新{loc}已创建，wiki_token={new_token}")
    return new_token


def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python create_wiki_page.py <file.md> [页面标题]          # 根目录新页面")
        print("  python create_wiki_page.py <file.md> [标题] --child      # 作为当前WIKI_TOKEN的子页面")
        sys.exit(1)

    md_file   = Path(sys.argv[1])
    title     = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else md_file.stem
    as_child  = "--child" in sys.argv

    if not md_file.exists():
        print(f"文件不存在: {md_file}")
        sys.exit(1)

    print(f"[init] 获取 tenant_access_token ...")
    token = get_tenant_token()

    print(f"[init] 获取 space_id ...")
    space_id, current_node_token = get_space_id(token, PARENT_TOKEN)
    parent_node_token = current_node_token if as_child else ""
    mode = f"子页面（挂在 {PARENT_TOKEN} 下）" if as_child else "根目录独立页面"
    print(f"[init] space_id={space_id}，创建模式={mode}")

    print(f"[init] 创建新页面：{title}")
    new_wiki_token = create_wiki_page(token, space_id, title, parent_node_token)

    # 等一下让飞书后台初始化完
    time.sleep(2)

    # 用 feishu_writer 推内容
    print(f"[write] 开始把 {md_file} 推送到新页面 ...")
    md_text = md_file.read_text(encoding="utf-8")
    units = feishu_writer.markdown_to_blocks(md_text)
    print(f"[parse] 解析出 {len(units)} 个单元")

    cli = feishu_writer.FeishuClient(APP_ID, APP_SECRET)
    doc_id = cli.wiki_node_to_doc_id(new_wiki_token)
    print(f"[wiki] new wiki_token={new_wiki_token} -> document_id={doc_id}")

    buf = []
    for unit in units:
        if unit["kind"] == "simple":
            buf.append(unit["block"])
            if len(buf) >= 50:
                cli.append_children(doc_id, doc_id, buf)
                buf = []
        else:
            if buf:
                cli.append_children(doc_id, doc_id, buf)
                buf = []
            cli.append_descendant(doc_id, doc_id, unit["children_id"], unit["descendants"])
    if buf:
        cli.append_children(doc_id, doc_id, buf)

    print(f"[done] 完成！新页面 wiki_token={new_wiki_token}")
    print(f"       飞书链接（拼接）: https://ncnte6r0dba2.feishu.cn/wiki/{new_wiki_token}")


if __name__ == "__main__":
    main()
