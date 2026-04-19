# meaning_unit_extractor

中文质性研究数据的命题识别工具。采用"规则层 + LLM 解释层"的双层架构：规则层对原始文本做机械可复现的切分，LLM 层从语义轮次中识别可独立赋码的分析命题。面向质性研究中内容分析（content analysis）、框架分析（framework analysis）、扎根理论（grounded theory）等需要开放编码（open coding）的方法学场景，产物可直接导入 NVivo、MAXQDA、ATLAS.ti 等 QDA 软件，或作为后续主题归纳与理论建构的输入。

本工具支持三类质性数据：多说话人访谈、单人自述/日记、研究者撰写的叙事民族志。

## 核心架构

```
原始文本 → 格式检测 → 解析为轮次 → 参数自动推断 → 轮次重建 →
  → 子句切分（规则层）─────────────┐
                                       ├→ 命题识别（LLM 层）
  → 语义轮次（含角色标注）─────────┘
```

产出两层数据：

| 层 | 来源 | 产物 | 用途 |
|---|---|---|---|
| 规则层 | 纯 Python | `clauses.csv` | 按标点机械切分的子句，保留原文句法，作为审计与原文回溯凭证 |
| LLM 层 | Claude / GPT / DeepSeek / 国内大模型 | `propositions.csv` | 从语义轮次识别的分析命题，含原文摘录、字符区间、置信度，可独立赋码 |

命题既可作为开放编码（一级编码）的候选产物直接导入 QDA 软件，也可在工作流上游作为后续聚类或主题分析的输入。

## 方法学锚点

命题识别的 prompt 构造基于 Graneheim 与 Lundman (2004) 在护理研究内容分析中的四层框架：**意义单元（meaning unit）→ 凝练意义单元（condensed meaning unit）→ 编码（code）→ 类属/主题（category / theme）**。本工具的 LLM 产物对应第一、二层的组合——每条命题含原文摘录（对应意义单元层）、paraphrase（对应凝练层）、label（对应初级编码层）。第三层的范畴化与第四层的主题归纳不在本工具的职责范围，应由研究者在 QDA 软件中或通过后续专门脚本完成。

> GRANEHEIM U H, LUNDMAN B. Qualitative content analysis in nursing research: Concepts, procedures and measures to achieve trustworthiness[J]. Nurse Education Today, 2004, 24(2): 105-112.

对于叙事民族志文本的分层编码（observation / quote / interpretation / theory），设计参考 Emerson、Fretz 与 Shaw (2011) 在 *Writing Ethnographic Fieldnotes* 中对田野笔记的多声部分析传统。

## 支持的输入格式

本工具根据文件内容（而非扩展名）自动路由到对应格式的专属解析器。共支持六种格式：

### 访谈类（自动检测）

| 格式 | 特征 | 典型来源 |
|---|---|---|
| A | `姓名(HH:MM:SS): 正文` | 带说话人分离的 ASR 输出（飞书、腾讯会议等） |
| B | `访谈者：/受访者：` | 人工编辑过的转录 |
| C | 音频块引用无说话人标签 | 低质量 ASR 未编辑（不支持，会诊断退出） |
| D | `说话人 N MM:SS` | 讯飞听见等工具输出 |

格式 A/D 会进一步处理 ASR 伪轮次切分现象——ASR 根据呼吸停顿把单一发言误切成多轮、并在断点处"脑补"句号。工具自动合并同说话人的连续轮次，并对受访者发言中夹入的短访谈员回应（backchannel）做穿透合并。

格式 C 因缺失说话人标签无法可靠自动处理，工具会输出诊断报告并以非零状态退出，建议先做人工或 LLM 辅助的说话人预标注再运行。

### 独白类（需 CLI 显式声明）

| 格式 | 特征 | 典型来源 | CLI 参数 |
|---|---|---|---|
| E | 单一说话人的长文本，无说话人标签 | 日记法研究、自传体访谈、健康博客、开放问卷长答 | `--format monologue` |
| F | 研究者撰写的叙事散文，含多重声音（观察/引语/解释/理论） | 民族志出版物、田野笔记 | `--format narrative` |

E 和 F 均按空行切分自然段。两者的根本区别在于：

- **Format E** 的所有内容都被视为单一说话人的自述，命题都赋给同一个 speaker
- **Format F** 识别为"研究者撰写但内含多重声音"，每条命题额外标注三个字段：
  - `subject` — 命题**关于谁**的情况（如"梁奶奶""护工""一般"）
  - `voice` — 命题**由谁的口吻**表述（如"研究者""梁奶奶""护工"）
  - `layer` — 命题层次，取 `observation`（研究者观察）/ `quote`（他人引语）/ `interpretation`（研究者推论）/ `theory`（一般性理论） 之一

