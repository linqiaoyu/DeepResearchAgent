# 033 运行清单：真实与 mixed-provider

时间均为 2026-07-26 UTC。除 Reflector arm 与 memory probe 外，完成的护栏 case 使用全真实
provider：DeepSeek/Qwen、Tavily、AKShare、CNINFO；authority-first 命中时 Tavily 实际请求数
可以为零，但 provider 仍为 live 配置。Reflector 实装返回 `synthetic_fixture /
recorded_placeholder`，因此涉及它的四条完成 run 明确标为 mixed-provider，不称真实模式。
每个 research run 的熔断是 CNY 2.00。

配置缩写：`B`=Flash planner/extractor/reporter、Dynamic on、旧语义评价未接通；`C`=`B`+
显式 Critic/Extractor/Procedural on，Reflector/working/prior/loop off；`S`=Flash + Qwen semantic
judge，Critic/Extractor on，Procedural/Reflector/working/prior/loop off，Dynamic on；`P`=Pro +
同一 Qwen judge。后缀只写相对该配置的 delta。

| arm / commit | config | 茅台或第一次 | 恒瑞或第二次 |
|---|---|---|---|
| baseline / `88c6f3e` | B | 20:42:17 `d6f4f582-c9b9-4b20-a3ea-7e0fcdb23a2d`，1/3 H0 fail，¥0.03324364，117.437s | 20:44:15 `e76c7a6e-09fe-4ba4-8613-fe424ea4c043`，3/3 H0 pass，¥0.03090808，95.668s |
| instrumented_control / `4c300ed` | C | 20:52:13 `1009f223-6700-403f-a49b-b68f9cae1215`，3/3 H1 fail，¥0.03543564，132.730s | 20:54:26 `6909aac2-c1e2-48fd-b26c-c0f92d144f36`，3/3 H0 pass，¥0.03144464，97.149s |
| critic_off / `4c300ed` | C−Critic | 20:56:19 `2663dd2c-db76-461c-ab62-05f7f76590bf`，3/3 H0 pass，¥0.03706864，124.427s | 20:58:23 `f1278ccb-1558-4b6d-93ea-634ad6ca04f3`，3/3 H1 fail，¥0.03399364，89.747s |
| extractor_off / `4c300ed` | C−Extractor | 21:03:15 `034c22e1-c096-4eb9-8064-3d50243e2bc7`，1/3 H1 fail，¥0.01098284，74.867s | 21:04:30 `1f2d1c3e-698e-4f63-9821-b17ab6e3efea`，0/3 H1 fail，¥0.00524784，29.859s |
| reflector_on / `4c300ed` | C+Reflector；**mixed-provider** | 21:05:15 `ecbae9ee-5464-4ff0-bdb5-83f86e7ef7e9`，1/3 H0 fail，¥0.03301164，107.384s | 21:07:02 `769f69bc-dd3d-49fd-99a3-7d9b8295bdd3`，1/3 H1 fail，¥0.04196500，137.518s |
| working_memory_on（旧）/ `4c300ed` | C+working（改 canonical） | 21:09:46 `4975fb59-aa62-4df9-a862-9bb7c3ccdf7b`，3/3 H0 pass，¥0.04103856，139.712s | 21:12:06 `ab7339a3-da76-4aea-b66e-c12b6631c5d8`，2/3 H1 fail，¥0.03493664，118.598s |
| procedural_memory_off / `4c300ed` | C−Procedural | 21:14:20 `29d3bcfd-5de3-4aa6-8ee5-e0e4a9c3fbd0`，1/3 H0 fail，¥0.04285956，132.585s | 21:16:33 `e787f402-de34-436c-90a0-0dc347ed62ca`，3/3 H0 pass，¥0.03330264，71.715s |
| research_loop_on / `4c300ed` | C+Loop(max=2) | 21:18:00 `ca3faf1e-e1e5-4381-b41a-fa50f0579df6`，1/3 H0 fail，¥0.03850264，138.834s | 21:20:19 `b2c67498-57ea-4fff-9fdb-25711a57b42a`，3/3 H1 fail，¥0.03605356，104.005s |
| dynamic_off（旧）/ `4c300ed` | C−Dynamic（失真 fixed set） | 21:22:15 `a389680c-38c5-4626-afc8-51760efafb60`，1/3 H0 fail，¥0.02861564，131.907s | 21:24:27 `42f6540a-a55b-4d68-8c45-b8fd9ea16222`，2/3 H0 fail，¥0.02636400，89.809s |
| all_memories_same_engine / `c724454` | working+episodic+procedural+reflector；**mixed-provider** | 21:27:34 `72fe9b46-e012-4be0-824b-64ca9c53282d`，3/3 H1 fail，¥0.04334112，145.191s | 21:30:00 `47e7d4e4-d995-4225-bd4d-e85c12e9eded`，3/3 H0 pass，¥0.03822412，101.384s |
| post_fidelity_flash / `6f1edeb` | B+机械保真 | 21:47:29 `7a723837-b6ed-4721-b8c4-db0132826326`，3/3 H0 pass，¥0.03413764，99.954s | 21:49:09 `d86a777d-0c3d-41b7-baf1-448ebe3d434e`，3/3 H0 pass，¥0.04247748，124.184s |
| final_dynamic_off_flash / `18411e3` | S−Dynamic（coverage 仍有缺陷） | 22:42:22 `83e72110-1489-40ba-a867-cdea43bc9185`，3/3 H0 pass，¥0.05741364，145.599s | 22:44:48 `7149a1ca-5395-46e4-a86c-2a98206ddd62`，冻结 scorer pass、机械 evaluator fail，¥0.05182164，113.111s |
| final2 误配 / `606683d` | 实际 Dynamic on / judge off | 22:59:56 `2652a5a3-b0f5-42f3-a5b7-a08d81c9bbe2`，3/3 H0 pass，¥0.03379120，122.570s | 约 23:02 `d633517e-bda0-4d0f-804d-25b80f5f5687`，planner 后中断，¥0.00442492；planner latency 19.090s，完整 wall/score 无；commit 由同一命令上下文推定，run 自身未持久化 manifest |
| final3_dynamic_off_flash / `606683d` | S−Dynamic | 23:03:27 `47f64d76-4060-4b52-8a89-c1fc04788be9`，3/3 H0 pass，¥0.06908056，138.411s | 23:05:46 `3ce0381f-39bf-4fcf-8886-c04ceaf8089d`，3/3 H0 pass，¥0.05865156，138.105s |
| final3_working_memory_on_flash / `606683d` | S+working prompt-only | 23:08:24 `c7e22f02-ed28-4360-aa9f-0323b6f2d98c`，3/3 H0 pass，¥0.06584156，144.527s | 23:10:48 `a3075d0e-11bd-4a70-a00d-2915318a7da7`，3/3 H0 pass，¥0.05423520，122.780s |
| final3_flash / `606683d` | S | 23:13:12 `104cdf5e-b04a-49f7-bd00-c85716d11488`，3/3 H0 pass，¥0.06204820，135.728s | 23:15:27 `bd035de2-ff13-408f-a65c-b0ea14f69f55`，3/3 H0 pass，¥0.06198556，145.141s |
| final3_pro / `606683d` | P | 23:18:05 `ee27cd9c-a97d-4852-9373-1d149cc89f86`，3/3 H0 pass，¥0.17303100，235.096s | 23:22:00 `ea9d285e-75c0-40e2-b72d-1051f6852065`，3/3 H0 pass，¥0.13006440，170.583s |

合计：31 个完成 guardrail case、2 个完成 memory probe、1 个中断 planner，共 34 条；其中
29 个完成 run 满足真实模式纯度，4 个完成 run 因 Reflector placeholder 为 mixed-provider，
另 1 个是真实配置下的非完整 run。可核实总成本 CNY 1.55554464。15 个完整双案例 aggregate
都使用同一个冻结 contract SHA，且 aggregate 与 case 求和一致。旧 arm 的语义指标没有接通，
不能补写语义分。Flash/Pro 是 live retrieval 端到端对照，不是冻结同一 Evidence 的纯模型实验。
