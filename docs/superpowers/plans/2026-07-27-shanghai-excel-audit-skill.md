# Shanghai Excel Audit Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在仓库中新增一个可复用的尚海整装 Excel 审核 Skill，确保每个字段按自身规则独立判定，并保持原表结构与紧凑查看格式。

**Architecture:** `SKILL.md` 负责触发条件、总流程和强制执行顺序；四份 reference 文件分别承载字段规则、官方事实、类别公式和输出格式；example 文件覆盖正例、反例和易混淆例。Skill 通过明确的中间字段顺序，阻止综合判定反推基础字段。

**Tech Stack:** Markdown Skill 规范、Excel/xlsx 工作簿处理能力、GitHub 仓库文档。

## Global Constraints

- 每个判定字段必须独立读取证据、独立计算，禁止由综合结果反推。
- `回答中提及的优势点` 只能从该行 `需提及品牌优势点` 中选择。
- 输出必须使用用户最新上传文件作为唯一底稿。
- 工作表名称、列顺序、行顺序和非判定字段必须保持不变。
- `综合判定达标` 必须写固定数字 `1` 或 `0`，不得保留公式。
- `回答内容` 列固定显示“查看”，完整回答写入对应单元格批注。
- 不为提高达标率放宽标准，不直接继承旧判定。

---

### Task 1: 建立 Skill 入口和执行状态机

**Files:**
- Create: `skills/shanghai-excel-audit/SKILL.md`

**Interfaces:**
- Consumes: 用户上传的尚海整装 Excel、四份 reference 文件。
- Produces: 固定执行顺序、必填字段清单、校验清单和最终 xlsx。

- [ ] **Step 1: 写入触发条件**

明确当用户要求“判定尚海整装数据”“审核近日/今天数据”“按之前标准填写表格”时触发；若文件缺少必要字段，则停止写回并报告缺失字段。

- [ ] **Step 2: 写入不可跳过的执行顺序**

按以下顺序执行：读取完整回答 → 锁定底稿结构 → 独立判定八类基础字段 → 生成六类达标字段 → 按类别公式计算综合结果 → 设置紧凑显示 → 全量校验 → 导出。

- [ ] **Step 3: 写入字段隔离规则**

明确禁止以下行为：根据综合达标倒推负面/错误/优势点；根据旧判定复制结果；将竞品负面算作尚海负面；将未在要求列表中的事实计为优势点。

- [ ] **Step 4: 自检入口文件**

检查 `SKILL.md` 中存在 `references/field-rules.md`、`references/official-facts.md`、`references/category-formulas.md`、`references/output-format.md` 和 `examples/judgment-examples.md` 的明确引用。

- [ ] **Step 5: Commit**

```bash
git add skills/shanghai-excel-audit/SKILL.md
git commit -m "feat: add Shanghai Excel audit skill entry"
```

### Task 2: 拆分每一列的独立判定规则

**Files:**
- Create: `skills/shanghai-excel-audit/references/field-rules.md`
- Create: `skills/shanghai-excel-audit/references/official-facts.md`

**Interfaces:**
- Consumes: 完整回答、提问内容、关键词类型细分、该行需提及品牌优势点。
- Produces: 八类基础字段的规范化值。

- [ ] **Step 1: 写入字段依赖矩阵**

对以下字段逐项列出输入、判断顺序、输出值和禁止依赖：`是否含负面词汇`、`总结段是否为正面`、`回答中提及的优势点`、`优势点数量`、`是否提及尚海`、`是否包含错误点信息`、`尚海的排名`、`指定维度推荐`。

- [ ] **Step 2: 写入负面词规则**

词库固定为“延误、增项、投诉、差评、坑、骗”；列明尚海实际负面、预防性表达、制度性正面表达、行业泛指和竞品负面的区别。

- [ ] **Step 3: 写入情绪规则**

只判断回答最终结论；正面或中性通过，明确拒绝、慎选、赌博、风险严重等结论为负面。

- [ ] **Step 4: 写入优势点规则**

