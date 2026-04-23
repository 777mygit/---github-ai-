"""
ai_summarize.py
读取 stdin 的 git diff 内容，调用 OpenAI 生成摘要，
然后用 feishu_writer 把摘要追加到飞书文档。

用法（在 post-commit 钩子里调用）：
    git diff HEAD~1 | python feishu/ai_summarize.py

环境变量（放在 feishu/.env）：
    OPENAI_API_KEY=sk-xxx        （必须）
    FEISHU_APP_ID=cli_xxx
    FEISHU_APP_SECRET=xxx
    FEISHU_WIKI_TOKEN=MLwKwZ...
"""
import sys
import os
import json
import datetime
import subprocess
from pathlib import Path

# 把 feishu/ 目录加入 path，复用 FeishuClient
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

def call_openai(diff_text: str) -> str:
    """调用 OpenAI API 生成 diff 摘要。如果没有 OPENAI_API_KEY 则返回 fallback。"""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        # 没有 OpenAI Key 时，直接用 commit message 作为摘要
        result = subprocess.run(
            ["git", "log", "-1", "--format=%s%n%n%b"],
            capture_output=True, text=True, encoding="utf-8"
        )
        return result.stdout.strip() or "(无 commit message)"

    import urllib.request
    prompt = f"""你是一个代码审查助手。下面是一次 git diff，请用中文输出以下三段，每段一行：

1. **改动内容**：简明说明改了哪些文件/功能（1-2句）
2. **改动原因**：推测或总结为什么要做这个改动（1-2句）
3. **优先级评估**：对比改动范围，给出 P0（紧急）/P1（重要）/P2（一般）并说明理由（1句）

只输出这三行，不要其他内容。

---
{diff_text[:6000]}
"""
    body = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 300,
        "temperature": 0.3,
    }).encode()

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"].strip()


def build_changelog_md(summary: str, commit_hash: str, commit_msg: str) -> str:
    """把摘要包装成一小段 Markdown，追加到飞书文档。"""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""## 变更记录 · {now}

**Commit**：`{commit_hash[:8]}` — {commit_msg}

{summary}

---
"""


def main():
    diff_text = sys.stdin.read()
    if not diff_text.strip():
        print("[ai_summarize] 没有读到 diff 内容，跳过")
        return

    # 获取最新 commit 信息
    result = subprocess.run(
        ["git", "log", "-1", "--format=%H%n%s"],
        capture_output=True, text=True, encoding="utf-8"
    )
    lines = result.stdout.strip().splitlines()
    commit_hash = lines[0] if lines else "unknown"
    commit_msg  = lines[1] if len(lines) > 1 else ""

    print("[ai_summarize] 正在生成 AI 摘要...")
    summary = call_openai(diff_text)
    print(f"[ai_summarize] 摘要：\n{summary}\n")

    md = build_changelog_md(summary, commit_hash, commit_msg)

    # 把摘要写入临时 md 文件，再调 feishu_writer 推送
    tmp = Path(__file__).parent / "_changelog_tmp.md"
    tmp.write_text(md, encoding="utf-8")

    import feishu_writer
    units = feishu_writer.markdown_to_blocks(md)
    app_id     = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    wiki_token = os.getenv("FEISHU_WIKI_TOKEN", "")
    if not all([app_id, app_secret, wiki_token]):
        print("[ai_summarize] 缺少飞书环境变量，摘要只打印到终端，未推送飞书")
        tmp.unlink(missing_ok=True)
        return

    cli = feishu_writer.FeishuClient(app_id, app_secret)
    doc_id = cli.wiki_node_to_doc_id(wiki_token)
    buf = []
    for unit in units:
        if unit["kind"] == "simple":
            buf.append(unit["block"])
            if len(buf) >= 50:
                cli.append_children(doc_id, doc_id, buf); buf = []
        else:
            if buf: cli.append_children(doc_id, doc_id, buf); buf = []
            cli.append_descendant(doc_id, doc_id, unit["children_id"], unit["descendants"])
    if buf:
        cli.append_children(doc_id, doc_id, buf)

    tmp.unlink(missing_ok=True)
    print("[ai_summarize] 摘要已推送到飞书")


if __name__ == "__main__":
    main()
