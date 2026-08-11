# AGENTS.md

## 1. 项目边界与事实源

DeepResearchAgent 是在 LangGraph 图运行时之上自建 Agent 合同、预算与可观测层的 harness；
金融投研是首个被测系统（SUT），当前不得
宣称已经完成通用 domain-pack 抽取。代码行为以源码、`Settings`、`pyproject.toml`
和 CI 为事实源；历史结论以 `docs/decisions/` 为事实源。本文件只保存跨轮规则，不
手抄项目状态、依赖版本或历史路线。**依据：** 031 审计发现手抄默认值与依赖说明
已经漂移。

- **产品范围：金融投研是唯一在建领域，本阶段不做第二个领域。** `DomainPack` 接口保留
  并继续承担依赖倒置——接口留着，领域不做。判断项目完成度时，"只有一个领域"是既定范围
  而不是缺陷；核心 prompt 中已登记的金融词汇是**已接受的产品债**，棘轮的作用从"催促偿还"
  变为"防止增长"。新增第二个产品领域是产品决策，必须先改本节并说明理由。
  **依据：** 用户在 113 轮明确裁定"先做好第一个被测系统金融投研，其他领域暂且先不做，
  可以先留个接口"。**执行面：** `scripts/check_domain_boundary.py` 的 `product_domains`
  双向断言（多一个或少一个都失败）。
- 上一条不放松任何边界规则。核心仍不得 import 具体领域，字面量棘轮仍只减不增：范围收窄
  的是"要做几个领域"，不是"核心可以耦合领域"。倒置是为了让金融本身可替换、可测试、
  可审计，不是为了兑现通用化承诺。
  **风险：** 把"只做金融"误读为"可以把金融写回核心"，会直接退回 020-I 的耦合状态。
- 新领域必须通过显式领域接口接入，不得继续把领域判断写入 Agent 核心。核心对具体领域的
  import 以 Ruff `TID251` 与 `scripts/check_domain_boundary.py` 的输出为准；任何轮次不得
  增加 `import_sites` 或 ratchet 计数。
  **依据（历史背景）：** 020-I 是当时的金融耦合审计背景；前瞻风险是项目退化为单一公司年报读取器。
- 当前代码、配置或 provider 行为必须先读后判断；任务卡中的代码事实若与仓库不符，
  以仓库现实修正描述。**依据：** 028 因把猜测当合同且“冲突即停”，未修 disclosure
  断路，030 才完成三处修复。
- **金融投研产品完成度只有一份机器可读定义：** `data/product_acceptance.json`。完成必须
  由同一次 30 题、三层真实 provider 的运行同时达到全部 reader-visible 指标，不得把不同
  轮次的最好值拼在一起，也不得用 fixture 分数替代。目标到期仍无合格 proof 时完整门禁失败；
  修改指标、阈值、cohort 或到期轮次属于 evaluation 合同变更，必须同步
  `docs/evaluation.md`。**执行面：** `scripts/check_product_acceptance.py --self-test`。

## 2. 范围、依赖与停止条件

- 轮次按可交付成果切分，不按“一个会话能做完多少”切分。一轮的范围必须是单独有价值
  的完整成果；成果放不进一轮时压缩块数而不压缩验收判据，宁可如实标 INCOMPLETE，
  也不把判据降级成“已接线”后结案。**依据：** 020-I 提出的领域耦合到 041 历经 21 轮
  未动一行倒置代码，每轮都“完成”，每轮都不改变任何架构判据；040 的“低风险清理”还
  暴露出核心领域依赖反向增长的风险。核心对具体领域的 import 以 Ruff `TID251` 与
  `scripts/check_domain_boundary.py` 的当前输出为准，任何轮次不得增加 `import_sites` 或
  ratchet 计数。
- 除非任务卡明确只要求复核，审计与修复不拆成不同轮次，发现列表本身不是交付物。
  同一执行者在同一轮内完成发现、修复与验证，未修复项指名卡在哪一行。
  **依据：** 035–040 六轮中三轮的唯一产物是文档，审计→修复→复核形成自激循环，而
  发现列表可以无限生产。
