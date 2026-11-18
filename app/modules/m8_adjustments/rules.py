import hashlib
from decimal import Decimal
from app.values import number, money
from app.reasons import reject, sources
from app.errors import DomainError
from app.modules.m2_billitems.rules import ITEMS
from app.modules.m3_changes.rules import CHANGES

APPROVED_STATUS={"已批准","批准","approved","生效","effective"}
WITHDRAWN_STATUS={"已撤回","撤回","withdrawn","void","作废"}
NOT_EFFECTIVE_STATUS={"未生效","pending_effect","not_effective"}
UNAPPROVED_STATUS={"未批准","待审批","草稿","draft","已驳回","rejected","未通过","pending"}
DEFAULT_SETTLEMENT_PERIOD="2026-11"
DEFAULT_BASES=[
    {"basis_id":"PA-2026-11-C1","change_id":"C1","item":"001","original_price":"100.00","new_price":"120.00","retroactive_from":"2026-03","retroactive_to":"2026-11","status":"已批准","approved":True,"effective_period":"2026-11","note":"合同调价C1批准，追溯至2026-03已签工程量"},
    {"basis_id":"PA-2026-12-DRAFT","change_id":"C1","item":"001","original_price":"100.00","new_price":"130.00","retroactive_from":"2026-04","retroactive_to":"2026-11","status":"待审批","approved":False,"effective_period":"2026-11","note":"审批未完成"},
    {"basis_id":"PA-2026-WD","change_id":"C1","item":"001","original_price":"100.00","new_price":"110.00","retroactive_from":"2026-06","retroactive_to":"2026-11","status":"已撤回","approved":True,"effective_period":"2026-11","note":"已撤回的依据"},
    {"basis_id":"PA-2026-11-C1-RESUBMIT","change_id":"C1","item":"001","original_price":"100.00","new_price":"120.00","retroactive_from":"2026-03","retroactive_to":"2026-11","status":"已批准","approved":True,"effective_period":"2026-11","note":"与PA-2026-11-C1为同一依据的重复提交"},
    {"basis_id":"PA-2026-12-PENDING","change_id":"C1","item":"001","original_price":"100.00","new_price":"115.00","retroactive_from":"2026-05","retroactive_to":"2026-11","status":"已批准","approved":True,"effective_period":"2026-12","note":"生效期未到"},
]

def _period(value):
    if not isinstance(value,str) or len(value)!=7 or value[4]!="-": return False
    try:
        year,month=value.split("-"); return int(year)>=1900 and 1<=int(month)<=12
    except (TypeError,ValueError): return False

def _identity(basis):
    basis_id=basis.get("basis_id") or basis.get("adjustment_id") or basis.get("id")
    if basis_id is not None: return str(basis_id)
    return "AUTO-"+_fingerprint(basis)[:10]

def _price(value):
    try: return money(number(value))
    except DomainError: return str(value if value is not None else "").strip()

def _fingerprint(basis):
    item=ITEMS.get(str(basis.get("item","")),str(basis.get("item","")))
    parts=[item,str(basis.get("change_id","")),_price(basis.get("original_price")),_price(basis.get("new_price")),str(basis.get("retroactive_from","")),str(basis.get("retroactive_to",""))]
    return "|".join(parts)

def _settlement_key(fingerprint,claim_id,item,period):
    return hashlib.sha256(f"{fingerprint}|{claim_id}|{item}|{period}".encode()).hexdigest()[:24]

def _basis_reject(basis, code, detail):
    return reject({**basis,"basis_id":_identity(basis),"basis_fingerprint":_fingerprint(basis)},code,detail)

