# 实验室阶段复盘

2026 年 10 月 25 日至 11 月 21 日。8 名成员，26 份日报、4 份周报。以下内容以这 30 份共享报告为依据；本版本的项目盘扫描数为 0。

共有 11 个研究与协作主题。通用疾病声音 Encoder 与已登记方向吻合，其余 10 个主题由本期材料归纳。

[展开报告和原文摘录](2026-11-21-lab-review.html) · [可机读版本](evidence/2026-11-21-lab-review.json) · [证据校审记录](2026-11-21-lab-review-audit.md)

另行核查了 101 主机上 8 名成员的 24 个项目入口，其中 17 个可读。目录里找到的候选文件还要核查内容、作者与可见范围；读者可对照[逐成员盘点表](../../research-data-center-next/experiments/2026-11-21-public-storage-audit.md)判断这份复盘的覆盖边界。

## 实验室判断

**本期进展**

- 截至本期，实验室已有三种可独立核查的产物：SpeechDX 的逐任务成绩，停顿干预的人级对照，以及音频记忆检索的问题定义；三者分别处于评测、验证假设和任务设计阶段。 [来源 18](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-20) [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly) [来源 26](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-20)
- 基础设施方面，何锋在 11 月 14 日记录制定平台规则、整理 auto-research-hub；严梓诚在 11 月 20 日用一条约 4 分钟视频跑通转写、分段与分流。平台规划和样例跑通各有据可查。 [来源 13](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_65a349fc3c98481589f1&date=2026-11-14) [来源 5](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-20)

**结果与证据**

- SpeechDX 报告 16 项实测、其中 10 项内部数值超过预设公开目标，另记 SVD 独立任务通过；T11 仅 8 名患者，公开测试名单或计分材料尚未核齐，无法确认同协议排名。 [来源 18](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-20) [来源 14](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-16)
- 陆梓健的停顿研究保留了阴性结果：中文四路注入的 8 项校正比较均未显著；波形减半复验平均增加 4.32 个百分点，按身份抽样的 95% 区间为 −0.17 至 +9.51。现有证据尚不能确认稳定增益。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)
- 在各自任务上，评测方式会改变判断：HumDial 拒答样例从选择题改成开放式时，成员报告下降超过 25 个百分点；陆永骅的 MMPsy 分类对照中，仅文本 AUC 0.858，融合韵律 0.845。两者分属不同任务。 [来源 22](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-16) [来源 7](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-17)

**局限与阻塞**

- 跨疾病编码器仍在训练；讨论指出不同疾病时间尺度和多个损失项可能冲突。情绪转换 demo 在健康语音上的试听效果有限，EBM 的小幅提升也缺少足够规模的验证。 [来源 12](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-18) [来源 11](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-16) [来源 21](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-20) [来源 20](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-19)
- 音频检索仍需区分证据未召回与模型未能拒答；音频处理样例中仍有真人串音，持续运行和跨任务去重尚未完成。 [来源 30](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_d42f95eadda34850b869&report=weekly) [来源 5](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-20)

**下一步**

- 建议下次周会先确定三项验收：优先补哪项 SpeechDX 输入或计分协议，如何验证停顿与基线的差异，以及按何种证据片段标注检索基准。三项均需给出可复查的划分或样例。 [来源 14](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-16) [来源 17](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-19) [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly) [来源 26](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-20)
- 平台侧建议把何锋提出的整体设计与具体协作版图作为讨论事项；编码器按模块对照验证，并跟踪训练结果。这里记录周会议题，责任人、排期与验收决定待会议确认。 [来源 13](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_65a349fc3c98481589f1&date=2026-11-14) [来源 11](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-16) [来源 12](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-18)

## 按研究问题阅读

### 通用疾病声音 Encoder

