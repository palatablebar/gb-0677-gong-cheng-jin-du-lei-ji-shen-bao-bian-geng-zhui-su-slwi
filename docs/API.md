# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV。

`/api/adjustments` 返回价格调整阶段：rows为逐条受影响已签工程量与调整金额，basis_decisions为每个依据的采信/排除裁决，basis_summaries为采信依据汇总，statement为可直接签认的说明文字。`GET /api/adjustments/settlements` 返回已签认结清明细。签认仍走 `/api/runs/<id>/review`；版本不符返回409且不登记结清。
