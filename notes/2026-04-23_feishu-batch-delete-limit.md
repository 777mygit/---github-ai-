# 飞书 batch_delete 单次上限导致文档内容重复 — 踩坑记录

## 环境

- 工具：`feishu_writer.py` v1.3
- OS：Windows 10
- 飞书 API：`/open-apis/docx/v1/documents/{doc_id}/blocks/{block_id}/children/batch_delete`

## 问题现象

执行 `python feishu_writer.py README.md --clear` 后，飞书文档出现**内容重复**——侧边栏显示两组完全相同的标题大纲，正文内容翻倍。

```
飞书文档侧边栏（异常）：
  ├── 飞书 × GitHub × AI 团队项目管理自动化
  │   ├── 为什么需要这套系统
  │   ├── 两类使用模式
  │   └── ...
  ├── 飞书 × GitHub × AI 团队项目管理自动化  ← 重复！
  │   ├── 为什么需要这套系统
  │   └── ...
```

## 排查过程

1. 怀疑是推送了两次 → 检查日志，只调用了一次 `feishu_writer.py`
2. 怀疑 `--clear` 没有生效 → 加日志发现 `[clear] 删除原有 728 个一级块` 后立刻追加
3. 手动调用 API 验证：传 `end_index=728` 的 `batch_delete`，实际只删除了 50 个
4. 查阅飞书 API 文档：`batch_delete` 接口**单次最多删除 50 个子块**

## 根本原因

飞书 `batch_delete` API 有单次 50 个块的上限。超出部分静默忽略，返回 200 但实际未删除。

旧代码：
```python
# 错误：试图一次删除全部，超出 50 的部分不生效
cli.delete_children(document_id, document_id, 0, len(children))  # len=728
```

实际效果：只删了前 50 个，剩余 678 个仍在文档里，新内容追加后变成重复。

## 解决方案

改为循环分批删除，每次删 50 个，查询剩余，直到文档为空：

```python
# 正确：循环分批，彻底清空
total_deleted = 0
while True:
    children = cli.list_children(document_id, document_id)
    if not children:
        break
    batch = min(50, len(children))
    cli.delete_children(document_id, document_id, 0, batch)
    total_deleted += batch
    time.sleep(0.3)  # 避免触发 QPS 限制
print(f"[clear] 已清空全部 {total_deleted} 个一级块")
```

## 验证

修复后推送含 718 个旧块的文档：
```
[clear] 已清空全部 718 个一级块   ← 分 15 批（14×50 + 1×18）彻底清空
[write] 追加 233 个单元 ...
[done] 完成
```

飞书文档侧边栏恢复正常，无重复内容。

## 关键词

飞书 API、batch_delete、50块上限、文档重复、--clear、feishu_writer