[已登记方向](https://rmp.wuwangwo.top/progress/#directions?item=universal-voice-encoder)

**本期进展**

- 设计语音疾病编码器，分别读取词元和连续时间特征，再按录音聚合。11 月 18 日记录了与远超的讨论，列出 PAN-Mask、HeAR、SVC 三份参考材料并描述架构融合。 [来源 11](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-16) [来源 12](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-18)

**结果与证据**

- 11 月 18 日训练仍在运行。这两份日报尚未提供完成复现的结果、独立验证指标或可交付权重。 [来源 11](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-16) [来源 12](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-18)

**局限与阻塞**

- 讨论指出，不同疾病线索对应不同时间尺度。统一 30 秒窗口与重建目标可能引入偏差，多项损失的贡献需要通过逐项对照来区分。 [来源 11](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-16)

**下一步**

- 讨论建议先在有限任务中逐项验证，再决定跨疾病联合训练；成员计划跑完两个编码器，原报告没有给出验收数值。 [来源 11](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-16) [来源 12](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-18)

### 语音问答与可答性检索

**本期进展**

- 以 AQUA-BENCH 为参照，在 HumDial-EIBench 的 Task1 与 Task2 上派生不可答变体，测试 Qwen3-Omni 拒答表现；加入纯文本对照验证是否使用音频证据。 [来源 22](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-16) [来源 23](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-17) [来源 24](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-18)
- 复盘 VoxMem 实验，调研 A2A Retrieval、多模态对齐检索及 IRIS、REASONAUDIO、PlanRAG-Audio、ReasonVoice 等相关工作。 [来源 24](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-18) [来源 26](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-20)
- 研读文本长时记忆工作 PGMem 与 EMIR²，以 PGMem 为基础构建文本模态记忆生命周期（代码进行中），产出长期纵向基线 benchmark 初步方向文档。 [来源 23](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-17) [来源 30](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_d42f95eadda34850b869&report=weekly)

**结果与证据**

- 可解释性拒答实验：MCQ 分数不可直接采信，开放式掉 25pp 以上；中文拒答结构性缺失约比英文严重一倍；音频信息被真实使用但约四成分数来自选项先验；内部已有证据不足信号（AUC 0.9），线性 gate 接出后中英分别拿回 30.5pp / 15.8pp。 [来源 22](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-16) [来源 23](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-17)
- VoxMem 检索：成员报告直接迁移 IRIS 的数值为 27.5%（日报未注明具体计分指标）；准确检索相关 session 并加入声音线索 caption 后准确率提升；ROUTED 方案随上下文窗口增大准确率持续下降。 [来源 24](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-18) [来源 25](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-19) [来源 30](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_d42f95eadda34850b869&report=weekly)
- 文献对比：REASONAUDIO 表明现有文本—音频检索模型难处理否定、时序、时长等逻辑约束；PlanRAG-Audio 采用 RAG 框架准确率提升但方案细节需验证。 [来源 25](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-19)
- 11 月 20 日形成“音频到音频的推理密集记忆检索”问题定义，目标是在多会话记忆中定位证据，找不到推理链时返回空。当前成果是任务定义，检索模型和基准的有效性尚待实验。 [来源 26](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-20)

**局限与阻塞**

- ROUTED 方案准确率下降根因未定位（检索召回、prompt 噪声或 LLM 时序推理瓶颈）；拒答样本变量耦合，无法区分检索未拿到证据还是模型无法判断证据不足。 [来源 30](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_d42f95eadda34850b869&report=weekly)
- A2A Retrieval 方向未收敛：聚焦具体副语言信息还是通用检索架构不明确；现有音频检索方法更接近快照匹配，时序和多 Session 场景考虑不足。 [来源 24](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-18) [来源 26](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-20)
- 长期纵向基线 benchmark 方向未收敛，需评估投入产出；音频多模态特征融入记忆图及配套 Benchmark、任务设计不清晰；HumDial 文本可能透露情绪信息。 [来源 23](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-17) [来源 24](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-18) [来源 30](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_d42f95eadda34850b869&report=weekly)

**下一步**

- 推进可解释性：让模型输出拒答原因并结合案例定位；复查 HumDial 文本泄漏；设计控制变量实验隔离检索与推理错误来源。 [来源 24](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-18) [来源 30](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_d42f95eadda34850b869&report=weekly)
- 收敛 VoxMem 检索方案：改造为检索基准，按 evidence×operation 补充标注；构建程序化音频难负例；细化以时间为链条的迭代检索。 [来源 26](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-20)
- 多模态长记忆迁移：精读 PGMem、EMIR²，思考音频声学特征接入图记忆节点；调研现有多模态记忆 Benchmark。 [来源 22](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-16) [来源 30](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_d42f95eadda34850b869&report=weekly)

### 语音停顿与认知障碍识别

**本期进展**

- 完成三类停顿梳理（A 话轮内、B 交接间隔、C 互动搁置），强调医学价值需结合位置、上下文和恢复情况。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)
- 完成中文 A 类停顿四路注入初筛（215 条录音、84 身份组），按人五折、冻结编码器、训练小分类器，设基线和错配对照。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)
- 完成 A 类波形对照（187 条录音、81 身份组、30 秒子集，60 次拟合）和 B 类回应间隔补充验证（英文 Pitt 162 条录音、333 次提问回应）。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)

**结果与证据**

- 四路注入 AUC：音频显式 68.50%（+0.02pp）、音频隐式 68.88%（+0.40）、文字显式 68.48%（+1.70）、文字隐式 66.01%（-0.77）；与基线、错配对照 8 项比较均未显著。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)
- A 类波形对照：保留 65.30%、删除 70.24%、减半 71.81%、时长交换 66.30%；减半固定方案 10 种子复验平均 +4.32pp，但 95% 区间 -0.17 至 +9.51 跨 0。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)
- B 类间隔：加入间隔音频 AUC 84.53%→84.73%（+0.20pp），区间 -2.57 至 +3.13；问答重建三臂 AUC 71.08% / 76.42% / 72.67%，减半 +5.33pp，区间 -0.71 至 +12.75。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)

**局限与阻塞**

- 四路注入与基线、错配对照比较均未达统计显著；文字显式上涨比错配低 2.14pp 且区间跨 0，不能归因于个人停顿信息。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)
- 文字显式仅话语段级时标，未精确插入停顿；中文 Chou 缺提问者时间轴，B 类改用英文 Pitt 不能直接推断中文；波形减半 95% 区间仍跨 0。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)
- 现用 Whisper 主要服务语音识别，停顿、语速、重音差异转写可能相同，表征未必可分；现有编码对语音占比和总时长敏感，未保留停顿与前后内容、语调、节奏的关系。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)

**下一步**

- 精读 TextPro-SLM，关注 WhisperPro 如何用 ASR 与声学重建保留副语言信息，整理训练目标和表征评估。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)
- 阅读 VoxParadox（ICML 2026），学习逐层探测，区分编码端信息变弱与下游忽略；整理训练目标、取层位置与副语言信息保留对照表。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)
- 在现有中文配对样本上冻结 encoder 与小探测头，比较不同层、时序池化及停顿处理；先验证表征可读性。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)

### 抑郁检测与 LLM 分类

**本期进展**

- 基于 MentalBERT 尝试能量模型样本筛选与 NCE 多任务联合训练；参考 TextPro-SLM/WhisperPro 完成 Global 与 Interleaving 融合对比。 [来源 6](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-16)
- 用 LLM 充当/后接分类头，对比文字、韵律、文字+韵律及不同转写模型、语音特征层；在完整 LLM 末端增加二分类头对照不同初始化。 [来源 7](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-17) [来源 8](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-18)
- 探究 LLM 后几层接分类头，复查 EATD 基线过拟合、特征降维和早停策略，整理心度日常聊天字段与指标。 [来源 9](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-19) [来源 10](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-20)

