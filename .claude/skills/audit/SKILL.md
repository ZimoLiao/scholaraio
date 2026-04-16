---
name: audit
description: Audit paper data quality in the knowledge base. Checks for missing fields, filename issues, DOI duplicates, title mismatches, and more. Supports LLM-based deep diagnosis for title mismatches and automated repair. Use when the user wants to check data quality, find problems, or fix metadata issues.
version: 1.1.0
author: ZimoLiao/scholaraio
license: MIT
tags: ["academic", "research", "metadata", "data-quality"]
---
# 论文审计

检查已入库论文的数据质量。分阶段：规则化检查（自动）+ LLM 深度诊断（对可疑项）+ 自动修复。

## 阶段一：规则化检查

```bash
scholaraio audit [--severity error|warning|info]
```

问题按严重程度分类：
- **错误**：缺少标题、缺少 MD 文件、JSON 解析失败、DOI 重复
- **警告**：缺少 DOI/摘要/年份/作者/期刊、MD 过短、标题不一致、文件名年份不匹配
- **提示**：文件名不符合规范格式

## 阶段二：LLM 深度诊断（title_mismatch 专项）

对每篇 `title_mismatch` 论文，用 Read 工具读取 meta.json 和 paper.md（前 80 行），提取最像标题的候选（不只看首个 H1），判断：
- MD 正文的实际主题/标题是否与 JSON 元数据一致
- 无害（封面/前言页、MinerU 标题识别问题）vs 真正的内容错配

## 阶段三：修复

对确认的错配，使用 `repair` 命令：

```bash
# 先 dry-run 预览
scholaraio repair "<paper-id>" --title "正确标题" [--author "一作"] [--year YYYY] [--doi "10.xxx/..."] --dry-run

# 确认后执行
scholaraio repair "<paper-id>" --title "正确标题" [--author "一作"] [--year YYYY] [--doi "10.xxx/..."] [--no-api]

# 修复后重建索引
scholaraio pipeline reindex
```

## 检查规则

| 规则 | 级别 | 说明 |
|------|------|------|
| `missing_title` | error | 缺少标题 |
| `missing_md` | error | JSON 无对应 MD 文件 |
| `duplicate_doi` | error | DOI 重复 |
| `missing_doi` | warning | 缺少 DOI（document / patent 等非论文类型通常不报） |
| `missing_abstract` | warning | 缺少摘要 |
| `title_mismatch` | warning | JSON 标题与 MD 前 80 行里的标题候选不一致 |
| `nonstandard_filename` | info | 文件名不符合规范格式 |

补充判断口径：
- `paper_type` 为空时，仍按普通论文保守检查 `missing_doi` / `missing_journal`
- `dissertation`、`document`、`technical-report`、`lecture-notes` 等非 article 类型，优先警惕封面/前言页导致的 `title_mismatch` 误报

## 示例

用户说："帮我检查一下论文库有没有问题"
→ 执行阶段一规则化检查

用户说："深度检查"
→ 执行阶段一 + 阶段二（LLM 逐篇诊断 title_mismatch）

用户说："修复那些错配的论文"
→ 执行阶段三
