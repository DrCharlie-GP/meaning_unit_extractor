# 使用说明

本文档面向**没有 Python 基础的研究者**，按步骤完成从安装到出结果的全流程。每一步都假设您从零开始。命令分 Windows 与 macOS 两版给出，以 Windows 为主，macOS 差异点单独注明。

读完本文约需 15 分钟。真正操作一遍（包括首次安装与 API 申请）约需 1–2 小时。之后每新处理一份数据约 5–10 分钟。

---

## 目录

- [第一步：确认 Python 已安装](#第一步确认-python-已安装)
- [第二步：准备项目目录](#第二步准备项目目录)
- [第三步：安装依赖](#第三步安装依赖)
- [第四步：配置 LLM](#第四步配置-llm)
- [第五步：准备您的数据文件](#第五步准备您的数据文件)
- [第六步：运行分析](#第六步运行分析)
- [第七步：查看与使用结果](#第七步查看与使用结果)
- [第八步：常见问题排查](#第八步常见问题排查)

---

## 第一步：确认 Python 已安装

### 操作步骤

打开命令行：

- **Windows**：按 `Win + R`，输入 `cmd`，回车
- **macOS**：启动台搜索"终端"（Terminal），点击打开

在命令行窗口输入：

```
python --version
```

回车后应显示类似 `Python 3.10.9` 或更高版本。

### 可能的情况

**情况一**：显示 `Python 3.9.x` 或更高 → 直接进入第二步

**情况二**：显示 `不是内部或外部命令` 或 `command not found` → 需要安装 Python：
1. 访问 [python.org/downloads](https://www.python.org/downloads/)
2. 下载并安装最新版（3.11 或 3.12 都行）
3. **Windows 用户安装时必须勾选"Add Python to PATH"**（界面底部的复选框）
4. 安装完成后**重新打开命令行窗口**（重要，旧窗口不会识别新安装）
5. 再次运行 `python --version`

**情况三**：显示 `Python 3.8` 或更低 → 版本过低，按情况二的步骤装新版

---

## 第二步：准备项目目录

### 2.1 确定项目位置

假设您把本项目解压到下面这些位置之一：

- **Windows 例子**：`D:\meaning_unit_extractor\` 或 `D:\桌面\meaning_unit_extractor\`
- **macOS 例子**：`/Users/您的用户名/Documents/meaning_unit_extractor/`

**建议**：不要放在中文路径或桌面以外的系统目录里。`D:\` 盘根目录或"我的文档"下比较稳妥。

### 2.2 在命令行中进入该目录

**Windows**：

```cmd
cd /d D:\meaning_unit_extractor
```

注意 `cd` 后面的 `/d` 参数——如果您要从 C 盘切换到 D 盘，必须带 `/d`，否则 CMD 不会跨盘切换。

**macOS**：

```bash
cd /Users/您的用户名/Documents/meaning_unit_extractor
```

进入后命令行的提示符应该变成类似 `D:\meaning_unit_extractor>` 或 `meaning_unit_extractor $`。

### 2.3 确认目录内容

Windows 输入 `dir`，macOS 输入 `ls`，应看到类似：

```
base_defaults.yaml
llm_config.example.yaml
requirements.txt
README.md
使用说明.md
src/
data/
```

如果少了任何一样，说明解压不完整，请重新解压。

### 后续操作都在这个目录下进行

之后每次打开新命令行窗口，都需要先回到这个目录。可以收藏或记下这个命令：

- Windows：`cd /d D:\meaning_unit_extractor`
- macOS：`cd /Users/您的用户名/Documents/meaning_unit_extractor`

---

## 第三步：安装依赖

### 3.1 运行安装命令

在项目目录下输入：

```
pip install -r requirements.txt
```

首次运行会下载并安装 `pyyaml`、`requests`、`pandas`、`python-docx` 四个库，过程约 1–2 分钟。看到 `Successfully installed ...` 就表示成功。

### 3.2 可能遇到的问题

**问题 A**：`pip 不是内部或外部命令`

改用：

```
python -m pip install -r requirements.txt
```

**问题 B**：下载很慢或卡住（尤其国内网络）

加 `-i` 参数改用国内镜像：

```
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**问题 C**：安装过程中出现"权限被拒绝"

Windows 用户：以管理员身份重开 CMD 再运行；或加 `--user` 参数装到用户目录：

```
pip install --user -r requirements.txt
```

macOS 用户：在前面加 `sudo`：

```
sudo pip install -r requirements.txt
```

### 3.3 确认安装成功

输入：

```
python -c "import yaml, requests, pandas, docx; print('OK')"
```

若输出 `OK`，安装完成。若报错 `ModuleNotFoundError`，说明某个库没装上，重新跑一遍 3.1。

---

## 第四步：配置 LLM

这是最关键也最容易卡住的一步。**如果您只想跑规则层切分（不识别命题），可以跳过本步**（在第六步命令中不加 `--llm-config` 参数即可）。

### 4.1 选择 LLM 厂商

工具支持多种 LLM，各有优劣：

| 厂商 | 成本（每份访谈） | 命题识别质量 | 注册门槛 | 适用场景 |
|---|---|---|---|---|
| **DeepSeek** | 约 0.3–1 元 | 良好 | 支付宝微信即可 | **推荐新手入门** |
| Claude Sonnet | 约 20–40 元 | 优秀 | 需国外支付 | 正式发表的语料分析 |
| GPT-4o | 约 20–40 元 | 优秀 | 需国外支付 | 备选，与 Claude 相当 |
| 通义千问 | 约 1–3 元 | 良好 | 国内手机号 | DeepSeek 的稳定替代 |
| 智谱 GLM-4 | 约 1–3 元 | 良好 | 国内手机号 | 同上 |
| Kimi | 约 1–3 元 | 良好 | 国内手机号 | 同上 |

**新手建议**：先用 DeepSeek 跑通全流程，后续想追求更高质量再考虑切到 Claude。

**正式发表建议**：DeepSeek 做前期探索，Claude 做最终分析，论文方法章节披露模型差异。

### 4.2 申请 API 密钥

以 **DeepSeek** 为例（其他厂商流程类似）：

1. 浏览器打开 [platform.deepseek.com](https://platform.deepseek.com)
2. 用手机号注册登录
3. 进入"API keys"菜单，点"创建 API key"
4. 起个名字（如"质性分析"），创建后**立刻复制**形如 `sk-xxxxxxx...` 的完整密钥（关闭窗口后无法再看，只能重建）
5. 在"充值"菜单里充 10–20 元即可（一份访谈约 0.3–1 元）

其他厂商的申请入口：

| 厂商 | 申请入口 | 备注 |
|---|---|---|
| Anthropic Claude | [console.anthropic.com](https://console.anthropic.com) | 需国外信用卡或中转服务 |
| OpenAI | [platform.openai.com](https://platform.openai.com) | 需国外信用卡 |
| 通义千问 | [bailian.console.aliyun.com](https://bailian.console.aliyun.com) | 支付宝登录即可 |
| 智谱 AI | [bigmodel.cn](https://bigmodel.cn) | 国内手机号 |
| Kimi | [platform.moonshot.cn](https://platform.moonshot.cn) | 国内手机号 |

### 4.3 复制配置模板

在项目目录下：

**Windows**：

```cmd
copy llm_config.example.yaml llm_config.yaml
```

**macOS**：

```bash
cp llm_config.example.yaml llm_config.yaml
```

这样就在项目根目录下有了一份您自己的 `llm_config.yaml` 供修改。

### 4.4 编辑配置文件

用记事本、VS Code 或任何文本编辑器打开 `llm_config.yaml`。

找到最上面几行里形如下面的行：

```yaml
active_provider: deepseek
```

把这一行的值改成您想用的厂商代号：

| 想用什么 | 值改成 |
|---|---|
| DeepSeek | `deepseek` |
| Claude | `anthropic` |
| OpenAI | `openai` |
| 通义千问 | `qwen` |
| 智谱 GLM | `zhipu` |
| Kimi | `kimi` |
| 豆包 | `doubao` |
| 文心 | `ernie` |

保存文件，关闭编辑器。

### 4.5 设置 API 密钥环境变量

这一步是把您的 API 密钥告诉系统。密钥不写入配置文件，而是存在系统环境变量里——这样配置文件可以安全分享，不会泄露密钥。

**先确认您用的是哪个命令行**：

- 打开 CMD 时，窗口标题栏写着 `命令提示符` 或 `cmd.exe`
- 打开 PowerShell 时，窗口标题栏写着 `Windows PowerShell` 或 `PowerShell`（**背景通常是蓝色**）
- 两者命令语法**完全不同**，对着错的文档输命令会失败

#### Windows CMD（黑底白字）

**临时设置（仅当前 CMD 窗口有效，关闭即失效）**：

```cmd
set DEEPSEEK_API_KEY=sk-您的完整密钥
```

注意三点：
1. 等号两边**不能有空格**
2. 值**不要加引号**
3. 关闭 CMD 窗口就失效，需要再设

**永久设置（写入系统，新开窗口也有效）**：

```cmd
setx DEEPSEEK_API_KEY "sk-您的完整密钥"
```

注意：`setx` 命令需要**值加引号**（和 `set` 相反）。设置完后**关闭当前窗口，重开一个**才生效。

#### Windows PowerShell（蓝底白字）

**临时设置**：

```powershell
$env:DEEPSEEK_API_KEY = "sk-您的完整密钥"
```

PowerShell 中等号两边**可以有空格**，值**必须加引号**（和 CMD 的 `set` 相反）。

**永久设置**：推荐还是用 CMD 的 `setx` 命令，PowerShell 的永久设置较复杂。

#### macOS / Linux

**临时设置**：

```bash
export DEEPSEEK_API_KEY="sk-您的完整密钥"
```

**永久设置**：在您的 shell 配置文件末尾加上面这一行：

- macOS 默认 zsh：编辑 `~/.zshrc`
- Linux 常用 bash：编辑 `~/.bashrc`

编辑后保存，运行 `source ~/.zshrc`（或 `source ~/.bashrc`），或者重开终端。

#### 各厂商对应的环境变量名

| 厂商 | 环境变量名 |
|---|---|
| Anthropic Claude | `ANTHROPIC_API_KEY` |
| DeepSeek | `DEEPSEEK_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| 通义千问 | `DASHSCOPE_API_KEY` |
| 智谱 | `ZHIPU_API_KEY` |
| Kimi | `MOONSHOT_API_KEY` |
| 豆包 | `ARK_API_KEY` |
| 文心 | `QIANFAN_API_KEY` |

用哪个厂商就设对应的变量名。

### 4.6 验证环境变量设置成功

设置完后在命令行输入（以 DeepSeek 为例）：

**Windows CMD**：

```cmd
echo %DEEPSEEK_API_KEY%
```

**Windows PowerShell**：

```powershell
echo $env:DEEPSEEK_API_KEY
```

**macOS / Linux**：

```bash
echo $DEEPSEEK_API_KEY
```

应该打印出 `sk-xxxxx...`。如果输出空白或原样输出 `%DEEPSEEK_API_KEY%`，说明没设置成功。

### 4.7 快速自检（确认 LLM 真的能调通）

在项目目录下运行：

```
python -c "import yaml; from src.llm_client import LLMClient; cfg=yaml.safe_load(open('llm_config.yaml',encoding='utf-8')); c=LLMClient(cfg); r=c.chat('You are helpful.','Say hello in one word.'); print('OK:',r.text,'| mode:',r.mode,'| model:',r.model)"
```

成功会显示类似：

```
OK: Hello | mode: live | model: deepseek-chat
```

若显示报错，按以下常见情况排查：

| 报错关键词 | 原因 | 解决 |
|---|---|---|
| `环境变量 XXX_API_KEY 未设置` | 没设或设错了 | 回 4.5 重设，记得新开窗口 |
| `401 Unauthorized` / `Incorrect API key` | 密钥复制不完整或已失效 | 去官网重建密钥，重新设置 |
| `404 model not found` | 配置里的 `model` 字段写错 | 去厂商官网确认当前模型名，修改 `llm_config.yaml` |
| `Connection error` / `Timeout` | 网络问题 | 国外厂商需要代理；检查防火墙 |
| `Rate limit` / `429` | 短时间调用过多 | 稍等几分钟再试；初次调用一般不会遇到 |

---

## 第五步：准备您的数据文件

### 5.1 把文件放到合适位置

推荐放到项目下的 `data/raw/` 目录（如果没有这个目录，自己创建一个）。文件名建议**用有意义的中英文标识**：

好的文件名例子：
- `护士访谈_张三_20240131.docx`
- `照顾者访谈_李四.txt`
- `等待嘟嘟.txt`

不推荐：
- `访谈1.txt`（看不出内容）
- `interview.txt`（无法区分多份）

### 5.2 支持的文件类型

- `.txt` 文本文件（UTF-8 编码最佳）
- `.docx` Word 文档
- `.md` Markdown 文件

**注意**：不支持 `.doc`（旧版 Word，需先另存为 `.docx`）、`.pdf`（需先用 OCR 或 Word 另存为文本）。

### 5.3 支持的六种格式

工具自动识别前四种（访谈类），后两种（独白/叙事）需要在命令行里显式声明。

#### 格式 A：带说话人分离的 ASR 输出

典型来源：飞书妙记、腾讯会议转录等。

```
李明(00:05:33): 您今天怎么过来的？

受访者A(00:05:45): 我家人带我来的。
```

#### 格式 B：人工编辑过的转录

```
2024.1.31 照顾者A，认知障碍老人为其母亲

访谈者：您那会儿怎么发现问题的？

受访者：她有一天突然不认识我了。
```

#### 格式 C：无说话人标签（**不支持**）

工具会诊断退出。需要先人工或用 LLM 给转录加上说话人标签（"访谈者："/"受访者："），再按格式 B 跑。

#### 格式 D：带说话人编号的 ASR 输出

典型来源：讯飞听见。

```
说话人 1 00:02

您平时去社区医院吗？

说话人 2 00:06

嗯，去那个校医院。
```

#### 格式 E：单人自述/日记

典型来源：日记法研究、自传体访谈、开放式问卷长答。

```
今天去医院做了复查，医生说我的情况还算稳定。但我感觉最近总是睡不好……

这周末女儿来看我了。她带来了好多吃的，还陪我聊了很久。……
```

没有任何说话人标签，按自然段（空行）切分。

#### 格式 F：叙事民族志 / 田野笔记

典型来源：质性研究著作、民族志出版物、研究者撰写的厚描述文本。

```
梁奶奶，中度失智，79岁，短发，小眼睛，陕西西安人……

我见到梁奶奶的时候，她衣服整洁，表情平和，完全不像护工口中描述的"爱哭包"。
近身照顾她的护工提及，梁奶奶特别容易伤感，每天至少掉两回眼泪……

梁奶奶："你是我舅家的娃。"（误认为我是舅舅家的孩子。）
```

特点：内含多重声音——研究者观察、研究者解释、被访者引语、护工转述、理论讨论等。工具会对每条命题额外标注 **layer**（observation/quote/interpretation/theory）、**subject**（关于谁）、**voice**（谁说的）三个字段。

---

## 第六步：运行分析

### 6.1 普通访谈（格式 A/B/D，自动识别）

```
python -m src.extract --input "data/raw/护士访谈_01.txt" --output-dir "data/processed/护士访谈_01/" --llm-config llm_config.yaml
```

三个参数的含义：

- `--input`：输入文件路径（支持绝对路径，如 `D:\ObsidianFiles\访谈\护士.txt`）
- `--output-dir`：结果输出目录（脚本会自动创建）
- `--llm-config`：LLM 配置文件路径（就是第四步配好的那份）

### 6.2 日记 / 自述（格式 E）

```
python -m src.extract --input "data/raw/日记_李某.txt" --output-dir "data/processed/日记_李某/" --format monologue --speaker-label "李某" --llm-config llm_config.yaml
```

新增两个参数：

- `--format monologue`：显式声明这是单人自述文本
- `--speaker-label "李某"`：CSV 里 speaker 字段显示的名字（默认"自述者"）

### 6.3 叙事民族志 / 田野笔记（格式 F）

```
python -m src.extract --input "data/raw/等待嘟嘟.txt" --output-dir "data/processed/等待嘟嘟/" --format narrative --subjects "梁奶奶,余奶奶,护工,梁小女儿,余女儿,研究者,一般" --llm-config llm_config.yaml
```

新增三个参数：

- `--format narrative`：显式声明这是叙事文本
- `--subjects`：主体白名单，逗号分隔。LLM 的 `subject`/`voice` 只能从这些标签中选，保证后续分析时标签一致。**强烈建议**提供，因为叙事文本的人物称谓变化多（"她"、"梁奶奶"、"妈妈"等），不限制的话 LLM 标签会不一致
- `--narrator-label`：叙述者标签（默认"研究者"，一般不用改）

### 6.4 运行过程中看到的日志

命令跑起来后会依次显示（以叙事模式为例）：

```
[read] 等待嘟嘟.txt 类型=plain_text_utf-8 字符=12034
[format] 用户指定为 narrative
[parse] 解析得 37 条原始轮次
[reconstruct] 原始 37 → 重建后 37
[segment] 产出 245 条子句
[proposition] 开始命题识别（LLM live / deepseek）
[proposition] [##########--------------------] 12/34 ( 35.3%)  ETA 2m18s  处理 t0012
```

进度条会在同一行不断刷新，显示命题识别的完成数与预计剩余时间。

**典型耗时**：
- 简短访谈（<5000 字）：2–4 分钟
- 中等访谈（5000–15000 字）：4–8 分钟
- 长篇叙事（>15000 字）：8–15 分钟

最后看到 `[done] 输出至 ...` 表示成功。

### 6.5 批处理多份文件

**Windows CMD**（在项目根目录下）：

```cmd
for %f in (data\raw\*.txt data\raw\*.docx) do python -m src.extract --input "%f" --output-dir "data/processed/%~nf/" --llm-config llm_config.yaml
```

**macOS / Linux**：

```bash
for f in data/raw/*.txt data/raw/*.docx; do
    name=$(basename "$f" | sed 's/\.[^.]*$//')
    python -m src.extract --input "$f" --output-dir "data/processed/$name/" --llm-config llm_config.yaml
done
```

**注意**：批处理默认用自动格式检测。如果批处理中混有 E/F 格式的文件，需要分开跑（命令行参数不同）。

### 6.6 文件放在别处怎么办

`--input` 接受任意绝对路径，**不需要**把文件复制到 `data/raw/`：

```
python -m src.extract --input "D:\您的研究库\访谈\某访谈.txt" --output-dir "data/processed/某访谈/" --llm-config llm_config.yaml
```

输出目录也可以放别处：

```
python -m src.extract --input "D:\研究库\访谈.txt" --output-dir "D:\研究库\分析结果\访谈_01\" --llm-config llm_config.yaml
```

---

## 第七步：查看与使用结果

### 7.1 输出目录内容

完成后 `data/processed/您的目录名/` 下会有以下文件：

| 文件 | 打开方式 | 说明 |
|---|---|---|
| `propositions.csv` | Excel / WPS | **主产出**：LLM 识别的命题表 |
| `clauses.csv` | Excel / WPS | 规则层子句表（审计用） |
| `audit_report.md` | Typora / VS Code / 任意 Markdown 阅读器 | 审计报告 |
| `config_snapshot.yaml` | 记事本 | 该次运行的完整配置（论文复现凭证） |
| `metadata.json` | 记事本 / 浏览器 | 元数据（输入哈希、LLM 调用 trace） |
| `*.jsonl` | 程序处理专用，**一般不看** | 给脚本读的格式 |

### 7.2 propositions.csv 的重要字段

用 Excel 或 WPS 打开 `propositions.csv`，重点看以下列：

**所有格式共通的字段**：

- `label` — 4-10 字的命题标签，类似人工开放编码
- `paraphrase` — LLM 用自己的话凝练的一句说明
- `source_excerpt` — 原文精确摘录
- `speaker_role` — 说话人规范角色
- `confidence` — LLM 识别信心（0-1）
- `flags` — 若含 `char_range_unreliable` 说明原文定位不准但命题本身有效；`low_confidence` 说明置信度低于阈值

**仅叙事模式（Format F）才有的字段**：

- `layer` — 命题层次：
  - `observation` = 研究者对个案的观察记录
  - `quote` = 他人言语的引语或转述
  - `interpretation` = 研究者的推论与解释
  - `theory` = 脱离个案的一般性理论讨论
- `subject` — 命题**关于谁**的情况（如"梁奶奶"）
- `voice` — 命题**由谁的口吻**表述（如"护工"说的，或"研究者"观察的）

### 7.3 叙事模式的典型用法：按轴筛选

打开 `propositions.csv`，用 Excel 的筛选功能（数据菜单 → 筛选）可以快速按不同轴查看：

**想看某个具体人物的完整叙事**：

1. 点 `subject` 列的筛选按钮
2. 只勾选"梁奶奶"
3. 现在表中只显示关于梁奶奶的命题（观察、引语、解释全都在）

**想看护工作为第三方的所有描述**：

1. 点 `voice` 列的筛选按钮
2. 只勾选"护工"
3. 这些就是护工对各位老人的第三方描述

**想看研究者的一般性理论讨论**：

1. 点 `layer` 列的筛选按钮
2. 只勾选 `theory`

**想看所有的直接引语（失智者自我表达）**：

1. 按 `layer = quote` 和 `voice = 梁奶奶`（或其他被访者）双重筛选

### 7.4 人工复核建议

**重要原则**：LLM 产出是**候选**，不是最终编码。

建议的工作流：

1. 打开 `propositions.csv`
2. 逐行浏览 `label` 与 `source_excerpt`，判断该命题是否合理
3. 不合理的命题可直接在表中编辑 `label` 或在最后一列加一列"人工标注"做标记
4. 另存为 `propositions_reviewed.csv`，**保留原表作为 AI 基线**
5. 对至少 10%–20% 的命题做双人独立编码一致性检验（计算 Cohen's κ 或 Krippendorff's α）

**叙事模式额外复核重点**：

- 白名单外的 `subject`（Excel 筛选 `subject` 列，看有无白名单之外的标签）
- `layer = quote` 但 `voice = 研究者` 的条目（可能是嵌套引语处理问题，需判断 voice 应改为原始发声者还是保留研究者）
- 同一段原文产出的多条命题是否有重复（可根据 `source_char_start` 排序后人工检查）

### 7.5 导入 QDA 软件

`propositions.csv` 可直接导入 NVivo、MAXQDA、ATLAS.ti 等质性分析软件。

**NVivo**（建议方式）：
1. 文件 → 导入 → 数据集 → 选择 `propositions.csv`
2. 每行作为一个分析单元，`label` 字段映射为节点名，`source_excerpt` 为内容
3. 后续在 NVivo 里做二级编码（归并 label 为更高层主题）

**MAXQDA / ATLAS.ti**：类似流程，具体菜单看软件版本。

每条命题的 `source_excerpt` 对应原文片段，`related_clause_ids` 可用于对照 `clauses.csv` 中的上下文。

### 7.6 审计报告查看

`audit_report.md` 用任何 Markdown 阅读器打开，包含六个主要章节：

1. **参数推断溯源**：工具自动推断了哪些参数、依据是什么
2. **输入文件摘要**：格式、字符数、轮次数等
3. **角色分布**
4. **轮次重建统计**
5. **意义单元统计**（含命题识别子节）
6. **建议人工复核**：被归为 unknown 或 other_participant 的轮次清单

方法学论文发表时，建议把 `audit_report.md` 与 `config_snapshot.yaml` 作为补充材料附上，作为该次分析的复现凭证。

---

## 第八步：常见问题排查

### 运行中的问题

**Q：跑到一半报错 "FileNotFoundError: llm_config.yaml"**

A：还没从 `llm_config.example.yaml` 复制出 `llm_config.yaml`。回到 4.3。

**Q：跑到一半报错 "环境变量 XXX_API_KEY 未设置"**

A：环境变量失效了。CMD 窗口关闭后 `set` 的临时变量会失效，`setx` 设的永久变量需要新开窗口才生效。回 4.5。

**Q：命题识别阶段报错率高（`failed_turns` 数值大）**

A：LLM 返回的 JSON 格式不稳定。处理方法：
- 更换更稳定的模型（Claude Sonnet 比 DeepSeek 在 JSON 格式遵循上更稳）
- 重跑一次（临时性网络问题）
- 如果反复失败，把一条失败的原文发我，调 prompt

**Q：产出的 `propositions.csv` 是空的，或命题极少**

A：检查 `audit_report.md` 的"命题识别"节，看是 `eligible_turns` 少（输入太短或被过滤太多）还是 `failed_turns` 多（LLM 调用失败）。

**Q：叙事模式下产出的 subject 有白名单外的值**

A：LLM 不是 100% 遵守白名单（约 1% 的条目会越出）。Excel 里按 `subject` 列筛选，找出白名单外的条目手工修改。Claude Sonnet 比 DeepSeek 遵守更严。

### 结果理解的问题

**Q：产出的命题 `label` 太具体、不够抽象**

A：这是开放编码（in vivo coding）的正常产物。保留细粒度有利于后续二级聚类（axial coding）。若需要更抽象的范畴，在人工复核后自行归纳，或后续用专门的聚类工具。

**Q：产出的命题 `source_char_start` 为空、`flags` 含 `char_range_unreliable`**

A：LLM 对字符偏移计算不够精确，但命题 `label` 与 `source_excerpt` 仍然有效，可以正常使用，只是无法自动映射回 `clauses.csv` 的特定行。

**Q：同一段原文产出了多条相似命题，有重复**

A：LLM 偶尔会对同一语义重复识别。按 `source_char_start` 排序后人工检查是最有效的方式。重复率一般 <5%。

**Q：叙事模式下的 `layer` 分类不准（比如本该 observation 的被标为 interpretation）**

A：observation 和 interpretation 的边界对 LLM 来说是难点。判断原则：
- "研究者看到的事实"（她衣服整洁）→ observation
- "研究者从事实推出的内部状态"（她内心惶恐）→ interpretation
人工复核时重点审视这两类的边界即可。

### 想做特殊操作

**Q：想不用 LLM，只跑规则层切分**

A：去掉 `--llm-config` 参数：

```
python -m src.extract --input "data/raw/X.txt" --output-dir "data/processed/X/"
```

此时只产出 `clauses.csv`，不产出 `propositions.csv`。

**Q：想用 mock 模式离线测试（不消耗 API 额度）**

A：加 `--llm-mock` 参数：

```
python -m src.extract --input "data/raw/X.txt" --output-dir "data/processed/X/" --llm-mock
```

Mock 模式下 LLM 返回占位响应（label 显示为"Mock命题一/二"），用于验证管线但不产生真实命题。

**Q：格式 C（无说话人标签的转录）怎么处理**

A：工具会诊断退出。建议先用 LLM 给转录加上说话人标签（"访谈者："/"受访者："），再按格式 B 跑。

**Q：某一次自动检测把格式判错了**

A：用 `--format` 参数强制指定：
- `--format monologue` 把输入视为单人自述
- `--format narrative` 把输入视为叙事

自动检测只覆盖 A/B/D 三种访谈格式；E/F 必须显式声明。

**Q：想调整命题识别的 prompt**

A：直接编辑 `src/proposition.py` 中的 `SYSTEM_PROMPT`（访谈用）或 `SYSTEM_PROMPT_NARRATIVE`（叙事用）。改动立即生效，下次运行即采用新 prompt。

**Q：想跑很长一份叙事，担心 token 成本**

A：可以先用 `--llm-mock` 跑一遍确认管线通，再用 DeepSeek 跑真实分析（成本约 1–3 元一份），质量满意后再考虑换 Claude 复跑。避免一上来就用 Claude 导致成本不可控。

---

## 如需进一步帮助

若您遇到文档未覆盖的错误或想调整命题识别的 prompt，请把以下三样一起提供：

1. 完整的命令行报错信息（或截图）
2. 对应输出目录下的 `metadata.json`（不含敏感的 API key，放心分享）
3. 几条您不满意的 `propositions.csv` 条目（label + source_excerpt + 您期望的正确结果）

---

## 附：关键命令速查

```bash
# 第一次跑访谈
python -m src.extract --input "data/raw/访谈.txt" --output-dir "data/processed/访谈/" --llm-config llm_config.yaml

# 跑日记
python -m src.extract --input "data/raw/日记.txt" --output-dir "data/processed/日记/" --format monologue --speaker-label "作者" --llm-config llm_config.yaml

# 跑叙事民族志
python -m src.extract --input "data/raw/民族志.txt" --output-dir "data/processed/民族志/" --format narrative --subjects "人物1,人物2,研究者,一般" --llm-config llm_config.yaml

# 只跑规则层（不调用 LLM）
python -m src.extract --input "data/raw/X.txt" --output-dir "data/processed/X/"

# Mock 测试（离线，不消耗 API）
python -m src.extract --input "data/raw/X.txt" --output-dir "data/processed/X/" --llm-mock

# 检查环境变量（Windows CMD）
echo %DEEPSEEK_API_KEY%

# 检查环境变量（macOS / Linux）
echo $DEEPSEEK_API_KEY

# 设置环境变量（Windows CMD，永久）
setx DEEPSEEK_API_KEY "sk-您的密钥"

# 设置环境变量（macOS，临时）
export DEEPSEEK_API_KEY="sk-您的密钥"
```
