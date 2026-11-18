from flask import render_template
from app.config import MODULES,TITLE,SHORT
from app.pipeline import execute,load_sample
from app import store
def register_pages(app):
    def page(index):
        run=store.latest() or execute(load_sample("dirty.csv"))
        stage=run["stages"][index]
        rows=stage["rows"]
        columns=[['claim_id', 'item', 'period', 'cumulative_qty', 'previous_qty', 'change_id', 'reported'], ['claim_id', 'item', 'unit', 'cumulative_qty', 'previous_qty'], ['claim_id', 'period', 'approved_change', 'unit_price'], ['claim_id', 'period', 'cumulative_qty', 'approved_previous', 'increment_qty', 'gross_amount'], ['claim_id', 'item', 'gross_amount', 'retention', 'advance_recovery', 'expected'], ['claim_id', 'item', 'expected', 'reported', 'difference', 'status'], ['claim_id', 'period', 'expected', 'status'], ['claim_id', 'item', 'period', 'signed_qty', 'unit_price', 'new_unit_price', 'delta_unit_price', 'adjustment_amount', 'direction', 'basis_id', 'status']][index]
        labels={'claim_id': '申报编号', 'item': '清单项', 'period': '申报周期', 'cumulative_qty': '本次累计量', 'previous_qty': '前审累计量', 'change_id': '变更单', 'reported': '申报净额', 'unit': '单位', 'approved_change': '已批变更', 'unit_price': '原单价 / 元', 'approved_previous': '修订前审量', 'increment_qty': '本期工程量', 'gross_amount': '本期总额', 'retention': '质保金', 'advance_recovery': '预付款扣回', 'expected': '实算净额', 'difference': '净额差异', 'status': '结论', 'gross_total': '本期总额合计', 'net_total': '实算净额合计', 'signed_qty': '已签工程量', 'new_unit_price': '调整单价 / 元', 'delta_unit_price': '单价差 / 元', 'adjustment_amount': '调整金额 / 元', 'direction': '补扣方向', 'basis_id': '调整依据', 'settlement_period': '结算期', 'basis_submitted': '提交依据', 'basis_accepted': '采信依据', 'basis_quarantined': '隔离依据', 'duplicate_basis': '重复依据', 'withdrawn_basis': '已撤回依据', 'unapproved_basis': '未批准依据', 'ineffective_basis': '未生效依据', 'affected_rows': '受影响已签量行', 'affected_qty': '受影响已签量', 'supplement_total': '应补合计', 'deduction_total': '应扣合计', 'net_adjustment': '净调整', 'signed_net_total': '原签认净额', 'adjusted_net_total': '调整后净额', 'settled_rows': '已结清行', 'settled_total': '已结清金额', 'signable': '可签认', 'conflicting_basis': '冲突依据', 'excluded_reasons': '排除原因', 'pending_rows': '待签认行', 'pending_adjustment': '待签认金额', 'signed_rows': '已签认行', 'signed_adjustment': '已签认金额', 'basis_note': '依据说明'}
        for key,label in {'accepted_inputs': '采纳来源行', 'quarantine_inputs': '隔离来源行', 'output_records': '结果记录', 'input': '输入行', 'excluded': '排除行', 'balanced': '行数平衡', 'expected_total': '预期合计', 'reported_total': '申报合计', 'differences': '差异项', 'blank': '空行', 'repeated_headers': '分段表头', 'encoding': '编码', 'duplicate': '重复行', 'quarantine': '隔离行', 'accepted': '采纳行', 'sha256': '校验摘要', 'ready': '可归档'}.items(): labels.setdefault(key,label)
        return render_template(f"m{index+1}.html",title=TITLE,short=SHORT,modules=MODULES,index=index,run=run,stage=stage,rows=rows,columns=columns[:12],history=store.history(),labels=labels)
    app.add_url_rule("/",view_func=lambda:page(4))
    for index,(slug,name) in enumerate(MODULES):
        app.add_url_rule("/"+slug,endpoint="page_"+slug,view_func=lambda index=index:page(index))
