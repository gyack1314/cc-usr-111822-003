# 机器人装机与售后

项目按来源版本保存业务资料，已有 fleet、service、parts 环节。现有装机、工单和备件只看当前开单数，未按实际暴露时间与配置变化估计批次风险。

运行与检查：

    python -m unittest discover -s tests -v
    python -m compileall -q robot_service tests
    python -m robot_service.cli data/example.json