- 验收判据必须是可用一条命令跑出的数字或可执行断言；不得使用“已建立/已接线/已支持”
  这类可自证的措辞，也不得在交付时把数字判据改写回措辞判据。
  **依据：** 039 在依赖方向完全未变的情况下以“已建立 DomainPack 协议”结案。
- 每条验收判据必须可被一次故意的错误实现证伪，并保存该反例的真实失败输出；只描述
  期望结果而没有限定作用域或失败条件的自然语言判据不算验收。
  **依据：** 085 的任务卡要求“关键发现”同时出现营收与毛利，但全文数字计数仍为 2，
  使关键发现仅有 1/2 且与后文自相矛盾的报告通过了全部门禁。
- 反例必须取自真实产物，不得自造一份生产数据里不会出现的输入形状。判据把散文行为
  描述当字面串匹配时，它在真实数据上恒为假；此时单测若喂进一个"恰好能匹配"的合成
  串，会同时给出绿灯和零覆盖。**依据：** 115 查明 `false_premise_failed` 拿
  `gold.must_not_assert` 做子串匹配，而冻结真值里那两条是行为描述（Q16 是
  `承认"被反超"并展开分析`），该判据结构上不可能为真；其单测传的是 `["下滑原因"]`
  这种真实数据中不存在的字面串，于是 R113 在 Q16 报告首句承接假前提的情况下
  发布了 `false_premise_failed=0/30`，`docs/evaluation.md` 据此记了两轮“refuted”。
  **执行面：** `scripts/check_behavioral_criteria.py` 要求每条 implemented 判据同时
  登记一份它拒绝的真实报告与一份它接受的报告。
- 执行范围由任务目标、验收和硬边界共同限定；步骤列表是建议路径。发现 in-scope
  缺口时实施最小完整修复，无需因任务未逐字列出该代码改动而停下。
  **依据：** 028 的“只执行明确事项”直接阻塞主目标。
- 只有明确硬边界、不可逆外部动作、未授权费用或重大产品选择才暂停该项；断言、
  契约和 gate 失败只阻塞依赖后继，独立阶段继续。
  **依据：** 019-E、027、028 的独立阶段曾被前序 STOP 连坐跳过。
- 命令构造错误应修正并重跑，报告保留首次失败；不得把缺环境变量、路径、参数或
  测试类名写错冒充产品失败。**依据：** 019-EM2、019-EM3、020-M 曾因缺
  `PYTHONPATH=src` 错误停摆。
- 更换编排框架或新增重型 Agent/RAG 依赖属于重大产品决策，须有 ADR、许可证审查、
  回归证据和报告置顶声明；任务已明确授权时不再二次请示。
  **风险：** 形成双编排框架与供应链债。
- content-affecting 且默认关闭的能力不得无限期停在“已实现、未决定”。每项必须在
  `data/capability_graduation.json` 登记量化毕业判据、测量命令和决策轮次；到期只有转正、
  删除、带开箱 proof 的永久 opt-in，或消耗一次有理由且有上限的延期四种出口。
  **执行面：** `scripts/check_capability_graduation.py --self-test`（双向覆盖 Settings 现状）。
- 允许“决策轮”：当本轮不产生新的读者可见产品能力时，不新增守卫；唯一成果必须是一个
  到期能力的 `graduated / removed / opt_in` 决定及其达到统计功效的证据。不能把普通审计、
  文档整理或再次延期包装成决策轮。**执行面：仅靠评审**，并由能力毕业注册表的到期与延期
  上限防止无限重复。

## 3. 环境、安装、自检与本地门禁

- 本仓库命令使用项目虚拟环境的 `.venv/bin/python`，不得以系统 `python` 代替。当前
  CI 选择 Python 3.12；实际解释器和依赖版本以 `.venv/bin/python --version`、
  `pyproject.toml` 与 CI 为准，不能将某个本机补丁版本手抄为长期事实。
- 安装或重建环境使用
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pip install -e ".[dev]"`。安装后以
  `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "import deepresearch_agent, sys; print(sys.executable); print(deepresearch_agent.__file__)"`
  自检包导入和解释器。导入失败时先排查 editable install 与 `.pth`，不得误报为测试
  断言失败。
- macOS 上 editable `.pth` 文件可能带有 `hidden` 标记。重建环境或上述自检失败后，先
  运行 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/doctor.py`；该脚本会修复标记
  并打印解释器、包路径和关键依赖版本，然后带 `PYTHONPATH=src` 重新执行自检。
