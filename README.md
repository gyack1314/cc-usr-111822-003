# 机器人装机与售后

项目按来源版本保存业务资料（设备、工单、配置），并按设备实际投用、停用、
维修停机与配置有效期形成暴露区间，输出可比的批次故障风险：首次失效与
返修分开计数，故障率带泊松精确置信区间；备件需求由未结工单（即时）加
故障率外推（预计）组成。服务中心补录维修单或撤销误报后，可复核任一决策
时点：受影响批次、备件需求变化、当时可用的证据（含内容摘要）以及决策后
才到达的资料。暴露不足观察期的设备只贡献真实暴露，不计入零故障样本。

资料模型（data/example.json 的 documents）：

- device：cohort / model / installed_on；停用用新 revision 登记 retired_on、active=false
- config：device / firmware / drive / effective_from（/ effective_to），配置有效期
- ticket：device / fault / part / occurred_on / returned_on / state（open、closed、retracted 为撤销的误报）

运行与检查：

    python -m unittest discover -s tests -v
    python -m compileall -q robot_service tests
    python -m robot_service.cli data/example.json
    python -m robot_service.cli data/example.json --decision-at 2026-09-10T00:00:00+08:00
