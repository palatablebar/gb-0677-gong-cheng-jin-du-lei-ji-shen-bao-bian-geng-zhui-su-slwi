REASONS={"BAD_COLUMNS":"列数不匹配","EMPTY_VALUE":"必填值为空","INVALID_NUMBER":"数字格式错误","INVALID_TIME":"时间缺少偏移或格式错误","DUPLICATE_CONFLICT":"同键取值冲突","UNKNOWN_REFERENCE":"引用不存在","STALE_VERSION":"版本已更新","EMPTY_FILE":"文件为空","HEADER_ONLY":"仅有表头","BLANK_ONLY":"全部为空行","UNAPPROVED_CHANGE":"变更未批准","ADJUSTMENT_WITHDRAWN":"调价依据已撤回","UNAPPROVED_ADJUSTMENT":"调价依据未批准","ADJUSTMENT_NOT_EFFECTIVE":"调价依据未生效","DUPLICATE_ADJUSTMENT":"调价依据重复提交","ADJUSTMENT_CONFLICT":"调价依据互相冲突","ADJUSTMENT_NO_AFFECTED_QTY":"追溯区间内无已签工程量","BAD_ADJUSTMENT":"调价依据字段无效","BAD_PERIOD":"结算期格式错误"}
def reject(row, code, detail):
    return {**row,"reason":code,"detail":detail}
def sources(row):
    return row.get("_sources", [row.get("_line",0)])