def _validate(basis, versions, settlement_period):
    """返回 (归一化依据, 拒绝原因或None, 明细)。依据无效时不参与计价。"""
    if not isinstance(basis,dict):
        return None,"BAD_ADJUSTMENT","依据需要对象"
    basis_id=_identity(basis)
    status=str(basis.get("status","已批准")).strip()
    change_id=basis.get("change_id")
    item=basis.get("item")
    if change_id:
        rule=versions.get(change_id)
        if not rule: return None,"UNKNOWN_REFERENCE",f"变更{change_id}不存在"
        if not rule.get("approved"): return None,"UNAPPROVED_CHANGE",f"变更{change_id}尚未批准"
    if not item: return None,"BAD_ADJUSTMENT","缺少清单项"
    if not _period(basis.get("retroactive_from")) or not _period(basis.get("retroactive_to")):
        return None,"BAD_ADJUSTMENT","追溯区间需要YYYY-MM"
    if basis["retroactive_from"]>=basis["retroactive_to"]:
        return None,"BAD_ADJUSTMENT","追溯起始周期必须早于结束周期"
    try:
        old_price=number(basis.get("original_price"));new_price=number(basis.get("new_price"))
        if old_price<0 or new_price<0: return None,"BAD_ADJUSTMENT","单价不能为负"
    except DomainError as error:
        return None,"BAD_ADJUSTMENT",error.message
    if basis.get("withdrawn") is True or status in WITHDRAWN_STATUS:
        return None,"ADJUSTMENT_WITHDRAWN",f"依据{basis_id}已撤回"
    effective_period=basis.get("effective_period") or basis.get("approved_period")
    if status in NOT_EFFECTIVE_STATUS or (effective_period and effective_period>settlement_period):
        return None,"ADJUSTMENT_NOT_EFFECTIVE",f"依据{basis_id}自{effective_period or '未定'}生效，本期{settlement_period}不可用"
    approved=basis.get("approved")
    if approved is None: approved=status in APPROVED_STATUS
    if not approved or status in UNAPPROVED_STATUS:
        return None,"UNAPPROVED_ADJUSTMENT",f"依据{basis_id}审批未通过"
    normalized={"basis_id":basis_id,"basis_fingerprint":_fingerprint(basis),"change_id":change_id,"item":ITEMS.get(str(item),str(item)),"original_price":money(old_price),"new_price":money(new_price),"delta_unit_price":money(new_price-old_price),"retroactive_from":basis["retroactive_from"],"retroactive_to":basis["retroactive_to"],"effective_period":effective_period or settlement_period,"status":status,"note":basis.get("note","")}
    return normalized,None,None

def _covers(basis,row,settlement_period):
    item=basis["item"]
    if item not in {"*","all","全部"} and row.get("item")!=item: return False
    period=row.get("period","")
    if period>=settlement_period: return False
    return basis["retroactive_from"]<=period<basis["retroactive_to"]

def _ladder_ok(earlier,later):
    """同一清单的两个调价依据只有在价格首尾相接时才视为连续调价，否则是重复或冲突授权。"""
    same_item=earlier["item"]==later["item"] or "*" in {earlier["item"],later["item"]}
    overlaps=earlier["retroactive_from"]<later["retroactive_to"] and later["retroactive_from"]<earlier["retroactive_to"]
    return not (same_item and overlaps) or number(earlier["new_price"])==number(later["original_price"])