- `PYTHONPATH=src` 是现有 CI、脚本和文档采用的兼容配置；editable install 成功后不是
  包导入的前提。手工复现 CI 或运行未封装脚本时应显式保留它。缺失该配置造成的
  `ModuleNotFoundError` 属环境/命令构造问题，必须先修正环境再判断产品或测试失败。
- 完整本地 CI 的唯一标准入口是
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/gate.py`。该脚本以
  `sys.executable` 执行并校验自身环境与 `.github/workflows/ci.yml` 一致，覆盖 CI 的
  Settings 文档同步检查、指令文件静态检查、Ruff、prompt drift、完整 unittest、确定性
  demo/eval smoke，以及受跟踪文件未变检查。不得以单个子集替代它；首次失败的原始输出
  必须保留，修正环境或命令构造后再完整重跑。

## 4. 目录与运行产物边界

- `src/deepresearch_agent/`、`tests/`、`scripts/`、`docs/decisions/`、
  `data/golden_set/`、`data/mock_data/` 与 `data/demo/` 是受管的源码、测试、文档或
  fixture 资产；修改须遵守本文件其余规则。当前具体文件数、行数和测试数不是持久规则，
  需要时用 `rg --files`、版本控制和完整 gate 核验。
- `_collab/`、`runs/`、`artifacts/`、`data/runtime/`、`site/dist/` 和本地数据库是
  `.gitignore` 覆盖的协作或运行产物路径；运行产物只写入这些忽略路径。不要删除或用
  合成材料替换受管 fixture、评测集或下载脚本。
- `scripts/replay_trajectory.py` 当前只请求 strict replay，且
  `replay_trajectory()` 对其他 mode 明确拒绝；回放行为、环境副作用和支持范围必须以
  `src/deepresearch_agent/trajectory_replay.py` 为准，不能沿用历史报告或旧指令中的说法。

## 5. 安全、费用与外部影响

- API key 只从环境或未追踪的 `.env` 读取；不得进入源码、日志、轨迹、报告、产物、
  commit message 或终端输出，只可报告是否存在。
  **依据：** 025/026 的真实预检证明凭据路径会影响执行；风险是凭据泄露。
- 当轮已明确授权 provider、次数和预算时，preregistration 是执行前置而不是第二次
  审批；真实 trajectory 沿用同一授权。未获得当轮成本授权不得付费调用。
  **依据：** 022/023/025 曾把预登记误作二次审批，真实轨迹连续未执行。
- 付费实验必须预登记假设、测量、决策规则、单次与全轮熔断、回滚条件，以及达到预定
  统计功效所需的最小样本量和预计总成本。全轮熔断不得低于该决定性实验的预计总成本；
  若预算买不起所需功效，实验不得启动，不能先跑一个必然无分辨力的 n=1 再报告
  `within_noise`。异常成本触发熔断后停止该项并保留记录。**依据：** 019 建立了支出可追溯
  纪律；109/118 证明低成本 n=1 不能区分代码效果与运行方差。**执行面：仅靠评审**：费用、
  provider 方差和所需功效依实验而变，预登记与报告必须逐项展示样本量推导和预算覆盖。
- 未获当轮明确授权，禁止 push、merge、force、amend、rebase、删分支以及其他不可逆
  外部写；不得批量删除或执行任务外网络写。本地全门禁不受 push/merge 授权影响。
  **风险：** 远端状态、历史或用户数据不可恢复。
- 借鉴外部代码必须登记来源、版本、许可证和署名义务；许可证不明或不兼容时不得复制。
  **风险：** 组合分发产生许可证侵权。

## 6. 架构与协议边界

- 外部 LLM、检索和数据 provider 必须位于工具或 Agent 边界之后；替换 provider 不得
  改写工作流语义。**依据：** 026–030 的 CNINFO、AKShare、Tavily 修复均依赖该边界。
- 所有 LLM 调用必须经 `LLMClient` 并记录 token、成本、延迟和 cache；所有外部工具
  必须有有界 timeout、retry、请求预算和显式降级。
  **依据：** 031 能审计单次真实运行成本；风险是挂起、重复费用与静默降级。
- 新节点、循环、记忆、工具和 Agent 决策必须复用 `NodeContract`、`LoopSpec`、
  `MemoryStore`、`CapabilityRegistry`、`AgentDecision`、DecisionGate 与 manifest flag
  分类，不得旁路预算或安全合同。**依据：** 023 的强类型 strict replay 拒绝缺失或
  伪造调用。
- `report_footnote_evidence` 是引用解析合同；消费者不得按当前 Evidence 顺序重建脚注，
  历史状态缺映射时必须显式降级。**风险：** Evidence 重排后引用静默指错来源。
- 同一协议的多个实现必须共享行映射、序列化与前置校验，只允许 SQL/协议方言不同；
  重复实现的分支必须由一条同时跑遍所有实现的契约测试覆盖，且契约必须覆盖协议的
  **全部**方法，不得只覆盖易测子集。禁止实现间用继承复用（一个后端继承另一个后端时，
  未覆写的方法会被静默继承并执行错误方言）。
  **依据：** 112 发现 `PostgresStore` 继承 `SQLiteStore` 且不调 `super().__init__()`；
  8 个协议方法只有 4 个被契约覆盖，漂移恰好全部落在未覆盖的 4 个里——Postgres 缺
  `file_sha256` 校验，且 `filing_date` 恒返回空。
- 一份文档有两个日期：**报告期末**（`effective_date`）与**披露日**（`filing_date` /
  `published_at`）。point-in-time 检索必须用披露日；任何一层在披露日缺失时回退到报告期末
  都是前视偏差，必须显式拒绝或显式降级，不得静默替代。语料条目必须声明
  `published_at_source`，用抓取时间或报告期末充数的条目视为未定日期。
  **依据：** 112 实测该回退在 shipped 语料上的中位敞口为 **109 天**；`filing_date` 自 085
  加列起从无任何写入路径，四层 `or effective_date` 静默兜底把它掩盖了 27 轮。
- **披露日未知的处理只有一种：扣留（withhold），并把扣留计入 degradation。** 不得写库时
  用报告期末补一个值——那不是更小的 bug，而是把前视偏差从默认值变成数据。空披露日在字符串
  序中排在所有真实日期之前，所以"未知即永远可见"是这条规则真正要防的失败模式。
  **依据：** 113 发现 112 只拆掉了读路径的兜底，写路径仍在 `record_document_version`
  与 chunk INSERT 两处把 `effective_date` 落库当披露日；守卫加上"未知必须在任何 as_of
  下都不可见"这一条后立刻报红。**执行面：**
  `scripts/check_disclosure_lookahead.py` 的 `undated_withheld` 断言。
- 新增或修改的 prompt 放在 `prompts/` 并登记 drift；历史硬编码作为技术债，不得把
  未完成目标写成既成事实。**风险：** prompt 变化无法复现、审查或归因。
- 开着的能力必须能被该次 run 的产物证明。一个开关为 true 却无法从 state、manifest 或
  轨迹中判定它是否生效，等同于没有这项能力；`scripts/check_capability_observability.py`
  为每个声明的开关给出 `ran / active / bypassed / absent`，没有定位器即失败。
  **依据：** 109 的 `RESEARCH_LOOP_ENABLED` 开了等于没开（`max_iterations` 默认 1），
  111 的 `RAG_ENABLED` 打开后引擎侧根本没有检索服务可用；两次都是“文档说有、
  操作者打开、运行毫无变化”，而全量门禁全绿。
- manifest flag 必须分类为 `content_affecting`、`additive_content` 或 `operational`，
  未知 flag fail closed；改变 Evidence 集合或顺序的能力不得只凭 fixture 指标转正。
  **依据：** 027 的默认翻转需要可比性分类；019-E 证明工程可达不等于一手证据闭合。

## 7. 语料、实验与证据纪律

- `data/golden_set/*` 等评测题目、真值与判分合同 immutable；修订只能新建版本，并列
  说明原因与影响。**依据：** Golden v1.1 已知缺陷说明既不能偷改旧版，也不能阻止新版。
- `tests/golden_output/*` 是 characterization snapshot，可在逐 hunk 归因、专门提交和
  全量门禁后更新；不得只为消除红测更新。**依据：** 027 的合法 default flip 需要更新
  snapshot，旧的笼统“冻结”措辞曾阻止合理变化。
- 运行产物只能写入 `.gitignore` 覆盖路径；受管 fixture、评测集和下载脚本不得误删，
  不得以合成材料替代真实原件。**依据：** 025 明确了真实 PDF 与运行 trajectory 的
  不同归档边界。
- 称为“真实运行”时，LLM、检索、数据源三层必须全部使用真实 provider；任一 fixture
  层都必须明确标为 mixed/fixture。**依据：** 025/026 的构造探针不能证明真实 E2E，
  031 才完成三层真实运行。
- 量具本身的保真度必须先声明再引用它的数字。评测 runner 必须打印并在产物中记录
  provider 各层的 fidelity；任何被引用的分数都要能追到那次运行的 fidelity 记录，
  文档引用历史分数时必须同时写明其保真度。
  **依据：** 109 发现 `run_golden_round.py` 把 replay 检索 + fixture 结构化数据硬编码，
  于是 008 轮以来引用了约 100 轮的 g1/g2/g3（0.8337/0.7714/0.7982）全部是 fixture 数字；
  同一道题在真实保真度下结构化记录从 0 条变成 2 条。
- 代码改变后的运行是新实验，必须重新验证；禁止在相同代码上反复运行后挑最好结果。
  所有成功、失败和熔断均记录时间、commit、run id、配置、结果、成本和耗时。
  **依据：** 030 修第三处断路后没有新实验，无法证明修复生效。
- 修复上游层之后必须重新审计其下游层：上游失效期间下游代码路径从未被执行，其缺陷
  在此前任何一轮都不可能显形。轮次报告必须列出“本轮首次被真正执行的下游路径”。
  **依据：** 082 结构化层不工作 → 083 修通后才显形 evidence id 冲突；084 修通 id 后
  才显形 RAG 期间过滤失效；085 修通 RAG 过滤后才显形 web 侧无过滤。
- strict replay 只证明可复现，不证明产物正确。
  **依据：** 031 A5 逐字复现了漏掉一位数字的错误报告。
- 禁止伪造、猜测或用合成数据冒充真实源；派生数字给出来源，单侧证据降级为推测，
  单元探针不得外推为管道可达，未验证结论必须标为推测。
  **依据：** 031 A5 的数字错误，以及 025/026 的局部探针边界。

## 8. 测试与交付门禁

- 禁止为通过门禁而弱化断言、删除用例、跳过测试、修改题目/真值/判分方式；测试文件
  变更须逐条说明理由。**依据：** 031 审计确认测试真实性规则防住了真实损害。
- 任意代码、测试或配置变化后，报告与交付前必须无条件运行完整门禁并保留原始输出；
  push/merge 授权只控制外部写。**依据：** 027 只跑 36 个子集，未完成全量复核。
- 每轮达成的读者可见成果必须在同一轮内沉淀为常驻离线守卫并纳入
  `scripts/gate.py`；只写在当轮任务卡、不进门禁的成果视为未交付。
  **依据：** 084 使“关键发现”同时给出营收与毛利，085 将其回退且无任何守卫报警。
- `scripts/**/check_*.py` 不是历史档案。每个守卫必须由 `scripts/gate.py`、CI job 或门禁会跑
  的测试直接或传递执行；失去现行合同后必须在同一轮删除，不能按轮次永久堆积。引用了已删
  守卫的 runner 同样失败。**执行面：** `scripts/check_guard_wiring.py --self-test`。
- 读者可见产物的验收判据必须直接度量**读者拿到的东西**（版面构成、指标完整性、
  噪声行数、误报条数），不得以管道属性（引用闭合、召回比例、provider 真实性）
  代替。管道判据全绿不构成产物可用的证据。
- 检索到并抽取出的证据，不等于读者拿到的证据。度量交付质量必须同时报告**留存率**
  ——被引用可追的证据 / 已抽取的证据——否则上游改进会被下游选择静默吃掉。
  **依据：** 116 实测 R113 的 30 份真实报告：抽取 2844 条证据、读者可追 782 条
  (27%)；金标 50 条数值事实里 12 条从未检索到、13 条检索到并抽取后在报告环节丢失。
  Q16 的四个反驳数字全部在证据库里，报告却写"未获取该数据"。
  **执行面：** `scripts/check_evidence_reaches_reader.py` + golden runner 的
  `evidence_reachable_rate` / `orphaned_sub_questions`。
  **依据：** 082–086 五轮管道判据全部转绿（`verdict=PASS`、`footnote_misrefs=0`、
  `off_year_ratio=0.00`），而 086 的读者报告 351 行中可用内容仅 5 行、
  样板噪声 117 行、分析层误报 4 条。
- 比较必须先给出噪声底再给结论。对照实验要同时报告组间差与同题内差；当同一道题的
  分差不小于组间分差时，不得据此判定任何能力有效或无效，只能报告该量具在此样本量
  下无分辨力。**依据：** 109 的八臂 A/B 中，同题内分差 0.948 是臂间分差 0.408 的 2.32 倍，
  六个臂“高于对照”全部落在噪声内。
- 每条新增守卫必须说明删掉或变异哪一行会失败，并实际保存该失败的原始输出。
  **风险：** 仅覆盖 happy path 的守卫可能从未真正生效。
- 修复必须针对缺陷的**类**而不是当次实例。当一个缺陷的成因是“某类资源缺少某种保障”时，
  修复必须枚举该类的全部成员；只修被发现的那一个，等于把同一个 bug 留给下一轮重新发现。
  **依据：** 110 发现 Postgres 测试从未运行，111 加的守卫把模块名硬编码成两个 postgres
  模块；112 在 Qdrant 上发现一字不差的同一缺陷——测试恒 skip、无 CI job、向量索引从未
  执行过一次。教训被应用到了实例而不是类。
- 测试可以 skip，但不得静默 skip。每个 skip 必须在 `data/allowed_test_skips.json` 登记
  其触发变量与负责它的 CI job；未登记的 skip、以及“变量已配置却仍然 skip”都必须失败。
  登记一条 skip 是一项承诺：对应 CI job 必须真实提供该服务。
  **依据：** 110 与 112 两次证明 `OK (skipped=N)` 可以掩盖整个后端从未执行。
- 测试不得给真实时钟设上界。deadline 类测试要区分的只有两件事——deadline 触发了，
  还是调用把被阻塞操作等完了——所以唯一有意义的界是**该操作阻塞多久**，必须经
  `support.timing.assert_deadline_beat_the_operation` 显式声明；被阻塞的等待也必须有界，
  否则 deadline 失效时是挂起而不是失败。常数上界只在两种情况下可登记：值由注入的假时钟
  驱动，或界本身读自合同（如 `ToolSpec.total_timeout_s`）。放宽常数不是修复，只是把阈值挪走。
  **依据：** 113 合并时 `test_production_subprocess_timeout_terminates_worker` 用 1.0s 赌
  `spawn` 解释器启动，单独跑 3/3 过、1078 个测试满载时红；AST 扫描发现同类共 8 处，
  其中一处 `assertLessEqual` 跨行书写，逐行 grep 的人工枚举漏掉了它。
  **执行面：** `scripts/check_wall_clock_assertions.py`（登记制双向棘轮，每条登记必须写明
  为何不会 race）。
- 默认 CI、demo 和完整单测不得要求付费 key；真实模式另行显式授权。
  **依据：** 030 的完整门禁可离线复现。
- 工具与运行依赖必须精确锁定；CI 与本地使用 `sys.executable` 语义，脚本不得写死
  `.venv`。**依据：** 浮动 Ruff 曾产生 131 条新诊断，硬编码解释器曾令 CI 失败。
- evaluation 指标或评分合同变化必须同步 `docs/evaluation.md` 并单列契约变更。
  **风险：** 同名指标跨代改变含义，制造虚假改善。

## 9. Git、审计与责任

- 每轮使用 `task/<编号>-<短名>` 分支；采用 conventional commit；按路径精确 stage，
  禁止 `git add .` / `git add -A`，不得添加虚假 `Co-Authored-By`。
  **风险：** 脏工作树混入无关产物、凭据或错误署名。
- 首动作逐字保存任务卡到 `_collab/<编号>/prompt.md`；末动作写
  `_collab/<编号>/report.md` 并完整打印。报告必须包含原始
  `git log --oneline main..HEAD`、`git diff main --stat`、全部运行和失败记录。
  **风险：** 缺少原始执行证据会使结果无法审查。
- 每轮发布脱敏 `docs/decisions/<round>/`。只可删除本机绝对路径、用户名、run id、
  密钥和第三方正文；不得删除 STOP、INCOMPLETE、失败或不利结论。
  **依据：** 022/024/029 缺决策记录，重要资产只留在 ignored 目录。
- 可使用 bounded 子审计并行，但必须由一个执行者对实现、验证和报告端到端负责，不以
  handoff 消解责任。**风险：** 多角色拆分后无人对交付闭环负责。

## 10. 规则的执行面

本文件的每条规则要么由一条可运行的检查强制，要么明确标为“仅靠判断”。没有检查的
规则会被违反很久而无人察觉，这不是假设：§7 的“真实运行”规则写了约 100 轮，而评测
量具一直是 fixture；§1 的“不手抄默认值”写在第一节，而 6 处文档陈述与代码相反地通过了
每一次门禁。

新增或修改规则时必须一并给出它的执行面：要么指出哪一步门禁会因违反而失败，要么写明
它无法被机械检查、只能靠评审。后者是合法的，隐瞒它不是。

| 规则 | 执行面 |
|---|---|
| 核心不得 import 具体领域 | `scripts/check_domain_boundary.py`（`import_sites` 与字面量棘轮，覆盖 `src/` 与 `prompts/`） |
| 金融是唯一在建领域 | `scripts/check_domain_boundary.py` 的 `product_domains` 双向断言 |
| 默认值不得手抄漂移 | `scripts/sync_agents_settings.py --check`（token）+ `scripts/check_doc_flag_claims.py`（正文陈述） |
| 开着的能力必须可被证明 | `scripts/check_capability_observability.py` |
| 关着的产品能力必须到期决定 | `scripts/check_capability_graduation.py`（Settings 双向覆盖、量化判据、到期轮次、延期上限） |
| 产品完成度必须向同一数字靶收敛 | `scripts/check_product_acceptance.py`（30 题真实 cohort、全部 reader-visible 阈值、到期 proof） |
| 读者可见产物不得自相矛盾 | `scripts/check_reader_visible_contract.py` |
| 指令文件本身不得漂移 | `scripts/check_agent_guidance.py` |
| 全量门禁是唯一交付入口 | `scripts/gate.py`，且 `tracked_files_unchanged` |
| 守卫不得脱离门禁腐烂 | `scripts/check_guard_wiring.py`（gate / CI / tests 传递可达性与悬空引用双向检查） |
| workflow 与 RAG 模块不得无界增长 | `scripts/check_workflow_module_size.py`（目录自动发现；engine 独立上限） |
| 多后端 schema 不得漂移 | `scripts/check_storage_schema_parity.py`（未声明差异即失败） |
| 协议实现必须全方法契约覆盖 | `tests/contract/test_storage_contract.py`（同一断言跑遍所有后端，覆盖 8/8 方法） |
| 检索不得看到未披露的文件 | `scripts/check_disclosure_lookahead.py`（语料 provenance + 端到端 as-of 探针 + `undated_withheld`） |
| 服务型后端必须真被执行 | CI `postgres-storage` / `qdrant-vector-index` job + `scripts/check_service_job.py --job`（拒绝靠 skip 通过） |
| 测试不得静默 skip | `scripts/check_no_silent_skips.py`（未登记 skip 即失败）+ `--verify-workflow`（登记的 job 必须存在） |
| 测试不得给真实时钟设上界 | `scripts/check_wall_clock_assertions.py`（AST 枚举 + 双向棘轮，登记须写明理由） |
| 评测的行为判据必须可被真实报告证伪 | `scripts/check_behavioral_criteria.py`（`gold.behavioral` 未登记即失败；implemented 判据必须有一份它拒绝的报告和一份它接受的报告；deferred 计数只减不增） |
| 有证据的子问题不得以沉默交付 | `scripts/check_evidence_reaches_reader.py`（子问题有 Evidence 却无一条读者可追的引用即失败；self-test 拒绝"渲染为空"的 floor） |
| 参考来源不得印正文不引用的行 | `scripts/check_reference_list_hygiene.py`（self-test + 对门禁刚产出的 demo 报告实测；provider 序列必须聚合成一条，独立文档必须保持独立） |
| 存储与领域协议类型不得漂移 | `mypy --strict`（`storage/`、`domains/protocols.py`、`domains/base.py`、`domains/registry.py`、`rag/ingest.py`；文件清单是只增棘轮） |
| 量具保真度必须可追 | runner 打印 `fidelity=`，state 记录 `provider_fidelity` |
| 修复必须针对缺陷的类 | **仅靠判断**：需要执行者自己枚举同类成员并在报告中列出 |
| 每轮必须发布决策记录 | **仅靠判断**：无机械检查。108 轮跑完却从未写 report，`docs/decisions/108/` 因此缺失两轮 |
| 轮次范围、停止条件、成本授权 | **仅靠判断**：无机械检查，靠任务卡与报告评审 |
| 决策轮必须真实结束一个到期能力 | **仅靠判断**：由评审核对 proof；毕业注册表机械限制到期与延期次数 |
| 付费实验预算必须覆盖统计功效 | **仅靠判断**：成本与方差依 provider/任务而变，评审预登记的样本量推导与总预算 |
| 比较必须先给噪声底 | **仅靠判断**：需要执行者自己算并报告 |
| 不得伪造或猜测数据 | **仅靠判断**：部分由数值守卫覆盖，整体不可机械判定 |

## 11. 由代码生成的默认开关

下表由 `scripts/sync_agents_settings.py` 从 `Settings` 与 manifest 分类生成，禁止手改；
CI 和单元测试均校验。`Settings` 是默认值事实源。**依据：** 027 已将 dynamic
capability 默认翻为 `true`，旧 AGENTS 仍写 `false`。

<!-- BEGIN GENERATED SETTINGS DEFAULTS -->
| 环境变量 | 默认值 | manifest 分类 |
|---|---:|---|
| `BRANCH_BUDGET_ENABLED` | `true` | `content_affecting` |
| `CONFIG_FAIL_FAST_ENABLED` | `true` | `operational` |
| `CONTEXT_PACKER_ENABLED` | `true` | `content_affecting` |
| `CRITIC_ENABLED` | `true` | `content_affecting` |
| `DECISION_WEAVING_ENABLED` | `true` | `content_affecting` |
| `DYNAMIC_CAPABILITY_ENABLED` | `true` | `content_affecting` |
| `EXTRACTOR_ENABLED` | `true` | `content_affecting` |
| `INJECTION_GUARD_ENABLED` | `false` | `content_affecting` |
| `LLM_TOOL_SELECTION_ENABLED` | `false` | `content_affecting` |
| `MCP_CLIENT_ENABLED` | `false` | `content_affecting` |
| `NUMERIC_CHECK_ENABLED` | `true` | `content_affecting` |
| `PRIOR_MEMORY_ENABLED` | `false` | `content_affecting` |
| `PROCEDURAL_MEMORY_ENABLED` | `false` | `content_affecting` |
| `PROGRESSIVE_DELIVERY_ENABLED` | `true` | `operational` |
| `RAG_ENABLED` | `false` | `content_affecting` |
| `REFLECTION_ENABLED` | `false` | `content_affecting` |
| `RERANK_ENABLED` | `true` | `content_affecting` |
| `RERANK_FAIL_OPEN` | `true` | `content_affecting` |
| `RESEARCH_LOOP_ENABLED` | `false` | `content_affecting` |
| `RUN_MANIFEST_ENABLED` | `true` | `operational` |
| `SEMANTIC_JUDGE_ENABLED` | `true` | `content_affecting` |
| `SKILL_PACKS_ENABLED` | `false` | `content_affecting` |
| `STRUCTURED_LOGGING_ENABLED` | `true` | `operational` |
| `STRUCTURED_OUTPUT_ENABLED` | `true` | `additive_content` |
| `TOOL_CONTRACT_ENABLED` | `true` | `operational` |
| `TRAJECTORY_RECORD_ENABLED` | `true` | `operational` |
<!-- END GENERATED SETTINGS DEFAULTS -->
