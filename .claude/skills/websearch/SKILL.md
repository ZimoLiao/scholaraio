---
name: websearch
description: 实时网页搜索（Bing via GUILessBingSearch），获取互联网最新信息
version: 1.0.0
author: Claude
tier: utility
destructive: false
---

# websearch — 实时网页搜索

通过本地 GUILessBingSearch HTTP API 服务执行实时 Bing 搜索，获取互联网最新信息。

## 前置要求

1. 安装并启动 GUILessBingSearch 服务：
   ```bash
   # 安装
   git clone https://github.com/wszqkzqk/GUILessBingSearch
   cd GUILessBingSearch
   pip install -r requirements.txt

   # 启动服务
   python guiless_bing_search.py
   ```

2. 服务默认运行在 http://127.0.0.1:8765

## 用法

```bash
# 基本搜索
scholaraio websearch "深度学习 congestion control"

# 指定结果数量
scholaraio websearch "transformer architecture" --count 20
```

## 配置

在 `config.yaml` 中自定义服务地址：

```yaml
websearch:
  base_url: http://127.0.0.1:8765
  api_key: null  # 如服务配置了认证
```

或通过环境变量：
```bash
export WEBSEARCH_URL=http://127.0.0.1:8765
export WEBSEARCH_API_KEY=your_key
```

## 输出示例

```
找到 10 条结果（'深度学习 congestion control'）：

[1] On the Design of High-throughput Congestion Control
    https://example.com/paper1
    深度学习方法在拥塞控制中的应用...

[2] Learning-based Congestion Control Survey
    https://example.com/paper2
    本文综述了基于学习的拥塞控制算法...
```

## 与其他功能配合

搜索结果可用于：
- 发现新的研究论文和 arXiv 链接
- 获取最新技术动态
- 验证本地知识库的信息完整性
- 为文献综述补充最新资料

## 故障排除

**服务不可用**
```
搜索服务未启动或不可达: http://127.0.0.1:8765
```
解决方案：
1. 确认 GUILessBingSearch 服务已启动
2. 检查端口是否被占用
3. 验证 `config.yaml` 中的 `websearch.base_url` 配置