def evaluate(rows,context):
    context=context or {};parameters=context.get("parameters",{}) or {}
    settlement_period=str(parameters.get("settlement_period",DEFAULT_SETTLEMENT_PERIOD))
    if not _period(settlement_period): raise DomainError("BAD_PERIOD","结算期需要YYYY-MM")
    versions=parameters.get("changes",CHANGES)
    bases=parameters.get("price_adjustments")
    if bases is None: bases=DEFAULT_BASES
    if not isinstance(bases,list): raise DomainError("BAD_ADJUSTMENTS","price_adjustments需要列表")
    accepted=[];quarantine=[];seen_ids=set();seen_fingerprints=set();decisions=[]
    for index,raw_basis in enumerate(bases,1):
        if not isinstance(raw_basis,dict):
            row=reject({"_line":index,"basis_id":f"ROW-{index}"},"BAD_ADJUSTMENT","依据需要对象")
            quarantine.append(row);decisions.append({"basis_id":row["basis_id"],"decision":"排除","reason":row["reason"],"detail":row["detail"]});continue
        fingerprint=_fingerprint(raw_basis);identity=_identity(raw_basis)
        if identity in seen_ids:
            row=_basis_reject(raw_basis,"DUPLICATE_ADJUSTMENT",f"依据{identity}重复提交，保留首次提交")
            quarantine.append(row);decisions.append({"basis_id":identity,"decision":"排除","reason":row["reason"],"detail":row["detail"]});continue
        seen_ids.add(identity)
        normalized,reason,detail=_validate(raw_basis,versions,settlement_period)
        if reason:
            row=_basis_reject(raw_basis,reason,detail);quarantine.append(row)
            decisions.append({"basis_id":identity,"decision":"排除","reason":reason,"detail":detail});continue
        if fingerprint in seen_fingerprints:
            row=_basis_reject(raw_basis,"DUPLICATE_ADJUSTMENT",f"依据{identity}与在先依据实质相同，保留首次提交")
            quarantine.append(row);decisions.append({"basis_id":identity,"decision":"排除","reason":row["reason"],"detail":row["detail"]});continue
        conflict=next((prior for prior in accepted if not _ladder_ok(prior,normalized)),None)
        if conflict:
            row=_basis_reject(raw_basis,"ADJUSTMENT_CONFLICT",f"依据{identity}与{conflict['basis_id']}价格区间重叠且单价不衔接")
            quarantine.append(row);decisions.append({"basis_id":identity,"decision":"排除","reason":row["reason"],"detail":row["detail"]});continue
        seen_fingerprints.add(fingerprint)
        accepted.append(normalized)
    output=[];basis_stats={basis["basis_id"]:{"rows":0,"qty":Decimal(0),"amount":Decimal(0)} for basis in accepted};basis_order=[basis["basis_id"] for basis in accepted]
    for row in sorted(rows,key=lambda item:(item.get("period",""),item.get("claim_id",""))):
        candidates=[basis for basis in accepted if _covers(basis,row,settlement_period)]
        if not candidates: continue
        basis=max(candidates,key=lambda candidate:candidate["retroactive_from"])
        quantity=number(row.get("increment_qty","0"))
        signed_price=number(row["unit_price"]) if row.get("unit_price") not in (None,"") else number(basis["original_price"])
        amount=number(money(quantity*(number(basis["new_price"])-signed_price)))
        direction="应补" if amount>0 else ("应扣" if amount<0 else "无调整")
        output.append({"_line":row.get("_line"),"_sources":sources(row),"claim_id":row.get("claim_id"),"item":row.get("item"),"period":row.get("period"),
            "signed_qty":str(quantity),"unit_price":money(signed_price),"new_unit_price":basis["new_price"],"delta_unit_price":money(number(basis["new_price"])-signed_price),
            "adjustment_amount":money(amount),"direction":direction,"basis_id":basis["basis_id"],"change_id":basis["change_id"],"basis_fingerprint":basis["basis_fingerprint"],
            "basis_note":basis.get("note",""),"settlement_period":settlement_period,"original_price":basis["original_price"],
            "settlement_key":_settlement_key(basis["basis_fingerprint"],row.get("claim_id"),row.get("item"),row.get("period")) if amount!=0 else None,
            "status":"可结算" if amount!=0 else "无调整"})
        stats=basis_stats[basis["basis_id"]];stats["rows"]+=1;stats["qty"]+=quantity;stats["amount"]+=amount
    basis_summaries=[]
    for basis in accepted:
        stats=basis_stats[basis["basis_id"]]
        if not stats["rows"]:
            quarantine.append(_basis_reject(basis,"ADJUSTMENT_NO_AFFECTED_QTY",f"依据{basis['basis_id']}在追溯区间内没有已签工程量"))
            decisions.append({"basis_id":basis["basis_id"],"decision":"排除","reason":"ADJUSTMENT_NO_AFFECTED_QTY","detail":"追溯区间内没有已签工程量"})
            continue
        basis_summaries.append({"basis_id":basis["basis_id"],"decision":"采信","change_id":basis["change_id"],"item":basis["item"],"original_price":basis["original_price"],"new_price":basis["new_price"],"retroactive_from":basis["retroactive_from"],"retroactive_to":basis["retroactive_to"],"affected_rows":stats["rows"],"affected_qty":str(stats["qty"]),"net_adjustment":money(stats["amount"])})
        decisions.append({"basis_id":basis["basis_id"],"decision":"采信","reason":"","detail":f"追溯{basis['retroactive_from']}至{basis['retroactive_to']}，影响{stats['rows']}条已签工程量"})
    basis_summaries.sort(key=lambda item:basis_order.index(item["basis_id"]))
    supplement=sum((number(row["adjustment_amount"]) for row in output if number(row["adjustment_amount"])>0),Decimal(0))
    deduction=sum((-number(row["adjustment_amount"]) for row in output if number(row["adjustment_amount"])<0),Decimal(0))
    net=sum((number(row["adjustment_amount"]) for row in output),Decimal(0))
    affected_qty=sum((number(row["signed_qty"]) for row in output),Decimal(0))
    valuation=context.get("valuation") or {}
    signed_net=number(valuation.get("metrics",{}).get("expected_total","0"))
    metrics={"settlement_period":settlement_period,"basis_submitted":len(bases),"basis_accepted":len(basis_summaries),
        "basis_quarantined":len(quarantine),"duplicate_basis":sum(1 for q in quarantine if q.get("reason")=="DUPLICATE_ADJUSTMENT"),
        "withdrawn_basis":sum(1 for q in quarantine if q.get("reason")=="ADJUSTMENT_WITHDRAWN"),
        "unapproved_basis":sum(1 for q in quarantine if q.get("reason") in {"UNAPPROVED_ADJUSTMENT","UNAPPROVED_CHANGE"}),
        "ineffective_basis":sum(1 for q in quarantine if q.get("reason")=="ADJUSTMENT_NOT_EFFECTIVE"),
        "conflicting_basis":sum(1 for q in quarantine if q.get("reason")=="ADJUSTMENT_CONFLICT"),
        "excluded_reasons":sorted({q.get("reason") for q in quarantine}),
        "affected_rows":len(output),"affected_qty":str(affected_qty),"supplement_total":money(supplement),"deduction_total":money(deduction),
        "net_adjustment":money(net),"signed_net_total":money(signed_net),"adjusted_net_total":money(signed_net+net),
        "pending_rows":len(output),"pending_adjustment":money(net),"settled_rows":0,"settled_total":"0.00",
        "signed_rows":0,"signed_adjustment":"0.00","signable":bool(basis_summaries) and net!=0}
    statement=f"本期{settlement_period}价格调整：采信{len(basis_summaries)}项依据（{'、'.join(item['basis_id'] for item in basis_summaries) or '无'}），影响{len(output)}条已签工程量共{str(affected_qty)}；应补{money(supplement)}元，应扣{money(deduction)}元，净调整{money(net)}元。价差单独计价，不改变前期已签工程量与原单价，也不并入累计链。"
    if quarantine:
        counts={}
        for item in quarantine: counts[item.get("reason","")]=counts.get(item.get("reason",""),0)+1
        statement+=f"另有{len(quarantine)}项依据未采信（{'、'.join(f'{code}×{n}' for code,n in sorted(counts.items()) if code)}），已单独列出，未参与计价。"
    return {"rows":output,"quarantine":quarantine,"metrics":metrics,"basis_decisions":decisions,"basis_summaries":basis_summaries,"statement":statement}

