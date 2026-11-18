from decimal import Decimal
import pytest
from app.modules.m8_adjustments.rules import evaluate,apply_settlements,DEFAULT_BASES
from app.errors import DomainError

def rows():
    return [
        {"_line":5,"_sources":[5],"claim_id":"00003","item":"001","period":"2026-03","increment_qty":"25","unit_price":"100.00"},
        {"_line":7,"_sources":[7],"claim_id":"00005","item":"001","period":"2026-05","increment_qty":"25","unit_price":"100.00"},
        {"_line":11,"_sources":[11],"claim_id":"00009","item":"001","period":"2026-09","increment_qty":"25","unit_price":"100.00"},
        {"_line":13,"_sources":[13],"claim_id":"00011","item":"001","period":"2026-11","increment_qty":"25","unit_price":"120.00"},
        {"_line":6,"_sources":[6],"claim_id":"00004","item":"002","period":"2026-04","increment_qty":"25","unit_price":"100.00"},
    ]

def basis(**overrides):
    base={"basis_id":"PA-1","change_id":"C1","item":"001","original_price":"100.00","new_price":"120.00","retroactive_from":"2026-03","retroactive_to":"2026-11","status":"已批准","approved":True,"effective_period":"2026-11"}
    base.update(overrides);return base

def test_retroactive_adjustment_uses_signed_qty_only():
    r=evaluate(rows(),{"parameters":{"price_adjustments":[basis()]}})
    assert r["metrics"]["affected_rows"]==3
    assert r["metrics"]["affected_qty"]=="75"
    assert r["metrics"]["supplement_total"]=="1500.00"
    assert r["metrics"]["net_adjustment"]=="1500.00"
    assert all(row["adjustment_amount"]=="500.00" for row in r["rows"])

def test_cumulative_chain_is_not_touched():
    source=rows();before=[dict(row) for row in source]
    evaluate(source,{"parameters":{"price_adjustments":[basis()]}})
    assert source==before

def test_period_range_is_half_open():
    r=evaluate(rows(),{"parameters":{"price_adjustments":[basis(retroactive_to="2026-05")]}})
    assert [row["period"] for row in r["rows"]]==["2026-03"]

def test_withdrawn_basis_excluded():
    r=evaluate(rows(),{"parameters":{"price_adjustments":[basis(status="已撤回")]}})
    assert r["rows"]==[] and r["quarantine"][0]["reason"]=="ADJUSTMENT_WITHDRAWN"
    assert r["metrics"]["net_adjustment"]=="0.00"

def test_unapproved_basis_excluded():
    r=evaluate(rows(),{"parameters":{"price_adjustments":[basis(status="待审批",approved=False)]}})
    assert r["rows"]==[] and r["quarantine"][0]["reason"]=="UNAPPROVED_ADJUSTMENT"

def test_not_effective_basis_excluded():
    r=evaluate(rows(),{"parameters":{"price_adjustments":[basis(effective_period="2026-12")]}})
    assert r["quarantine"][0]["reason"]=="ADJUSTMENT_NOT_EFFECTIVE"
    r=evaluate(rows(),{"parameters":{"price_adjustments":[basis(status="未生效")]}})
    assert r["quarantine"][0]["reason"]=="ADJUSTMENT_NOT_EFFECTIVE"

def test_duplicate_basis_by_id_and_by_content():
    r=evaluate(rows(),{"parameters":{"price_adjustments":[basis(),basis(status="已批准")]}})
    assert r["metrics"]["basis_accepted"]==1 and r["metrics"]["duplicate_basis"]==1
    assert len(r["rows"])==3
    r=evaluate(rows(),{"parameters":{"price_adjustments":[basis(),basis(basis_id="PA-2")]}})
    assert r["metrics"]["duplicate_basis"]==1 and r["metrics"]["basis_accepted"]==1

def test_draft_change_reference_rejected():
    r=evaluate(rows(),{"parameters":{"price_adjustments":[basis(change_id="DRAFT")]}})
    assert r["quarantine"][0]["reason"]=="UNAPPROVED_CHANGE"

def test_basis_without_affected_qty_quarantined():
    r=evaluate(rows(),{"parameters":{"price_adjustments":[basis(retroactive_from="2027-01",retroactive_to="2027-06")]}})
    assert r["quarantine"][0]["reason"]=="ADJUSTMENT_NO_AFFECTED_QTY"
    assert r["metrics"]["basis_accepted"]==0 and r["metrics"]["signable"] is False

def test_deduction_when_price_drops():
    r=evaluate(rows(),{"parameters":{"price_adjustments":[basis(new_price="90.00")]}})
    assert r["metrics"]["deduction_total"]=="750.00" and r["metrics"]["supplement_total"]=="0.00"
    assert r["metrics"]["net_adjustment"]=="-750.00"
    assert all(row["direction"]=="应扣" for row in r["rows"])