**结果与证据**

- 纯文本算法实验完成，音频两种融合三折训练效果不好；EATD 对照 Belle 文字+WhisperPro 韵律 AUC 0.775、阳性 F1 0.432。 [来源 6](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-16) [来源 7](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-17)
- DAIC 逐层实验第 5 层融合 AUC 0.715 vs 仅文字 0.711，韵律增益不明显；MMPsy 对照仅文字 AUC 0.858 vs 融合 0.845，效果主要来自文本。 [来源 7](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-17)
- 原 A/B 权重初始化头在 MMPsy 上 AUC 0.863，与原模型 0.859 接近；F1 从 0.488 升至 0.590，但召回下降；11-20 日报定性描述抑郁与 AD 两项任务的模态表现趋势不同，未提供 AD 的数值或样本范围。 [来源 8](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-18) [来源 10](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-20)

**局限与阻塞**

- 模型基本把所有样本分到最低一档，未学会区分不同抑郁程度。 [来源 6](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-16)
- 还原音频特征的能力变好，但抑郁判断仍不理想。 [来源 6](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-16)

**下一步**

- 11-16 计划重新检查音频训练结构以利用 EBM；后续 11-17 实际转向 LLM 分类头尝试，未直接记录 EBM 检查。 [来源 6](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-16) [来源 7](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-17)
- 已有安排：探索从 LLM 内部哪一层取特征更合适，对比中间层和最后几层接分类头；11-19 已初步探究后几层接分类头。 [来源 7](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-17) [来源 8](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-18) [来源 9](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-19)
- 建议：鉴于韵律增益不明显，可增加韵律特征消融或更换编码方式，并与文本基线在同一验证集上比较。 [来源 7](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-17) [来源 10](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-20)

### 医学语音任务 SpeechDX

**本期进展**

- 屠宇航完成 MDVR T16、TORGO T11、Coswara T24/T25/T26 候选实验与结果复核，并完成帕金森分类 T13 多轮候选实验。 [来源 14](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-16)
- 完成心血管 HFrEF、CirCor、通用语音 AISHELL-1 以及儿童语音和 SLURP 候选实验；邓霁轩同步推进 SpeechDX 和 AD 筛查 S20 三分类映射与微调。 [来源 16](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-18) [来源 19](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-18)
- 多次汇总项目七类任务、数据缺口、公开目标和评测口径，整理已有模型、结果与数据缺口记录。 [来源 15](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-17) [来源 17](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-19) [来源 18](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-20)

**结果与证据**

- 11-16 报告数值：T16 MAE 0.4629（公开 0.571），T11 MAE 0.2409/0.1967（公开 0.244），Coswara T24 AUROC 0.7893（公开 0.7722）、T25 0.8777（公开 0.8573）、T26 macro AUROC 0.6383（公开 0.6281），T13 当前最佳 AUROC 0.9583（公开 0.9625）。 [来源 14](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-16)
- 11 月 18 日报告 T13 五折 AUROC 提升至 0.9708，T15 五折 MAE 降至 0.2077，达到预设公开数值目标。同日报另记录独立任务：HFrEF AUROC 0.9601、AISHELL-1 CER 0.5488% 达到目标，CirCor 加权准确率均值 0.7942。 [来源 16](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-18)
- 11 月 19–20 日报告：16 项有数据任务完成实测，其中 10 项内部数值超过预设公开目标；另记 1 项 SVD 独立任务通过。11 月 19 日列出 10 项因缺数据未开展。部分公开测试名单和计分材料仍缺，仅支持数值比较。 [来源 17](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-19) [来源 18](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-20) [来源 14](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-16)

**局限与阻塞**

- T11 仅 8 名患者，个体差异影响交叉验证。Coswara 的测试集在前序实验中已有使用，需独立数据复核。项目对外比较仍需还原历史测试名单和计分协议。 [来源 14](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-16)
- 11 月 16 日的项目报告列出 UASpeech 患者组、KSoF、Cambridge、AVFAD 和 AphasiaBank 的任务输入缺口。材料能说明当时项目可用范围，获取状态需回最新授权台账核对。 [来源 14](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-16) [来源 17](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-19)

**下一步**

- 继续查看实验结果和日志，对照评测指标，统一比较口径并验证可复现记录；分析儿童语音、SLURP、CirCor 改进方向。 [来源 15](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-17) [来源 16](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-18)
- 获取缺失数据集以推进未开展的 10 项任务，并继续提高已有分数。 [来源 17](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-19)
- 继续整理已完成任务的模型、配置、实验记录和成绩汇总，形成可追溯的阶段成果。 [来源 14](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-16) [来源 18](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-20)

### 副语言 TTS 与情绪转换

**本期进展**

- 使用同内容、不同副语言的合成数据对训练情绪转换模型，11 月 20 日制成试听 demo。 [来源 21](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-20)

**结果与证据**

- 成员报告 demo 可以保持内容并改变说话情绪；W47 周报登记了训练结果、对照和试听材料。效果仍需回听原件核对。 [来源 21](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-20) [来源 28](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&report=weekly)

**局限与阻塞**

- 成员试听认为，迁移到健康相关语音时主要模仿音色；内容和整体表达未达到预期，语气迁移仍不稳定。 [来源 21](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-20) [来源 28](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&report=weekly)

**下一步**

- 继续验证语气迁移；在可用健康语音资料增多后，再评估能否用于数据增强。 [来源 21](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-20) [来源 28](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&report=weekly)

### 音频数据处理管道

**本期进展**

- 搭建降噪、说话人标注和单轨提取链路。从分离两条人声、分别降噪再合并，到复用 MOSS 时间戳处理串音，11 月 20 日已将转写与时间戳提取接入多模态爬虫，并按内容类型分流。 [来源 1](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-16) [来源 2](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-17) [来源 5](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-20)