def apply_settlements(result, settled_elsewhere=None, settled_here=None):
    """标注结清状态。本批已签认的明细保留金额并显示"已签认"；被其他批次结清的明细从本期可入账金额中剔除，
    保证同一依据重跑不重复计价。"""
    others=set(settled_elsewhere or []);here=set(settled_here or [])
    rows=[];pending=[];settled_rows=[];signed_rows=[]
    for row in result.get("rows",[]):
        key=row.get("settlement_key")
        if key and key in others:
            marked={**row,"status":"已结清","settled_by":"其他批次","settled":True}
            settled_rows.append(marked);rows.append(marked);continue
        if key and key in here:
            marked={**row,"status":"已签认","settled_by":"本批次","settled":True}
            signed_rows.append(marked);rows.append(marked);continue
        rows.append(row)
        if row.get("status")=="可结算": pending.append(row)
    batch_rows=pending+signed_rows
    supplement=sum((number(row["adjustment_amount"]) for row in batch_rows if number(row["adjustment_amount"])>0),Decimal(0))
    deduction=sum((-number(row["adjustment_amount"]) for row in batch_rows if number(row["adjustment_amount"])<0),Decimal(0))
    net=sum((number(row["adjustment_amount"]) for row in batch_rows),Decimal(0))
    pending_net=sum((number(row["adjustment_amount"]) for row in pending),Decimal(0))
    settled_total=sum((number(row["adjustment_amount"]) for row in settled_rows),Decimal(0))
    signed_total=sum((number(row["adjustment_amount"]) for row in signed_rows),Decimal(0))
    signed_net=number(result.get("metrics",{}).get("signed_net_total","0"))
    metrics={**result.get("metrics",{}),"supplement_total":money(supplement),"deduction_total":money(deduction),
        "net_adjustment":money(net),"pending_rows":len(pending),"pending_adjustment":money(pending_net),
        "settled_rows":len(settled_rows),"settled_total":money(settled_total),
        "signed_rows":len(signed_rows),"signed_adjustment":money(signed_total),
        "adjusted_net_total":money(signed_net+net),"signable":bool(pending) and number(result.get("metrics",{}).get("basis_accepted","0"))>0}
    period=metrics.get("settlement_period","")
    parts=[f"本期{period}价格调整：采信{metrics.get('basis_accepted',0)}项依据，影响{metrics.get('affected_rows',0)}条已签工程量共{metrics.get('affected_qty','0')}；应补{money(supplement)}元，应扣{money(deduction)}元，净调整{money(net)}元。"]
    if settled_rows: parts.append(f"另有{len(settled_rows)}条{money(settled_total)}元已由在先批次结清，同一依据不再重复计价，未计入本批。")
    if signed_rows: parts.append(f"本批已签认{len(signed_rows)}条{money(signed_total)}元。")
    if pending: parts.append(f"待签认{len(pending)}条{money(pending_net)}元。")
    parts.append("价差单独计价，不改变前期已签工程量与原单价，也不并入累计链。")
    return {**result,"rows":rows,"metrics":metrics,"statement":"".join(parts)}