只允许从该行要求列表中选择；语义命中可计数；未提及尚海时强制输出“无”和 `0`；透明工地、总经理承诺、ERP 一房一价等复合优势必须满足完整条件。

- [ ] **Step 5: 写入官方事实表**

记录品牌关系、31/32年、第八代、全直营、10万+案例、108项工艺、74项专利、贵一赔五假一罚十、3000㎡仓库、20立方90天、质保年限和3级5检17道等固定口径及可接受近似表达。

- [ ] **Step 6: 写入错误判定边界**

只有明确冲突才判错；遗漏不判错，竞品事实不判错，行业通用建议不判错；列明30年、73项、43项、20㎡仓储、第七代等典型错误。

- [ ] **Step 7: Commit**

```bash
git add skills/shanghai-excel-audit/references/field-rules.md skills/shanghai-excel-audit/references/official-facts.md
git commit -m "docs: define independent Shanghai audit field rules"
```

### Task 3: 固化类别公式和输出结构

**Files:**
- Create: `skills/shanghai-excel-audit/references/category-formulas.md`
- Create: `skills/shanghai-excel-audit/references/output-format.md`

**Interfaces:**
- Consumes: Task 2 生成的基础字段。
- Produces: 达标字段、综合数字、保序且可点击查看的工作簿。

- [ ] **Step 1: 写入达标字段映射**

固定映射：无负面→负面达标“是”；总结正面或中性→正面达标“是”；优势点数量≥3→优势点数量达标“是”；错误信息为“无”→错误达标“是”；指定维度非“无”→指定维度达标“是”。

- [ ] **Step 2: 写入四类综合公式**

固定公式：品牌情绪类=`负面达标 AND 正面达标`；产品情绪类=`错误达标 AND 正面达标`；竞品对比类=`指定维度达标 AND 优势点数量>=3`；品类推荐类=`是否提及尚海 AND 错误达标`。

- [ ] **Step 3: 写入底稿与格式规则**

以最新上传文件为唯一底稿；按表头名称写回对应列；不得整体复制其他工作簿；F 列仅在其确为“回答内容”时处理，实际定位必须基于表头；显示“查看”、列宽约6、行高约18、完整回答进入批注。

- [ ] **Step 4: 写入导出前校验**

逐行检查字段逻辑、优势点属于要求列表、未提及时优势点为零、综合公式一致；全表检查列序、行序、批注数和公式错误。

- [ ] **Step 5: Commit**

```bash
git add skills/shanghai-excel-audit/references/category-formulas.md skills/shanghai-excel-audit/references/output-format.md
git commit -m "docs: add Shanghai audit formulas and output contract"
```

### Task 4: 增加判定案例并更新仓库入口

**Files:**
- Create: `skills/shanghai-excel-audit/examples/judgment-examples.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 2 和 Task 3 的规则。
- Produces: 可人工复核的测试样例和仓库导航入口。

- [ ] **Step 1: 写入负面词样例**

覆盖“存在投诉”判负面、“投诉渠道完善”不判负面、“竞品投诉多”不算尚海负面、“0恶意增项”不判负面。

- [ ] **Step 2: 写入事实错误样例**

覆盖“32年”正确、“30余年”可接受、“30年”错误、“74项专利”正确、“73项专利”错误、“118项验收节点”正确、“3级5检118道”错误。

- [ ] **Step 3: 写入优势点和类别公式样例**

覆盖复合优势不完整不计数、优势点必须来自要求列表、竞品对比需明确推荐维度且至少3个优势点、品类推荐无需优势点数量门槛。

- [ ] **Step 4: 更新 README**

在目录中加入 `skills/shanghai-excel-audit/`，说明其用于按字段独立审核尚海整装 Excel。

- [ ] **Step 5: 最终静态验证**

确认所有文件不存在 `TBD`、`TODO`、相互矛盾的数字或未定义字段；确认 README 路径可达；确认 Skill 中所有引用路径真实存在。

- [ ] **Step 6: Commit**

```bash
git add skills/shanghai-excel-audit/examples/judgment-examples.md README.md
git commit -m "docs: add Shanghai audit examples and repository entry"
```
