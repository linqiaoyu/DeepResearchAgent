# 033 工具失败矩阵与失败回放决策

## 决策

CNINFO 是优先的一手通道，但不是整个研究请求的单点失败条件。连接、timeout、5xx、
rate limit、auth、404、空结果和协议格式异常都在 CNINFO adapter 内 fail closed：不构造、
不猜测任何公告；随后允许 Researcher 查询较低权威的 web 通道。报告必须新增“数据获取
降级”章节，说明 authority 失败及证据覆盖影响。唯一不降级继续的是 run-wide 外部请求
预算拒绝，因为继续请求会绕过成本/配额安全合同。

这一选择优于整体 fail closed 的理由是：authority 失败不等于用户问题不可研究，二手来源
仍可形成带 source tier 的有限答案；但静默 fallback 会让读者把二手材料误认成一手闭合，
所以读者可见告知是该选择的必要组成部分。

## 故障矩阵

注入探针把 transport 异常设为立即返回并禁用真实 backoff，五种目标故障的代码识别均为
0ms（计时分辨率 1ms）。这个数字只证明分支可达，不代表真实网络等待。生产上每个 HTTP
请求仍是 30s；CNINFO `ToolSpec.timeout_s=120s` 未延长，并新增同为 120s 的 logical total
deadline，因此一次完整 retry envelope 的硬上限是 120s，而不是原设计可能出现的 360s。

| 故障 | 通道 | 注入识别 / 生产上限 | retry / circuit | 降级行为 | 用户可见 |
|---|---|---|---|---|---|
| connection refused/reset | CNINFO stock/query/PDF | 0ms / logical ≤120s | transient，最多 3 attempt；3 个失败 logical call 后 circuit open，后续 0 attempt fast-fail | CNINFO 返回空，不接纳伪 authority；转 web | 是，`disclosure_source / transient` |
| transport timeout / 挂起 | CNINFO logical call | 0ms 即时 timeout 注入；另有真实 Event 阻塞 30ms deadline 测试；logical ≤120s | detached worker 不重试；provider 在旧 worker 退出前 quarantine，新 run 零外呼 | 转 web | 是，`timeout` |
| HTTP 503/5xx | CNINFO query/PDF | 0ms / logical ≤120s | transient，最多 3 attempt | 转 web | 是，`transient` |
| HTTP 429 | CNINFO query/PDF | 分类单测即时 / logical ≤120s | rate_limited，最多 3 attempt，独立 backoff policy | 转 web | 是，`rate_limited` |
| HTTP 401/403 | CNINFO query/PDF | 分类单测即时 / 单 attempt | auth，不重试 | 转 web | 是，`auth` |
| HTTP 404 | CNINFO query/PDF | 0ms / 单 attempt | not_found，不重试 | 转 web | 是，`not_found` |
| `announcements=[]` | CNINFO query | 0ms / 单 attempt | 成功调用但显式 `not_found` 事件 | 转 web | 是，“no matching document” |
| 缺 `announcements` / 非列表 | CNINFO query | 0ms / 单 attempt | permanent，不重试；authority 内 fail closed | 转 web | 是，`permanent` |
| 非空 announcement 缺 URL / 证券代码不符 | CNINFO payload | 0ms / 单 attempt | permanent，不重试；拒绝脏 authority | 转 web | 是，`permanent` |
| web transient/timeout/429 | web search/fetch | 各 attempt 受既有 ToolSpec timeout | 按 typed policy retry，失败/恢复均记 event；circuit 可 fast-fail | 返回已有 Evidence 或空集 | 是，已有 chaos tests 覆盖 |
| CNINFO 后 web 也完全失败 | authority + web | 两个通道各自有界 | 各自预算/circuit 独立 | 完成空 Evidence 报告，不伪造答案 | 是，“尚未收集到足够证据” + 降级章节 |
| run-wide request budget 拒绝 | 任一外部通道 | 消耗前立即 | 不重试、不 fallback 绕过 | `budget_exceeded` partial report / terminal | 是，预算决策记录 |

探针原始计数：connection/timeout 各 3 HTTP calls；503 为 6（每 attempt 的 stock GET +
announcement POST）；empty/malformed 各 2；对应 JSON 保存于 ignored
`_collab/033/failure_matrix_probe.json`。

## 失败轨迹回放

旧实现对所有非 `completed` termination 直接 cache miss。现在采用以下合同：

- completed + degraded：严格重放 typed degradation event、web fallback 与报告字节；
- failed + 已有 recorded plan/provider 调用：重建同类 tool error，比较 status、phase、
  error type、error message 和已生成 artifacts；
- budget_exceeded：重建 rejected counter 与 partial report，再比较 typed termination；
- Planner 之前的内部失败：没有计划或后续调用可执行，不伪造 control flow；明确返回
  `unreplayable_internal_failure`，并承认只能验证 trace prefix。

回放状态 `reproduced` 只说明失败/降级轨迹可复现，不说明 fallback 内容正确。本轮没有把
strict replay 作为质量论据。

## 移除验证

共做 15 次实际 mutation 并全部恢复：

- failure handling 7 项：移除 total deadline、degrade event、web fallback、empty event、
  run-context 同步、404 分类、invalid-entry fail-closed guard；
- failure replay 5 项：恢复 blanket rejection、移除 terminal error 重建、移除 budget
  counter、移除 trace degradation event、移除 typed budget terminal metadata。
- blocking/isolation 3 项：允许 detached timeout 重试、绕过 provider quarantine、删除下一
  request boundary 的 cancellation guard。

逐项命令和原始失败输出在 ignored
`_collab/033/removal_validation/failure_handling.txt` 与 `failure_replay.txt`；原恢复态 43/43
输出在 `final_green.txt`，加入真实阻塞后定向套件 45/45；阻塞红灯与恢复输出在
`blocking_timeout_isolation.txt`。

## 已知边界

- daemon worker 能让调用者按 deadline 返回，但 Python 不能安全杀死已经进入的任意同步
  GET。CNINFO 会捕获旧 run context、在旧 worker 存活时隔离 provider，并在下一 request
  boundary 协作取消；HTTPX 自身的 30s transport timeout 仍是实际资源回收边界。任意不
  配合 cancellation scope 的第三方同步 operation，其内部副作用仍无法由通用 executor 强杀。
- circuit breaker 当前按 Engine run context 隔离，不跨进程共享，不能代表供应商全局健康。
- 同时注入“CNINFO 失败 + web 挂起”的组合只由已有 total-retrieval chaos 覆盖，没有真实
  provider 故障演练；最小后续修复是录制一个经授权的真实 provider outage run。