**结果与证据**

- 11 月 18 日在袁老师精标资料上报告转写字错率 8%；其他指标当时尚未取得。11 月 19 日人工复看发现，源录音噪声及部分参考文本漏记语气词都可能影响错误统计。 [来源 3](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-18) [来源 4](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-19)
- 11 月 20 日以约 4 分钟的一条视频跑通全流程，得到 135 段完整讲话，另保留 133 个短碎片，主要归因于两套时间戳不一致。这是单条样例。 [来源 5](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-20)

**局限与阻塞**

- 11 月 20 日复核发现 AI 轨仍有真人串音；成员认为叠加 MOSS 时间戳后听感改善。跨任务去重、搬运识别与自动持续运行仍待处理。 [来源 5](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-20)

**下一步**

- 与需求方确定标注优先级，比较转写组件，整理可供团队复用的样例并统一去重记录。 [来源 5](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-20)

### 科研平台与 auto-research

**本期进展**

- 何锋进行科研平台整体规划，升级数据分类、进度协调规则；调研 auto-research 和相关智能体工作。 [来源 13](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_65a349fc3c98481589f1&date=2026-11-14)

**结果与证据**

- 制定科研平台规则，整理 auto-research-hub。 [来源 13](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_65a349fc3c98481589f1&date=2026-11-14)

**局限与阻塞**

- 仍待明确：一个好的全流程 agent 体系真正需要什么，什么是通用 agent 之外的卡点；一个 agent 时代好的 infra。 [来源 13](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_65a349fc3c98481589f1&date=2026-11-14)

**下一步**

- 计划下一步整理得出 infra 之外的整体设计，并与舒颜、于翔、曹玫一起优化和明确具体科研管理平台版图。 [来源 13](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_65a349fc3c98481589f1&date=2026-11-14)

### 能量模型与异常检测

**本期进展**

- 邓霁轩开展多轮 EBM 对照；陆永骅另在抑郁分类与量表回归中尝试 MentalBERT 能量样本筛选。两组记录涉及不同任务。 [来源 20](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-19) [来源 6](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-16)

**结果与证据**

- 邓霁轩报告多轮实验有小幅提升。报告没有给出可比较的 OOD 拒识指标。 [来源 20](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-19)

**局限与阻塞**

- 样本量有限，提升的实际意义仍不明确。 [来源 20](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-19)

**下一步**

- 构造特定场景验证能量模型能否改善分布外拒识和异常检测，现阶段这是待验证假设。 [来源 20](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-19)

### 空间音频与动态编码

**本期进展**

- 邓霁轩在 W47 周报汇总空间音频与动态编码的结果和演示。刘思哲另将合成空间音频数据列入后续计划。 [来源 28](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&report=weekly) [来源 12](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-18)

**结果与证据**

- 周报记录，中间记录的内存占用下降；未报告内存下降幅度或实验平台配置。 [来源 28](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&report=weekly)

**局限与阻塞**

- 空间音频整体识别与速度仍需优化；周报未列出基准设备、速度、准确率和内存对照值。 [来源 28](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&report=weekly)

**下一步**

- 继续验证音频编码方案，关注整体识别及速度。 [来源 28](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&report=weekly)

### 达旦语音协作与标注

**本期进展**

- 邓霁轩在 W47 周报归档了达旦语音合作的来源和演示。 [来源 28](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&report=weekly)

**结果与证据**

- 已完成初步样本梳理，周报提供团队总览入口。 [来源 28](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&report=weekly)

**局限与阻塞**

- 周报没有登记样本量、标注通过率或一致性结果，标注范围仍需结合原声核对。 [来源 28](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&report=weekly)

**下一步**

- 推进说话人标注及原声校对。 [来源 28](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&report=weekly)

## 按成员阅读

### 刘思哲

2 份来源。

**本期进展**

- 设计语音疾病编码器，分别读取词元和连续时间特征，再按录音聚合。11 月 18 日记录了与远超的讨论，列出 PAN-Mask、HeAR、SVC 三份参考材料并描述架构融合。 [来源 11](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-16) [来源 12](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-18)

**结果与证据**

- 11 月 18 日训练仍在运行。这两份日报尚未提供完成复现的结果、独立验证指标或可交付权重。 [来源 11](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-16) [来源 12](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-18)

**局限与阻塞**

- 讨论指出，不同疾病线索对应不同时间尺度。统一 30 秒窗口与重建目标可能引入偏差，多项损失的贡献需要通过逐项对照来区分。 [来源 11](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-16)

**下一步**

- 成员计划完成副语言及健康编码器训练；另计划合成空间音频、检查验证集分布偏差。两条工作分别验收。 [来源 12](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-18)

### 靳驰骋

7 份来源。

**本期进展**

