# 学术 Beamer PPT 制作规范

---

## 一、内容风格规范

**核心原则**：学术简洁、引用上标、基于权威来源重构、功能化视觉分块。

### 1.1 写作风格

- **学术凝练，避免口语化冗余**
  - 使用短促的陈述句、bullet points 和 block 环境
  - 禁止大段散文式叙述

- **引用标注紧凑**
  - 用上标引用编号：`\textsuperscript{[8]}`
  - 完整文献信息放在最后的 References 页
  - 避免在正文 clutter 作者、会议、年份

- **基于权威来源重构**
  - 发现事实性错误或过时表述时，优先基于原始论文/官方文档重写整页
  - 追求来源真实性和表达清晰度，而非保留原文措辞

### 1.2 视觉结构

- 使用 `columns`、`alertblock`、`block` 进行功能分区
- 擅长左右分栏对比两种观点（如历史 vs 现代、理论 vs 实践）
- 保持简洁的叙事流：
  > IR nodes → Background bridge → Lowering → Optimization passes → Verification → Scheduling → Lowering to RTL

---

## 二、制作技术规范

### 2.1 高密度排版

- 双栏溢出或 `alertblock` 被挤出时：
  - 先将正文缩到 `\footnotesize`（必要时 `\scriptsize`）
  - 缩小垂直间距：`\vspace{0.2em}` 代替 `0.5em`
  - **优先压缩字体和间距，而非删除内容**

### 2.2 纯图幻灯片

- 使用 `\begin{columns}[T]`，宽度均衡（如 `0.50\textwidth` / `0.48\textwidth`）
- 图注最小化，使用 `\scriptsize`
- 布局惯例：宏观照片放左，微观模块图放右

### 2.3 下划线转义

- `\texttt{}` 中的下划线必须转义：
  ```latex
  % 正确
  \texttt{tok\_merged}
  % 错误（会触发 math-mode 错误）
  \texttt{tok_merged}
  ```

### 2.4 Frame 手术安全

**严禁**：全局字符串替换 `\end{frame}`（会破坏环境平衡）。

**正确做法**：
1. 按 `\frametitle` 内容定位 frame
2. 按显式行号范围提取
3. 逐行重新组装
4. 验证平衡：
   ```python
   text.count(r"\begin{frame}") == text.count(r"\end{frame}")
   ```

### 2.5 页码漂移管理

- 插入新 frame 后，下游页码会整体偏移
- **维护一份实时 frame title 列表**，确保叙事弧线连贯
- 不要追逐具体页码数字

### 2.6 Verbatim 与间距回收

- `\end{verbatim}` 后紧跟：
  ```latex
  \vspace{-0.3em}
  ```
- 必要时使用 `\tiny` 做 tiny caption 回收空间

### 2.7 SVG 矢量图插入

- Beamer 中可直接插入 SVG 矢量图，避免栅格图放大后的模糊问题：
  ```latex
  \usepackage{svg}
  \begin{frame}
  \centering
  \includesvg[width=0.8\columnwidth]{images/diagram.svg}
  \end{frame}
  ```
- **编译要求**：必须带 `-shell-escape` 参数调用 `lualatex` 或 `xelatex`，且系统需安装 Inkscape。
- **推荐工作流**：复杂架构图/数据流图先用 Graphviz 生成 `.dot` 脚本，渲染为 SVG 后插入 Beamer。此流程已在项目内验证可行，能兼顾绘图效率与矢量输出质量；具体命令和排错见 [Graphviz Diagram Guide](graphviz-guide.md)。

---

## 三、最终检查清单

- [ ] 编译成功（`xelatex`/`lualatex` 无报错）
- [ ] Frame 数量平衡：`\begin{frame}` == `\end{frame}`
- [ ] Frame title 列表与叙事顺序一致
- [ ] 文字不拥挤（已尝试压缩字体而非删内容）
- [ ] 所有 `\texttt{}` 中的下划线已转义
- [ ] 图片清晰、来源标注正确

---

## 四、References 页规范

**位置**：正文结束后、附录之前。

**格式**：使用 `\texttt{}` 或 `\bibitem` 风格列出核心技术文献。

**典型条目示例**：
- Gurd 1985 (Manchester Dataflow)
- Rowen 2004 (H/S Equivalent Model)
- Kahn 1974 (KPN)
- Leary 2024 (UCSC XLS Lecture)
- Bachrach 2012 (Chisel)
- Xilinx UG902 (Vivado HLS)

> **目的**：增强报告的学术严谨性，所有技术论断需有据可查。

---

**最后更新**: 2026-04-10
