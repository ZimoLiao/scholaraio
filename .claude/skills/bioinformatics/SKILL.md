---
name: bioinformatics
description: Use when working on bioinformatics workflows such as alignment, variant calling, phylogenetics, or protein-structure analysis, especially across BLAST, minimap2, samtools, bcftools, MAFFT, IQ-TREE, or ESMFold.
---

# 生物信息学分析

用生物信息学工具链做序列比对、变异检测、系统发育和蛋白质结构分析。

本 skill **故意保持轻量**：
- 它负责告诉 agent 哪类问题该用哪类工具、标准分析链路是什么、哪些生信规范不能忽略
- 它**不**承担各个命令行工具的完整手册职责
- 具体 CLI 选项、子命令、输入输出细节统一去查 `scholaraio toolref`

## Agent 默认协议（toolref-first, toolchain-aware）

Bioinformatics 不是单一程序，而是一组工具链。agent 必须先判断自己在用哪一个子工具，再决定怎么查。

默认顺序：

1. 先判断当前任务属于哪类：
   - 同源搜索：BLAST
   - 组装序列比对：minimap2
   - BAM/SAM 处理：samtools
   - 变异调用：bcftools
   - 多序列比对：MAFFT
   - 建树：IQ-TREE
   - 结构预测：ESMFold
2. 再用 `toolref show bioinformatics <program> ...` 或 `search --program <program>` 查对应程序
3. 不要把“生信工具链”当一个大黑箱查
4. 如果某个子工具当前 `toolref` 覆盖不全，agent 应先回退该工具的官方手册或 README，再继续任务
5. 不要让普通用户自己补齐某个子工具的 `toolref`

这意味着：
- `bioinformatics` skill 负责先分流，再选工具
- `toolref` 负责各子工具的接口细节
- 当前覆盖不全时，复杂度应由 agent 吸收，而不是由用户承担

## 前置条件

```bash
# 核心工具（conda bioconda 频道）
conda install -c bioconda minimap2 mafft iqtree bcftools samtools blast

# Python 库
pip install biopython py3Dmol pycirclize toytree matplotlib seaborn pandas

# 蛋白质结构预测（需 GPU）
pip install fair-esm

# 数据获取
conda install -c conda-forge ncbi-datasets-cli
```

验证：`minimap2 --version`、`samtools --version`、`blastn -version` 均应正常输出。

## 何时使用

适合：
- 序列相似性搜索、参考比对、变异检测、系统发育树构建
- 蛋白质结构预测与突变位点解释

不适合：
- 没有明确数据类型就盲选工具
- 把生信流程当“黑箱一键按钮”，不检查质量控制和统计假设

## Toolref 优先

当 agent 不确定子命令、选项、参数含义时，**先查 toolref**。

常用查法：

```bash
scholaraio toolref show bioinformatics samtools sort
scholaraio toolref show bioinformatics bcftools manual
scholaraio toolref show bioinformatics minimap2 manual
scholaraio toolref show bioinformatics blast blastn
scholaraio toolref search bioinformatics bootstrap tree --program iqtree
```

推荐习惯：
- 在决定工具前先确认数据类型：组装序列、短读段、蛋白序列、树推断
- 写命令前先查对应手册页，而不是靠记忆拼接参数
- 报告结果时带上阈值、模型和置信度，而不是只给一张图

如果遇到覆盖缺口：
- 先回退到对应子工具的官方手册
- 在回答里明确指出是哪个子工具存在 `toolref` 覆盖不足
- 不要让用户为了当前分析去维护 `toolref`

## 核心工具链

| 工具 | 功能 | 何时用 |
|------|------|--------|
| **BLAST** | 序列相似性搜索 | 查找同源序列、注释未知基因 |
| **minimap2** | 序列比对 | 组装序列/长读段 vs 参考基因组 |
| **BWA-MEM2** | 短读段比对 | Illumina 短读段 vs 参考基因组 |
| **samtools** | BAM/SAM 操作 | 排序、索引、统计 |
| **bcftools** | 变异检测 | SNP/InDel calling |
| **MAFFT** | 多序列比对 | 建树前的全局比对 |
| **IQ-TREE** | 最大似然系统发育 | 建进化树（支持 bootstrap） |
| **FastTree** | 快速近似建树 | 大规模序列（>1000 条） |
| **ESMFold** | 蛋白质结构预测 | AI 蛋白质折叠（用 A100 GPU） |
| **BioPython** | 通用生物信息学 | PDB 解析、序列操作、Entrez 查询 |

### 工具选择规范

