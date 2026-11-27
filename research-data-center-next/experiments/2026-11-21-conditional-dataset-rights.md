# 九条公开数据记录的共享条件

2026 年 11 月 21 日。核查对象是飞书台账中的九条记录。这里分别记录发布方允许的用途、团队实际登记的范围，以及现有证据能否支持把原件放进成员共享目录。原目录的权限和归档身份由存储验收记录确认。[发布文件与校验值](evidence/2026-11-21-conditional-dataset-rights.json) · [实机迁移记录](2026-11-21-public-storage-audit.md)

| 资料 | 发布条件与本次取得范围 | 可执行的处理 |
| --- | --- | --- |
| RAVDESS Speech | Zenodo 1188976，v1.0.0；本条只指 24 位演员的语音音频 ZIP。数据作者明确将学术及其他非商业用途归于 CC BY-NC-SA 4.0。飞书记为已验收，条目没有可核的本地文件计数。 | 非商业团队可按许可分享未修改的语音包，随包保留 Livingstone、Russo 的署名、来源和许可证。飞书提示公司研究要按实际用途判断。现有用户用途和包身份一致时可迁；商业或混合用途须核所获授权。 [固定发布](https://zenodo.org/records/1188976) · [作者说明](https://affectivedatascience.com/licensing.html) |
| UltraSuite 四个子库 | UXSSD、UPX、Cleft、UX2020 的已选子集分别登记 3,729、5,948、1,441、2,150 个 WAV。发布方对数据使用 CC BY-NC 4.0。完整主库还包含超声、采集参数、提示等，标签另行发布；官方 rsync 提供当前版本。 | 非商业团队可保留各子库的原署名与许可，分享所取得的原件。原表记为个人私有保存。迁移现有子集时应保留原访问范围，具名的非商业团队用途已确认后才扩大成员范围。现有子集按发布方对应的 core、labels 相对路径逐件核验，进度见下方实机记录。 [项目许可及引用](https://ultrasuite.github.io/#license) · [发布目录与历史标签](https://ultrasuite.github.io/download/) |
| Czech-Laryngectomy | University of West Bohemia，2019-12-20，固定标识 11234/1-3142。机构原记录标记 PUB 和 CC BY-NC-SA 4.0。台账记为三个说话者 ZIP 与一个 README，官方清单可逐一对照。 | 非商业原件分享需署名并附许可，分发适配作品时遵守相同方式共享。原表明确私有保存。现有四件原件均通过发布方校验，可按已确认的成员范围安排。 [官方记录](https://lindat.mff.cuni.cz/repository/items/5ba66397-f457-4ba3-846a-daac8e27130a) |
| BMD-HS | 作者仓许可 CC BY-NC-ND 4.0。台账记“官方归档已验收”“原样私有学术保存”，没有标注固定提交。本次核到的提交含 872 个 WAV 路径。 | 明确非商业成员范围后，可原样分享可确证的发行包。保留 mHealth Lab 署名和许可证；公开转码、裁剪或编辑后录音不在未修改原件授权内。实机 tar.gz 的 877 个文件均已与固定提交的 Git 对象逐项校验。 [固定源码树](https://github.com/sani002/BMD-HS-Dataset/tree/4745751855d15ff5fc9aaed29c32ad3ec7a5d409) · [数据许可](https://github.com/sani002/BMD-HS-Dataset/blob/4745751855d15ff5fc9aaed29c32ad3ec7a5d409/LICENSE) |
| Oral-Cancer | Zenodo 6308119，v0.1.0，单一归档已登记。发布元数据为 CC BY 4.0；第一作者的项目页同时将 YouTube 原录音描述为 fair use，并限定科研教学、谢绝商用。作者项目页链接的旧版与该 ZIP 同属概念记录 3732321。 | 现有证据不足以把所有第三方录音扩大至通用共享。保留现有访问范围和原件；需要更广的再分发时，确认所涉原录音权利和作者条件。 [固定发布](https://zenodo.org/records/6308119) · [第一作者的资料与条款](https://karkirowle.github.io/oral_cancer_corpus/) |
| UK-COVID | Zenodo 11167750，openAccessv1.1，开放版采用 OGL v3.0。30 个文件含 24 个分卷、一个 ZIP 末卷和五份说明或元数据。原表仅确认其中 6 个文件。开放版不含受保护的说话录音。 | 明确属于开放版的原件可复制及共享，按 UKHSA 指定署名，附 OGL 链接并引用发布页所列论文。47 节点已在受限维护会话中逐一确认六件开放版文件；可以迁移这些文件，以部分取得展示。补齐其余分卷以前无法完成解包。 [开放版及署名格式](https://zenodo.org/records/11167750) · [OGL v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/) |

CC BY-NC、BY-NC-SA、BY-NC-ND 的公开条款允许符合条件的未修改原件分享，所查发布页均未要求每位成员单独申请。原表所写的“个人私有保存”说明既有访问边界。项目负责人已确认 RAVDESS、UltraSuite、Czech-Laryngectomy、BMD-HS 属于获准的非商业研究，且仅限现有成员权限。迁移时保留源属主，专属目录 0750、文件 0640、读者组 GID 992。Oral-Cancer 的第三方权利边界继续保留。[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) · [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) · [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/)

后续实机只读核验取得了更直接的证据。47 节点的 Czech 三个 ZIP 与 README 全部符合机构的 MD5；BMD-HS 的一个 126,924,002 字节 tar.gz 对应作者固定提交，全部 877 个文件的 Git 对象哈希逐一相符，其中有 872 个 WAV。UK 实有 6 件开放版原件与官方 MD5 相符，分别是三个 CSV、数据词典、README 和第一个音频分卷 `covid_data.z01`。UltraSuite 实盘四个 WAV 数均与台账吻合；已从源站读到 core-UXSSD 和 core-UPX 的版本均为 1.0，配套合并标签为 1.2，Cleft 标签为 1.0。发布目录未提供 core-Cleft、core-UX2020 和 labels-UX2020 的独立版本号，这些文件依具体发布路径和发布方校验值确定身份。

### UltraSuite 已取得子集

按 47 节点现有音频、提示、标签与说明文件逐路径对照爱丁堡发布方。四个已取得的子集合计 87,265 个原件（13,268 个 WAV，5,962,741,692 字节），全部匹配并已迁入成员共享目录。上游还发布超声图像等其他内容。两个节点分别以门户服务账号核查全部文件，并用两位成员及一位组外账号抽验读取边界。

| 子库 | 已取得文件 | 其中 WAV | 与发布方逐件相符 | 共享目录验收 |
| --- | ---: | ---: | ---: | --- |
| UXSSD | 32,123 | 3,729 | 32,123 | 47、101 均已验证成员读取及组外拒绝 |
| UPX | 46,602 | 5,948 | 46,602 | 47、101 均已验证成员读取及组外拒绝 |
| Cleft | 3,179 | 1,441 | 3,179 | 47、101 均已验证成员读取及组外拒绝 |
| UX2020 | 5,361 | 2,150 | 5,361 | 47、101 均已验证成员读取及组外拒绝 |

[来源回执与共享清单指纹](evidence/2026-11-21-conditional-dataset-rights.json) · [旧入口与访问验证](2026-11-21-public-storage-audit.md)

引用 Cleft 时，数据页仍列修订稿。正式刊发的论文由 Aciel Eshky、Joanne Cleland、Manuel Sam Ribeiro、Eleanor Sugden、Korin Richmond 与 Steve Renals 六人合著。用到人工标注时，还可按发布页引用 Cleland 等人 2020 年的转写研究。UXSSD、UPX、UX2020 的原始集合引用见 Eshky 等人 2018 年的数据论文。[Cleft 期刊定稿](https://doi.org/10.1016/j.specom.2021.05.008) · [Cleft 发布页](https://ultrasuite.github.io/data/cleft/) · [UltraSuite 数据论文](https://doi.org/10.21437/Interspeech.2018-1736)

人工审阅限于发布说明、许可和登记范围。机器以校验值核对文件身份，共读附件只留公开版本信息、聚合计数和摘要。