Format F 支持主体白名单约束（CLI `--subjects "梁奶奶,余奶奶,护工,..."`），LLM 被要求只从白名单中选取 subject 与 voice，保证后续分析时的标签一致性。

## 参数自动推断

工具对每份输入自动推断运行时参数，研究者无需手动调参。推断项包括：

- **说话人角色映射**：启发式基于问号率、平均字数、总字数的加权评分识别访谈员；LLM 在可用时复核修正；若 `base_defaults.yaml` 中配置了 `known_interviewer_names`，命中的姓名直接定为 interviewer。独白类（E/F）跳过此推断
- **`segmentation.max_length`**：基于该文件小句长度分布的 95 百分位自适应调整
- **同说话人合并 gap 阈值**：基于该文件同人连续轮次的时间间隔 95 百分位
- **情境朗读（vignette）识别**：访谈员长轮次中命中触发词时启用
- **ASR 噪声过滤**：全文英文字符比超过阈值时启用

所有推断依据写入审计报告的"参数推断溯源"节，便于研究者人工复核。不满意的推断可通过 `--override` 参数在命令行单键覆盖。

## LLM 层

### 多厂商统一客户端

工具实现了统一的 LLM 调用接口，在 `llm_config.yaml` 中切换 `active_provider` 即可切换厂商。预置配置包括：

- **OpenAI 兼容协议**：OpenAI、DeepSeek、通义千问 Qwen、智谱 GLM、月之暗面 Kimi、字节豆包、百度文心（千帆）、本地 vLLM/Ollama
- **Anthropic 原生协议**：Claude Sonnet / Opus / Haiku

三种调用模式：`disabled`（纯规则层，不调用 LLM）、`mock`（内置离线响应用于测试）、`live`（真实调用）。

### 三种 prompt 模式

命题识别对不同格式用不同的 prompt：

| prompt_mode | 适用格式 | 产出字段 | 特殊机制 |
|---|---|---|---|
| `interview` | A / B / D | 基础字段 | 识别基于 Graneheim 框架的意义单元 |
| `monologue` | E | 基础字段 | 同上，但 speaker 统一 |
| `narrative` | F | 基础字段 + `layer` + `subject` + `voice` | 按自然段调用，每次调用带前后段作为上下文参考 |

**叙事模式下的前后段上下文**：在 Format F 中，工具给 LLM 除当前段外额外提供"前一段"和"后一段"作为**上下文参考**，但命题识别范围严格限定在当前段。这解决了类似"梁奶奶:'你是我舅家的娃'"这种短对话段落脱离上下文后 LLM 无法判断说话场景的问题。上下文段落做 240 字截断，首段/末段自动降级为"无前文/无后文"提示。

### 两项推断任务

1. **说话人角色复核**（每份访谈 1 次调用，独白类跳过）：启发式先给出基线，LLM 基于每位说话人的样本发言复核修正，置信度高于阈值时采纳 LLM 结果，否则回退启发式
2. **命题识别**（每份输入 30–60 次调用）：对每个符合条件的语义轮次单独调用，返回该轮次的命题列表

温度统一固定 0 以保证同一输入的可复现性。

### 命题识别的可追溯性保证

每条命题的 `source_char_start` / `source_char_end` 是命题在 `CanonicalTurn.text` 中的字符偏移。由于 LLM 对字符偏移的计算不总是精确，脚本对返回值做独立验证：若 `text[start:end]` 不等于 `source_excerpt`，尝试在原文中搜索摘录文本；搜索失败则打 `char_range_unreliable` 标签但保留命题。`related_clause_ids` 字段把每条命题映射回规则层的子句 ID，便于在 QDA 软件中对照原文。

### 进度显示

命题识别阶段耗时较长（典型 3–6 分钟一份），工具提供命令行进度条显示完成数、百分比、预计剩余时间与当前处理的轮次 ID。进度显示通过回调接口 `progress_callback(current, total, message)` 实现，命令行输出与未来可能的 Web UI 推送共享同一接口，业务逻辑无需修改。

## 配置层

### 三层配置合并

最终生效配置由三层叠加产生：

1. **base_defaults.yaml**（研究级常量，发行时冻结）
2. **detected_config**（每份输入运行时自动推断）
3. **CLI `--override`**（用户显式覆盖）