- 以 AQUA-BENCH 为参照，在 HumDial-EIBench 的 Task1 与 Task2 上派生不可答变体（选项缺失、证据缺失、前提不成立），测试 Qwen3-Omni 的拒答表现；并梳理可解释性验证实验，加入纯文本对照，验证模型拒答是否真正使用音频证据。 [来源 22](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-16) [来源 23](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-17) [来源 24](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-18)
- 复盘 VoxMem 实验，调研 A2A Retrieval、多模态对齐检索及 IRIS、REASONAUDIO、PlanRAG-Audio、ReasonVoice 等相关工作，对比 VoxMem 与这些方法在查询形式、文档内容、相关性定义和监督信号上的差异。 [来源 24](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-18) [来源 26](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-20)
- 研读文本领域长时记忆工作 PGMem 与 EMIR²，理解其图结构记忆与时序状态演化建模；以 PGMem 为基础构建文本模态记忆生命周期（代码进行中），并产出长期纵向基线 benchmark 初步方向文档。 [来源 23](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-17) [来源 30](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_d42f95eadda34850b869&report=weekly)
- W44 已记录 VoxMem 背景音和副语言随时间变化的识别困难，提出区分音频表征与后续推理瓶颈；后续进一步形成多会话证据检索问题定义。 [来源 29](https://rmp.wuwangwo.top/progress/#team?week=2026-W44&member=m_d42f95eadda34850b869&report=weekly) [来源 26](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-20)

**结果与证据**

- 可解释性拒答实验显示：MCQ 分数不可直接采信，同一模型换开放式会掉 25pp 以上；中文拒答结构性缺失约比英文严重一倍；失败形态是近错选项的稳定确信；音频信息被真实使用但约四成分数来自选项先验；内部已有证据不足信号（AUC 0.9），用线性 gate 接出后中英分别拿回 30.5pp / 15.8pp；Qwen3-Omni 在 AAD 任务表现不佳且存在误拒答，提示可拒答时更严重，IASD 任务中英文表现不错。 [来源 22](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-16) [来源 23](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-17)
- VoxMem 检索相关结果：成员报告直接迁移 IRIS 的数值为 27.5%（日报未注明具体计分指标）；准确检索相关 session 并加入声音线索 caption 后模型准确率提升，表明当前提升关键在检索环节；但 ROUTED 方案随上下文窗口增大准确率持续下降，且情绪时序追踪中选择题模式指标虚高，切换开放式原生生成后严格全对率显著下滑。 [来源 24](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-18) [来源 25](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-19) [来源 30](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_d42f95eadda34850b869&report=weekly)
- 文献对比结果显示：REASONAUDIO 表明现有文本—音频检索模型擅长表层语义匹配但难处理否定、时序、时长等逻辑约束，MLLM 经对比微调后原有推理能力可能受损；PlanRAG-Audio 采用 RAG 框架并以 SQL 替代部分查询过程，准确率有所提升但方案细节及实际有效性仍需验证。 [来源 25](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-19)
- 11 月 20 日形成“音频到音频的推理密集记忆检索”问题定义，目标是在多会话记忆中定位证据，找不到推理链时返回空。当前成果是任务定义，检索模型和基准的有效性尚待实验。 [来源 26](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-20)

**局限与阻塞**

- ROUTED 方案准确率持续下降，根因未定位（检索召回、prompt 噪声或 LLM 时序推理瓶颈），且拒答样本存在变量耦合，无法区分错误来源于检索未拿到证据还是模型拿到证据但无法判断证据不足。 [来源 30](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_d42f95eadda34850b869&report=weekly)
- A2A Retrieval 方向尚未收敛：聚焦具体副语言信息还是构建通用检索架构不明确；现有音频检索方法更接近快照匹配，对时序变化和多 Session 场景考虑不足，VoxMem 同时涉及语义、副语言、时序和可答性判断，任务复杂度更高。 [来源 24](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-18) [来源 26](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-20)
- 长期纵向基线 benchmark 方向和方法尚未收敛，需评估投入产出；PGMem、EMIR² 等结构化状态记忆均为文本方案，音频多模态特征融入记忆图及配套 Benchmark、任务设计尚不清晰；HumDial 数据集文本原则上应中性但纯文本已能透露部分情绪信息，可能影响实验结论。 [来源 23](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-17) [来源 24](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-18) [来源 30](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_d42f95eadda34850b869&report=weekly)

**下一步**

- 推进可解释性：让模型输出判断及拒答原因并结合案例定位问题来源；复查 HumDial 文本中性与情绪线索泄漏；设计控制变量实验隔离检索与推理两个模块错误来源；调研 abstention、uncertainty 相关工作。 [来源 24](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-18) [来源 30](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_d42f95eadda34850b869&report=weekly)
- 收敛 VoxMem 检索方案：将 VoxMem 改造成检索基准，按 evidence×operation 补充目标片段标注；构建程序化音频难负例（调整顺序、加入否定、修改时长）；细化以时间为链条的迭代检索（Re-Act-Observe），优先评估文本语义、时序和逻辑约束建模，不再直接复用 IRIS 属性检索思路。 [来源 26](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-20)
- 多模态长记忆迁移：精读 PGMem、EMIR² 原文，思考音频声学特征（ECAPA、emotion2vec、环境音特征）如何接入图记忆节点；调研现有多模态记忆 Benchmark，构思音频侧新增任务；收敛 agent memory 探索方向，结合节点生命周期评估可行性与创新点。 [来源 22](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-16) [来源 30](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_d42f95eadda34850b869&report=weekly)

### 何锋

1 份来源。

**本期进展**

- 进行科研平台整体规划，升级数据分类、进度协调规则 [来源 13](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_65a349fc3c98481589f1&date=2026-11-14)
- 调研 auto-research 和相关智能体工作 [来源 13](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_65a349fc3c98481589f1&date=2026-11-14)

**结果与证据**

- 制定科研平台规则 [来源 13](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_65a349fc3c98481589f1&date=2026-11-14)
- 整理 auto-research-hub [来源 13](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_65a349fc3c98481589f1&date=2026-11-14)

**局限与阻塞**

- 仍待明确：一个好的全流程 agent 体系真正需要什么，什么是通用 agent 之外的卡点 [来源 13](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_65a349fc3c98481589f1&date=2026-11-14)
- 仍待明确：一个 agent 时代好的 infra [来源 13](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_65a349fc3c98481589f1&date=2026-11-14)

**下一步**

- 计划下一步整理得出 infra 之外的整体设计 [来源 13](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_65a349fc3c98481589f1&date=2026-11-14)
- 计划与舒颜、于翔、曹玫一起优化和明确具体科研管理平台版图 [来源 13](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_65a349fc3c98481589f1&date=2026-11-14)

### 陆梓健

1 份来源。

**本期进展**

- 本周完成三类停顿梳理：A话轮内停顿、B交接间隔、C互动搁置；强调医学价值需结合停顿位置、上下文和停后是否成功恢复，单看总时长或一次长停顿不足以区分找词、记忆提取与补偿。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)
- 完成中文A类停顿四路注入初筛：使用Mandarin/Chou的215条看图描述录音、84个身份组，健康对照与轻度认知障碍标签；按人隔离五折划分，冻结声音和文字编码器、只训练后面小分类器，每方案重复3个随机种子；设置不加停顿基线和不同身份间交换停顿错配对照，比较音频显式、音频隐式、文字显式、文字隐式。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)
- 完成A类停顿波形对照：另取187条中文录音、81个身份组（健康对照104条、MCI83条）的30秒子集，生成保留、删除、减半、时长交换四版音频，分别编码、训练；3个种子、按人五折，共60次拟合，处理1516个目标停顿。同时完成B类回应间隔补充验证：中文Chou缺少提问者时间轴，改用英文Pitt 162条录音、131个身份组、333次明确提问与回应（162条录音的标签构成为HC 34条、AD 121条、MCI 7条），从提问结束算到首次词语或填充词回应；沿用按人五折、冻结Whisper、训练集内降维和逻辑回归探测，控制提问数量、长度、时长和类型；另在68条录音、62个身份组（录音为HC 12条、AD 55条、MCI 1条）中重建204段问答，将等待段设为实测长度、减半或删除的零值静音，三臂均使用冻结Whisper与小探测头，共15次确定性拟合。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)

