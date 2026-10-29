"""平台层：数据源配置、任务调度、执行与结果落盘。

分层边界：Loader（取数与拆序列）→ Preprocessor（清洗）→ Detector（打分）→ Evaluation/Alert。
第一版全部在进程内完成，接口边界保留，后续可把 Loader/Preprocessor 拆成独立服务。
"""