每次运行产出 `config_snapshot.yaml`，对每个配置键标注其来源（`default` / `detected` / `user_override`）。该快照可随论文补充材料发布，作为该份输入处理的复现凭证。

### LLM 配置独立

`llm_config.yaml` 独立管理 LLM 厂商、模型、API 密钥等信息。API 密钥通过环境变量传入（`api_key_env` 字段指定环境变量名），配置文件本身不含敏感信息，可安全纳入版本控制或在团队间分享。

## 命令行接口

```
python -m src.extract --input <文件> --output-dir <目录> [选项]
```

核心参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--input` | 必需 | 输入文件路径 |
| `--output-dir` | 必需 | 输出目录（自动创建） |
| `--llm-config` | 无 | LLM 配置文件，不提供则只跑规则层 |
| `--llm-mock` | 否 | 用 mock 响应替代真实 LLM 调用，离线测试用 |
| `--format` | `auto` | `auto` 自动检测访谈格式 / `monologue` 单人自述 / `narrative` 叙事民族志 |
| `--speaker-label` | `自述者` | `--format monologue` 下的说话人标签 |
| `--narrator-label` | `研究者` | `--format narrative` 下的叙述者标签 |
| `--subjects` | 空 | `--format narrative` 下的主体白名单，逗号分隔 |
| `--base-config` | 项目根 `base_defaults.yaml` | 基础配置文件路径 |
| `--override` | 可多次 | 形如 `key.path=value` 的单键覆盖 |

典型调用：

```bash
# 自动检测访谈（A/B/D）
python -m src.extract --input "data/raw/访谈_01.docx" --output-dir "data/processed/访谈_01/" --llm-config llm_config.yaml

# 日记/自述
python -m src.extract --input "data/raw/日记_李某.txt" --output-dir "data/processed/日记_李某/" --format monologue --speaker-label "李某" --llm-config llm_config.yaml

# 叙事民族志
python -m src.extract --input "data/raw/等待嘟嘟.txt" --output-dir "data/processed/等待嘟嘟/" --format narrative --subjects "梁奶奶,余奶奶,护工,梁小女儿,余女儿,研究者,一般" --llm-config llm_config.yaml
```

## 产出目录结构

每次运行在 `--output-dir` 下产出：

```
<output_dir>/
├── propositions.csv          主产出：LLM 识别的命题
├── propositions.jsonl        同上，程序友好
├── clauses.csv               规则层子句（审计用）
├── clauses.jsonl
├── canonical_turns.jsonl     重建后的语义轮次
├── audit_report.md           人类可读摘要
├── config_snapshot.yaml      实际生效配置（每键标注来源）
└── metadata.json             版本、输入哈希、LLM 调用 trace
```

### propositions.csv 字段

| 字段 | 说明 | 出现条件 |
|---|---|---|
| `proposition_id` | 确定性 ID，如 `interview01_p_0005_03` | 所有格式 |
| `source_file` | 源文件名 | 所有格式 |
| `turn_id` | 所属 CanonicalTurn 的 ID | 所有格式 |
| `index_in_turn` | 该命题在所属轮次中的序号 | 所有格式 |
| `speaker_raw` | 说话人原标签 | 所有格式 |
| `speaker_role` | 规范角色（`interviewer` / `primary_informant` / `family_member` / `patient` / `other_participant` / `unknown`） | 所有格式 |
| `speaker_stable_id` | 同一文件内跨轮次稳定的人员 ID | 所有格式 |
| `timestamp_seconds` | 时间戳（秒） | A / D 格式 |
| `label` | 4-10 字中文短标签 | 所有格式 |
| `paraphrase` | LLM 凝练的一句话说明 | 所有格式 |
| `source_excerpt` | 原文精确摘录 | 所有格式 |
| `source_char_start` | 原文字符起始偏移 | 所有格式 |
| `source_char_end` | 原文字符结束偏移 | 所有格式 |
| `related_clause_ids` | 对应的子句 ID 列表 | 所有格式 |
| `confidence` | 识别置信度 | 所有格式 |
| `flags` | 标签列表（可能含 `low_confidence` / `char_range_unreliable`） | 所有格式 |
| `llm_provider` | 调用的 LLM 厂商 | 所有格式 |
| `llm_model` | 调用的具体模型 | 所有格式 |
| `layer` | `observation` / `quote` / `interpretation` / `theory` | **仅 Format F** |
| `subject` | 命题关于谁的情况 | **仅 Format F** |
| `voice` | 命题由谁的口吻表述 | **仅 Format F** |

### 审计报告（audit_report.md）

包含六个主要章节：

1. **参数推断溯源**：说话人角色映射表、各推断参数的方法与依据、LLM 复核决策的来源
2. **输入文件摘要**：检测格式、字符数、原始轮次数、重建轮次数、产出单元数
3. **角色分布**
4. **轮次重建统计**：合并数、跨 backchannel 穿透合并数
5. **意义单元统计**：长度分布、边界来源分布、flag 分布
   - **5.5 命题识别（LLM 产物）**：API 调用数、成功/失败轮次数、命题总数、置信度与长度分布、前 10 条样本预览
6. **建议人工复核**：被归为 `other_participant` 或 `unknown` 的轮次清单

## 目录结构

```
meaning_unit_extractor/
├── base_defaults.yaml          研究级常量与全局默认（发行时冻结）
├── llm_config.example.yaml     LLM 多厂商配置模板
├── requirements.txt            依赖清单（pin 版本）
├── src/
│   ├── extract.py              主入口 CLI
│   ├── file_reader.py          不信任扩展名的内容嗅探读取
│   ├── format_router.py        访谈格式检测路由
│   ├── parsers/
│   │   ├── format_a.py         时间戳姓名格式
│   │   ├── format_b.py         语义角色格式
│   │   ├── format_d.py         说话人编号格式
│   │   ├── format_e.py         单人自述
│   │   └── format_f.py         叙事民族志
│   ├── models.py               CanonicalTurn / MeaningUnit / Proposition 数据类
│   ├── inference.py            启发式参数推断
│   ├── llm_client.py           多厂商 LLM 统一客户端
│   ├── llm_inference.py        LLM 辅助角色推断
│   ├── proposition.py          LLM 驱动的命题识别（含三种 prompt 模式）
│   ├── reconstruction.py       同人合并与 backchannel 穿透
│   ├── segment.py              子句切分核心算法
│   ├── config.py               三层配置合并与快照
│   ├── audit.py                审计报告生成
│   ├── export.py               输出导出
│   └── progress.py             进度条与通用回调接口
└── data/
    ├── raw/                    原始文件放此
    └── processed/              每份输入的输出目录（脚本自动创建）