**结果与证据**

- 中文A类四路注入初筛AUC：音频显式68.48%→68.50%（+0.02个百分点）；音频隐式68.48%→68.88%（+0.40）；文字显式66.78%→68.48%（+1.70）；文字隐式66.78%→66.01%（-0.77）。各值为3个种子分别完成五折后AUC平均；短、中、长以0.6秒和1.5秒为分界；与基线、错配对照的8项比较经多重比较校正后均未达到统计显著；文字显式较基线+1.70个百分点，但比错配低2.14个百分点，差值区间跨0，尚不能把上涨归因于个人停顿信息。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)
- A类停顿波形对照初筛AUC：保留65.30%、删除70.24%（+4.94）、减半71.81%（+6.50）、时长交换66.30%（+1.00）。减半初筛由65.30%升至71.81%；固定方案换10个新种子复验，保留66.19%、减半70.51%，平均+4.32个百分点，9/10次上涨；按身份组抽样95%区间为-0.17至+9.51个百分点，仍跨0。实验条件记录：该实验使用187条中文录音、81个身份组、30秒子集、3个种子按人五折、60次拟合、1516个目标停顿。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)
- B类回应间隔补充验证：控制提问数量、长度、时长和类型后，加入B类间隔使音频AUC由84.53%至84.73%（+0.20个百分点；身份组95%区间-2.57至+3.13）；与20次错配预测平均结果相比差值区间也跨0。问答重建三臂AUC依次为71.08%、76.42%、72.67%；减半+5.33个百分点，身份组95%区间-0.71至+12.75。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)

**局限与阻塞**

- 四路注入与基线、错配对照的8项比较经多重比较校正后均未达到统计显著；文字显式上涨但比错配低2.14个百分点且差值区间跨0，尚不能把上涨归因于个人停顿信息。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)
- 四路注入未见稳定提升，还不能判断是停顿信息无效，还是当前编码及接入方式未能利用；文字显式当前只有话语段级时标，标记实际追加在对应段末，尚未精确插到“昨天”和“去了”之后；中文Chou缺少提问者时间轴，因此B类改用英文Pitt验证，不能据此直接推断中文提问后的等待。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)
- 波形减半、B类间隔增益及问答重建减半增益的95%区间仍跨0；现用Whisper主要服务于语音识别，同一句话停顿、语速或重音不同转写仍可能相同，训练未必要求这些差异在输出表征中保持可分；现有编码与时间窗汇总可能对语音占比和总时长较敏感，却未充分保留停顿与前后内容、语调和节奏的关系。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)

**下一步**

- 计划精读TextPro-SLM，重点看WhisperPro如何用ASR与声学重建约束保留副语言信息，以及文本token与韵律向量如何对齐；整理可借鉴的训练目标和表征评估。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)
- 计划阅读VoxParadox（ICML 2026），重点学习逐层探测，区分编码端信息变弱与下游忽略；结合Whisper、WavLM/HuBERT，整理训练目标、取层位置与副语言信息保留的对照表。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)
- 计划在现有中文配对样本上尝试冻结encoder与小探测头，比较不同层、时序池化及停顿处理；先验证表征可读性，再检验不同处理是否改变信息保留。 [来源 27](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)

### 严梓诚

5 份来源。

**本期进展**

- 搭建降噪、说话人标注和单轨提取链路。从分离两条人声、分别降噪再合并，到复用 MOSS 时间戳处理串音，11 月 20 日已将转写与时间戳提取接入多模态爬虫，并按内容类型分流。 [来源 1](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-16) [来源 2](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-17) [来源 5](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-20)

**结果与证据**

- 11 月 18 日在袁老师精标资料上报告转写字错率 8%；其他指标当时尚未取得。11 月 19 日人工复看发现，源录音噪声及部分参考文本漏记语气词都可能影响错误统计。 [来源 3](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-18) [来源 4](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-19)
- 11 月 20 日以约 4 分钟的一条视频跑通全流程，得到 135 段完整讲话，另保留 133 个短碎片，主要归因于两套时间戳不一致。这是单条样例。 [来源 5](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-20)

**局限与阻塞**

- 11 月 20 日复核发现 AI 轨仍有真人串音；成员认为叠加 MOSS 时间戳后听感改善。跨任务去重、搬运识别与自动持续运行仍待处理。 [来源 5](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-20)

