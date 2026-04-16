---
name: webextract
description: 网页内容提取工具，通过本地 qt-web-extractor 服务提取网页内容并转换为 Markdown，支持 JavaScript 渲染页面和
  PDF 提取
trigger: extract, webextract, fetch, webpage, url
tier: utility
destructive: false
---

# WebExtract - 网页内容提取

通过本地 qt-web-extractor 服务提取网页内容并转换为 Markdown。

## 服务地址

默认服务运行在 `http://127.0.0.1:8766`

也支持通过 `config.yaml` 配置：

```yaml
webextract:
  base_url: http://127.0.0.1:8766
  api_key: your_key
```

## 功能特性

- 提取完全渲染的网页内容（支持 JavaScript 和 SPA）
- 自动转换为干净的 Markdown 格式
- 支持 PDF 文本提取
- 支持 JSON 格式输出

## 使用方法

### 基本用法

```bash
scholaraio webextract <URL>
```

### PDF 提取模式

```bash
scholaraio webextract <PDF_URL> --pdf
```

### 全文与预览模式

```bash
# 默认只显示预览，避免长页面直接刷满终端
scholaraio webextract <URL>

# 查看全文
scholaraio webextract <URL> --full

# 自定义预览长度
scholaraio webextract <URL> --max-chars 1200
```

### 环境变量

- `WEBEXTRACT_URL` - 自定义服务地址（默认: http://127.0.0.1:8766）
- `WEBEXTRACT_API_KEY` - API 认证密钥（如服务配置了认证）

## 与 Claude 协作

当需要提取网页内容进行分析时：

1. 使用 `scholaraio webextract <URL>` 提取网页内容
2. 将提取的 Markdown 内容进行分析、总结或回答问题

## 注意事项

- 确保 qt-web-extractor 服务已在本地 8766 端口运行
- 如果服务返回错误且没有正文，CLI 会直接报错退出，而不是显示“提取成功”
- 对于需要登录或特殊认证的页面，可能需要额外配置
- 大量提取时建议分批进行，避免过载