```

## 方法学注意事项

命题识别由 LLM 完成，属于解释性操作。在方法部分应披露：

- 模型名称与版本
- prompt 全文（见 `src/proposition.py` 中的 `SYSTEM_PROMPT` / `SYSTEM_PROMPT_NARRATIVE`）
- 温度与置信度阈值
- 人工复核比例
- 若使用 Format F 的叙事分层编码，需另行说明 layer / subject / voice 三字段的分析作用

建议对至少 10%–20% 的命题做独立人工编码并计算 Cohen's κ 或 Krippendorff's α，作为 LLM 命题识别的信度证据。这是当前 BMC Medical Research Methodology、Qualitative Health Research 等期刊对 AI 辅助质性分析审稿的常见要求。

若 LLM 输出被人工覆盖修改，建议另存 `propositions_reviewed.csv`，保留原 `propositions.csv` 作为"AI 基线"供方法学透明度披露。

## 已知限制

1. **字符偏移不总是精确**：LLM 对字符区间的计算能力有限，脚本做了独立验证，仍可能出现 `char_range_unreliable` 标签。这些命题仍然有效（label 和 excerpt 可用），只是无法自动映射回子句
2. **ASR 同音字错误不自动修正**：如"核磁"被误识别为同音字、药物名被误识别等。严重语料建议先人工校正核心术语
3. **格式 C 不支持**：无说话人标签的转录会诊断退出，需人工或 LLM 辅助预标注说话人后再处理
4. **单文件内同一说话人不能中途换人**：例如访谈员中途换人需要手动拆分文件
5. **叙事模式的白名单遵守率约 99%**：LLM 极少数情况会越出白名单（如用"梁老太太"替代"梁奶奶"），建议人工后处理做一次规范化
6. **不同模型产出质量差异**：DeepSeek 等次一级模型产出的命题抽象层次不如 Claude Sonnet 或 GPT-4，在方法学层面建议披露所用模型、必要时做模型敏感性分析

## 依赖

运行时依赖：`pyyaml`、`requests`、`pandas`、`python-docx`。详见 `requirements.txt`。

## 使用

基本使用与分步操作说明请参见 `使用说明.md`。