**下一步**

- 与需求方确定标注优先级，比较转写组件，整理可供团队复用的样例并统一去重记录。 [来源 5](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-20)

### 屠宇航

5 份来源。

**本期进展**

- 围绕 SpeechDX 的帕金森、构音障碍和呼吸健康任务，完成了 MDVR T16、TORGO T11、Coswara T24/T25/T26 的候选模型实验与结果复核，并完成帕金森分类 T13 的多轮候选实验（保留历史最佳，分析新方案未提升原因）。 [来源 14](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-16)
- 完成了心血管 HFrEF、CirCor、通用语音 AISHELL-1 以及儿童语音和 SLURP 的候选实验；其中对 CirCor 复现训练/选模/评分并补充受试者隔离验证，保存 SLURP 八路融合模型并测试多候选转写与不同录音通道。 [来源 16](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-18) [来源 17](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-19)
- 多次汇总项目七类任务、数据缺口、公开目标和评测口径，整理已有模型、结果与数据缺口记录，供后续查看和交接。 [来源 15](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-17) [来源 17](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-19) [来源 18](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-20)

**结果与证据**

- 11-16 医学语音任务报告数值：T16 帕金森严重度回归 MAE 0.4629（公开数值 0.571）；T11 构音障碍严重度回归主方案 MAE 0.2409、另一预设候选 0.1967（公开数值 0.244）；Coswara T24 AUROC 0.7893（公开 0.7722）、T25 AUROC 0.8777（公开 0.8573）、T26 macro AUROC 0.6383（公开 0.6281）；T13 帕金森分类当前保留最佳 AUROC 0.9583（公开 0.9625），本轮新增方案未超过原结果。 [来源 14](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-16)
- 11 月 18 日成员再次报告改进、模型复核与保存：T13 五折 AUROC 提升至 0.9708，T15 五折 MAE 降至 0.2077，均达到预设公开数值目标。同日报另记录独立任务：HFrEF 患者级五折 AUROC 0.9601、AISHELL-1 测试字符错误率 0.5488% 达到预设目标，优势较小并冻结；CirCor 15 次基线检查级加权准确率均值 0.7942；儿童语音和 SLURP 新尝试未超过当前最佳。 [来源 16](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-18)
- 11 月 19–20 日报告：16 项有数据任务完成实测，其中 10 项内部数值超过预设公开目标；另记 1 项 SVD 独立任务通过。11 月 19 日列出 10 项因缺数据未开展。部分公开测试名单和计分材料仍缺，仅支持数值比较。 [来源 17](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-19) [来源 18](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-20) [来源 14](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-16)

**局限与阻塞**

- T11 仅 8 名患者，个体差异影响交叉验证。Coswara 的测试集在前序实验中已有使用，需独立数据复核。项目对外比较仍需还原历史测试名单和计分协议。 [来源 14](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-16)
- 11 月 16 日的项目报告列出 UASpeech 患者组、KSoF、Cambridge、AVFAD 和 AphasiaBank 的任务输入缺口。材料能说明当时项目可用范围，获取状态需回最新授权台账核对。 [来源 14](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-16) [来源 17](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-19)

**下一步**

- 继续查看各任务实验结果和日志，对照 SpeechDX 评测指标，统一比较口径并验证候选模型可复现记录；结合错例分析儿童语音、SLURP、CirCor 的改进方向。 [来源 15](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-17) [来源 16](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-18)
- 获取缺失的数据集以推进未开展的 10 项任务，并继续提高已有分数。 [来源 17](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-19)
- 继续整理已完成任务的模型、配置、实验记录和成绩汇总，形成可追溯的阶段成果。 [来源 14](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-16) [来源 18](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-20)

### 陆永骅

5 份来源。

**本期进展**

- 11-16 尝试基于 MentalBERT 的能量模型样本筛选与 NCE 多任务联合训练；参考 TextPro-SLM/WhisperPro，结合 LoRA、Mel 重建和 ASR 一致性约束，完成 Global 与 Interleaving 融合对比，并启动连续 SDS 回归实验。 [来源 6](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-16)
- 11-17 至 11-18 用 LLM 充当/后接分类头，对比文字、韵律、文字+韵律及不同转写模型、语音特征层；在完整 LLM 末端增加二分类头并对照从零训练、统一 A/B 映射、原 A/B 权重初始化；在 EATD 训练后迁移到 MMPsy 测试纯文字、纯韵律和融合输入的泛化。成员自述：感觉直接让 LLM 判断有一定效果，用 LLM 判断特征可能更有泛化性，但当前文字作用更明显。 [来源 7](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-17) [来源 8](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-18)
- 11-19 至 11-20 探究 LLM 后几层接分类头、尝试抑郁文字与音频基线融合头；复查 EATD 基线过拟合、特征降维和早停策略；查看算法中文字与韵律关系；整理心度日常聊天字段与指标。 [来源 9](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-19) [来源 10](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-20)

**结果与证据**

- 11-16 完成纯文本算法实验；音频完成两种融合的三折训练，但效果不太好。 [来源 6](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-16)
- EATD 对照：Belle文字+WhisperPro韵律 AUC 0.775、阳性F1 0.432；DAIC 逐层实验第5层融合 AUC 0.715 vs 仅文字 0.711，韵律增益不明显；MMPsy 对照仅文字 AUC 0.858 vs 融合 0.845，当前效果主要来自文本。 [来源 7](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-17)
- 11-18 原 A/B 权重初始化头在 MMPsy 上 AUC 0.863，与原模型 0.859 接近；F1 由 0.488 升至 0.590，但召回有所下降。成员自述：虽然效果都不是很准，但跨数据集效果稍微稳定一点。 [来源 8](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-18)
- 11-19 文字/音频融合头没有明显优化；11-20 成员定性观察为抑郁任务中文字更好、AD 中趋势相反；该日报没有给出 AD 的样本范围与指标。 [来源 9](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-19) [来源 10](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-20)