| 场景 | 正确工具 | 常见错误 |
|------|---------|---------|
| 组装基因组 vs 参考 | **minimap2** | 用 BWA（BWA 是短读段工具） |
| 短读段 vs 参考 | **BWA-MEM2** | 用 minimap2（不够精确） |
| 建进化树 | **IQ-TREE** (ML) | 用 NJ（邻接法太粗糙） |
| 蛋白质结构 | **ESMFold** 或 PDB 实验结构 | 盲目信任预测不看 pLDDT |

## 工作流模板

### 变异分析

建议流程：
1. 明确数据类型和参考序列
2. 选择正确比对工具
3. 用 `samtools` / `bcftools` 做排序、索引和变异调用
4. 做变异注释与功能解释
5. 与论文或数据库中的关键突变结论交叉验证

### 系统发育分析

建议流程：
1. 明确序列集合和研究问题
2. 多序列比对
3. 用 ML 方法建树
4. 检查 bootstrap 支持度
5. 讨论拓扑、分支和可能的趋同进化，而不是只贴树图

### 蛋白质结构预测

建议流程：
1. 优先检查是否已有实验结构
2. 无实验结构时再做预测
3. 报告 pLDDT 或其他置信度
4. 将结构解释和突变、生物功能联系起来

### 重点查询点

- `minimap2` 的预设与输入输出格式
- `samtools sort/view/index` 的正确用法
- `bcftools` 变异调用链路
- `iqtree` 的 bootstrap 与模型参数
- `blastn` 的输出格式和阈值

这些细节优先查 `toolref`。

## 可视化

### 系统发育树

```python
import toytree
import matplotlib.pyplot as plt

tree = toytree.tree("tree.treefile")
canvas, axes, marks = tree.draw(
    width=600, height=800,
    tip_labels_align=True,
    node_sizes=[0 if not n.is_leaf() else 8 for n in tree.treenode.traverse()],
)
# 按类群着色需自定义 node_colors
```

### Circos 基因组图

```python
from pycirclize import Circos

circos = Circos(sectors={"genome": genome_length})
sector = circos.sectors[0]

# 轨道 1: 基因注释
track1 = sector.add_track((90, 95))
# 轨道 2: 变异密度
track2 = sector.add_track((80, 88))
# 轨道 3: GC 含量
track3 = sector.add_track((70, 78))

circos.savefig("circos.png", dpi=300)
```

### 3D 蛋白质结构

```python
import py3Dmol

view = py3Dmol.view(width=800, height=600)
view.addModel(pdb_string, "pdb")

# 卡通表示 + 突变位点高亮
view.setStyle({"cartoon": {"color": "spectrum"}})
# 突变残基显示为球棍
view.addStyle({"resi": [484, 501, 681]},
              {"stick": {"colorscheme": "redCarbon"}})
view.zoomTo()
view.show()
```

### 突变景观图（Lollipop plot）

```python
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(15, 4))
# x 轴: 蛋白位置
# y 轴: 携带该突变的变异株数量
# 颜色: 按功能域着色（NTD, RBD, S1/S2, S2）
ax.vlines(positions, 0, counts, colors=domain_colors, linewidth=1.5)
ax.scatter(positions, counts, c=domain_colors, s=30, zorder=5)
# 标注关键突变
for pos, name in key_mutations:
    ax.annotate(name, (pos, counts[pos]), fontsize=8, rotation=45)
```

## GPU 使用（ESMFold）

| 序列长度 | VRAM 需求 | A100 40GB |
|----------|----------|-----------|
| < 400 aa | ~10 GB | 单 GPU |
| 400-800 aa | ~15-20 GB | 单 GPU |
| 800-1200 aa | ~25-35 GB | 单 GPU |
| > 1200 aa | > 40 GB | 需拆分域或多 GPU |

**建议：预测蛋白质域（200-500 aa）而非全长（可能超出 VRAM）。**

## 科学规范

| 检查项 | 正确做法 | 常见错误 |
|--------|---------|---------|
| 比对工具 | 组装用 minimap2，短读段用 BWA | 混用 |
| 建树方法 | ML (IQ-TREE) + bootstrap ≥1000 | 用 NJ 不做 bootstrap |
| 替换模型 | DNA: GTR+G4，蛋白: LG+G4 | 不做模型选择 |
| 结构预测 | 报告 pLDDT，与实验结构对比 | 盲目信任预测 |
| 突变命名 | 标准命名（N501Y 而非"501位天冬酰胺突变"） | 非标准命名 |
| 趋同进化 | 区分趋同进化和共祖 | 混淆 |
| E-value | BLAST 结果按 e-value 过滤 | 不设阈值 |

## Agent 行为准则

- 不要先想命令，先判断数据类型和科学问题
- 不要混用工具适用场景，尤其是 `minimap2` / `BWA` / `BLAST`
- 不要只给图，不给阈值、支持度、置信度和过滤标准
- 不要把结构预测或树拓扑当事实，必须解释其可信边界