def test_current_settlement_period_is_not_retroactively_recalculated():
    r=evaluate(rows(),{"parameters":{"price_adjustments":[basis(retroactive_to="2026-12",item="*")]}})
    assert all(row["period"]<"2026-11" for row in r["rows"])
    assert not any(row["period"]=="2026-11" for row in r["rows"])

def test_settlement_prevents_double_counting():
    base=evaluate(rows(),{"parameters":{"price_adjustments":[basis()]}})
    keys={row["settlement_key"] for row in base["rows"]}
    replayed=apply_settlements(base,keys,set())
    assert replayed["metrics"]["net_adjustment"]=="0.00"
    assert replayed["metrics"]["settled_rows"]==3
    assert all(row["status"]=="已结清" for row in replayed["rows"])
    assert "不再重复计价" in replayed["statement"]

def test_same_batch_signed_still_reports_amount():
    base=evaluate(rows(),{"parameters":{"price_adjustments":[basis()]}})
    keys={row["settlement_key"] for row in base["rows"]}
    signed=apply_settlements(base,set(),keys)
    assert signed["metrics"]["net_adjustment"]=="1500.00"
    assert all(row["status"]=="已签认" for row in signed["rows"])

def test_settlement_key_stable_across_batches():
    first=evaluate(rows(),{"parameters":{"price_adjustments":[basis()]}})
    second=evaluate(rows(),{"parameters":{"price_adjustments":[basis(note="重新提交同依据")]}})
    assert [r["settlement_key"] for r in first["rows"]]==[r["settlement_key"] for r in second["rows"]]

def test_bad_settlement_period_rejected():
    with pytest.raises(DomainError):evaluate(rows(),{"parameters":{"settlement_period":"2026/11"}})

def test_default_basis_set_mixes_invalid_sources(result):
    stage=result["stages"][7];reasons={q["reason"] for q in stage["quarantine"]}
    assert {"UNAPPROVED_ADJUSTMENT","ADJUSTMENT_WITHDRAWN","DUPLICATE_ADJUSTMENT","ADJUSTMENT_NOT_EFFECTIVE"}<=reasons
    assert stage["metrics"]["basis_accepted"]==1 and stage["metrics"]["net_adjustment"]=="2000.00"

def test_real_sample_adjustment_totals(result):
    stage=result["stages"][7]
    assert stage["metrics"]["supplement_total"]=="2000.00" and stage["metrics"]["deduction_total"]=="0.00"
    assert Decimal(stage["metrics"]["adjusted_net_total"])==Decimal(stage["metrics"]["signed_net_total"])+Decimal(stage["metrics"]["net_adjustment"])

def test_real_sample_statement_covers_evidence(result):
    stage=result["stages"][7]
    for token in ("应补","应扣","已签工程量"):
        assert token in stage["statement"]
    assert all(row["basis_id"] and row["period"] and row["signed_qty"] for row in stage["rows"])

def test_overlapping_conflicting_basis_rejected():
    second=basis(basis_id="PA-2",new_price="130.00",original_price="110.00")
    r=evaluate(rows(),{"parameters":{"price_adjustments":[basis(),second]}})
    assert any(q["reason"]=="ADJUSTMENT_CONFLICT" for q in r["quarantine"])
    assert r["metrics"]["basis_accepted"]==1 and r["metrics"]["net_adjustment"]=="1500.00"

def test_ladder_basis_applies_latest_price():
    first=basis(basis_id="PA-1",retroactive_to="2026-06")
    second=basis(basis_id="PA-2",original_price="120.00",new_price="130.00",retroactive_from="2026-06",retroactive_to="2026-11")
    r=evaluate(rows(),{"parameters":{"price_adjustments":[first,second]}})
    assert r["metrics"]["basis_accepted"]==2
    assert {row["basis_id"] for row in r["rows"]}=={"PA-1","PA-2"}
    # 2026-03/05 按 100→120，2026-09 按 100→130
    by_period={row["period"]:row["adjustment_amount"] for row in r["rows"]}
    assert by_period=={"2026-03":"500.00","2026-05":"500.00","2026-09":"750.00"}

def test_signed_price_already_at_new_price_has_no_adjustment():
    data=[{"claim_id":"A","item":"001","period":"2026-05","increment_qty":"25","unit_price":"120.00"}]
    r=evaluate(data,{"parameters":{"price_adjustments":[basis()]}})
    assert r["metrics"]["net_adjustment"]=="0.00" and r["rows"][0]["status"]=="无调整"