**局限与阻塞**

- 模型现在基本把所有样本分到最低一档，未学会区分不同抑郁程度。 [来源 6](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-16)
- 还原音频特征的能力变好，但抑郁判断仍不理想。 [来源 6](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-16)

**下一步**

- 已有安排（11-16）：重新检查当前音频训练结构，明确如何利用 EBM。后续 11-17 转向 LLM 分类头尝试，未直接记录 EBM 检查。 [来源 6](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-16) [来源 7](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-17)
- 已有安排（11-17 至 11-18）：探索从 LLM 内部哪一层取特征更合适，对比中间层和最后几层接分类头，并与直接用 LLM 输出判断对比。后续 11-19 已初步探究利用 LLM 后几层接分类头。 [来源 7](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-17) [来源 8](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-18) [来源 9](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-19)
- 已有安排（11-19 至 11-20）：优化 LLM 后的分类头和输入 LLM 前的特征提取，并尝试将 LLM 微调好。建议：鉴于韵律增益不明显，可增加韵律特征消融或更换编码方式，并与文本基线在同一验证集上比较。 [来源 9](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-19) [来源 10](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-20) [来源 7](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-17)

### 邓霁轩

4 份来源。

**本期进展**

- SpeechDX 稳步推进，AD 筛查 S20 算法正在做三分类映射和微调。 [来源 19](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-18)
- 针对 EBM 方法开展了多轮实验。 [来源 20](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-19)
- 完成副语言 TTS 情绪转换 demo，并整理了达旦语音合作、副语言研究、空间音频与动态编码的工作结果和演示。 [来源 21](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-20) [来源 28](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&report=weekly)

**结果与证据**

- 能量模型（EBM）实验基本显示有提升，但幅度很小。 [来源 19](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-18) [来源 20](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-19)
- 已提供副语言情绪转换 demo，并整理训练结果、对照实验和试听材料。 [来源 21](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-20) [来源 28](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&report=weekly)
- 达旦样本已完成初步梳理，空间音频与动态编码减少了中间记录的内存占用。 [来源 28](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&report=weekly)

**局限与阻塞**

- EBM 提升幅度较小，仅几个点且数据量不大，难以看出实际意义。 [来源 19](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-18) [来源 20](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-19)
- 将副语言方法迁移到健康领域效果不佳，只能模仿音色，听到的内容和感受不像 AD 老人，依赖人格设定提示词。 [来源 21](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-20)
- 副语言语气迁移不够稳定，空间音频整体识别和速度仍需优化。 [来源 28](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&report=weekly)

**下一步**

- 成员计划继续推进 SpeechDX、EBM 实验，以及 S20 的三分类映射和微调。 [来源 19](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-18)
- 成员计划探索 EBM 在特殊场景下的效果，验证其对音频边缘分布建模可能提升 OOD 拒识与异常检测能力的猜测。 [来源 20](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-19)
- 成员计划推进达旦样本标注与原声校对，并尝试在健康领域数据更多时迁移副语言方法，继续验证副语言迁移和音频编码方案。 [来源 21](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-20) [来源 28](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&report=weekly)

## 来源清单

1. [严梓诚 · 2026-11-16 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-16)
2. [严梓诚 · 2026-11-17 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-17)
3. [严梓诚 · 2026-11-18 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-18)
4. [严梓诚 · 2026-11-19 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-19)
5. [严梓诚 · 2026-11-20 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_132d761984b3464cb087&date=2026-11-20)
6. [陆永骅 · 2026-11-16 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-16)
7. [陆永骅 · 2026-11-17 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-17)
8. [陆永骅 · 2026-11-18 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-18)
9. [陆永骅 · 2026-11-19 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-19)
10. [陆永骅 · 2026-11-20 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_20b1ff39591646ac9d5d&date=2026-11-20)
11. [刘思哲 · 2026-11-16 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-16)
12. [刘思哲 · 2026-11-18 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_233d0a339e114f5bbb9e&date=2026-11-18)
13. [何锋 · 2026-11-14 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_65a349fc3c98481589f1&date=2026-11-14)
14. [屠宇航 · 2026-11-16 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-16)
15. [屠宇航 · 2026-11-17 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-17)
16. [屠宇航 · 2026-11-18 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-18)
17. [屠宇航 · 2026-11-19 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-19)
18. [屠宇航 · 2026-11-20 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_79a214ead54c43ba960f&date=2026-11-20)
19. [邓霁轩 · 2026-11-18 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-18)
20. [邓霁轩 · 2026-11-19 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-19)
21. [邓霁轩 · 2026-11-20 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&date=2026-11-20)
22. [靳驰骋 · 2026-11-16 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-16)
23. [靳驰骋 · 2026-11-17 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-17)
24. [靳驰骋 · 2026-11-18 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-18)
25. [靳驰骋 · 2026-11-19 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-19)
26. [靳驰骋 · 2026-11-20 日报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_d42f95eadda34850b869&date=2026-11-20)
27. [陆梓健 · 2026-W45 周报](https://rmp.wuwangwo.top/progress/#team?week=2026-W45&member=m_760d85f8a05f40b1a7bc&report=weekly)
28. [邓霁轩 · 2026-W47 周报](https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member=m_b41d517e5f1f4c19a874&report=weekly)
29. [靳驰骋 · 2026-W44 周报](https://rmp.wuwangwo.top/progress/#team?week=2026-W44&member=m_d42f95eadda34850b869&report=weekly)
30. [靳驰骋 · 2026-W46 周报](https://rmp.wuwangwo.top/progress/#team?week=2026-W46&member=m_d42f95eadda34850b869&report=weekly)
