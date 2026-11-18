import csv,io
from app.pipeline import execute,load_sample
from app.config import MODULES
from app import store
def test_full_sample_flow(client):
    r=client.post("/api/runs",json={"sample":"dirty.csv"});assert r.status_code==200
    p=r.get_json();assert len(p["stages"])==len(MODULES)
    assert p["stages"][5]["metrics"]["balanced"] is True
def test_idempotent_real_input(sample):
    a=execute(sample);b=execute(sample)
    assert a["run_id"]==b["run_id"] and len(store.history())==1
def test_stale_review_409(client):
    "TRAP-26 陈旧复核不得覆盖新版本"
    p=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json();u="/api/runs/"+p["run_id"]+"/review"
    assert client.post(u,json={"version":1,"decision":"已复核"}).status_code==200
    assert client.post(u,json={"version":1,"decision":"退回复核"}).status_code==409
def test_export_has_manifest_and_quarantine(client):
    p=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()
    r=client.get("/api/runs/"+p["run_id"]+"/archive")
    rows=list(csv.reader(io.StringIO(r.data.decode("utf-8-sig"))))
    assert rows[0][1]=="input_sha256" and any(x[3]=="quarantine" for x in rows[1:])
def test_failed_import_is_atomic(client):
    assert client.post("/api/runs",json={"csv":"bad"}).status_code==422
    assert store.history()==[]
def test_module_entrances(client):
    from app.config import MODULES
    for slug,name in MODULES:
        assert client.get("/api/"+slug).status_code==200
        assert client.get("/"+slug).status_code==200
def test_missing_run_404(client): assert client.get("/api/runs/missing").status_code==404

def test_signed_adjustment_is_settled_once(client):
    from decimal import Decimal
    p=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()
    assert p["stages"][7]["metrics"]["net_adjustment"]=="2000.00"
    assert client.post("/api/runs/"+p["run_id"]+"/review",json={"version":1,"decision":"已复核"}).status_code==200
    settled=client.get("/api/adjustments/settlements").get_json()["settlements"]
    assert len(settled)==4 and {x["amount"] for x in settled}=={"500.00"}
    again=client.get("/api/runs/"+p["run_id"]).get_json()["stages"][7]
    assert again["metrics"]["signed_rows"]==4 and again["metrics"]["pending_rows"]==0
    assert again["metrics"]["signed_adjustment"]=="2000.00"
    assert all(row["status"]=="已签认" for row in again["rows"])

def test_rerun_same_basis_not_double_counted(client):
    from decimal import Decimal
    first=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()
    client.post("/api/runs/"+first["run_id"]+"/review",json={"version":1,"decision":"已复核"})
    second=client.post("/api/runs",json={"sample":"dirty.csv","parameters":{"retention_rate":"0.05"}}).get_json()
    assert second["run_id"]!=first["run_id"]
    stage=second["stages"][7]
    assert stage["metrics"]["settled_rows"]==4
    assert stage["metrics"]["pending_rows"]==0 and stage["metrics"]["net_adjustment"]=="0.00"
    assert stage["metrics"]["signable"] is False
    assert Decimal(stage["metrics"]["adjusted_net_total"])==Decimal(stage["metrics"]["signed_net_total"])

def test_failed_review_keeps_old_version_and_no_settlement(client):
    p=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()
    url="/api/runs/"+p["run_id"]+"/review"
    assert client.post(url,json={"version":1,"decision":"已复核"}).status_code==200
    before=client.get("/api/runs/"+p["run_id"]).get_json()
    assert client.post(url,json={"version":1,"decision":"已复核"}).status_code==409
    after=client.get("/api/runs/"+p["run_id"]).get_json()
    assert after["version"]==before["version"] and after["decision"]=="已复核"
    assert len(client.get("/api/adjustments/settlements").get_json()["settlements"])==4

def test_archive_contains_adjustment_evidence(client):
    p=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()
    rows=list(csv.reader(io.StringIO(client.get("/api/runs/"+p["run_id"]+"/archive").data.decode("utf-8-sig"))))
    kinds={row[3] for row in rows[1:]}
    assert {"adjustment","adjustment_basis","adjustment_statement"}<=kinds
    assert sum(1 for row in rows[1:] if row[3]=="adjustment_quarantine")>=4

def test_failed_adjustment_approval_keeps_previous_version_verifiable(client):
    p=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()
    run_id=p["run_id"]
    assert client.post("/api/runs/"+run_id+"/review",json={"version":1,"decision":"已复核"}).status_code==200
    bad={"sample":"dirty.csv","parameters":{"price_adjustments":[{"basis_id":"PA-BAD","item":"001","original_price":"100","new_price":"120","retroactive_from":"2026-03","retroactive_to":"2026-11"}],"settlement_period":"2026/11"}}
    assert client.post("/api/runs",json=bad).status_code==422
    kept=client.get("/api/runs/"+run_id).get_json()
    assert kept["version"]==2 and kept["decision"]=="已复核"
    assert kept["stages"][7]["metrics"]["signed_rows"]==4
    assert kept["stages"][7]["rows"][0]["status"]=="已签认"
    assert kept["manifest"]["rule_version"]

def test_adjustment_basis_quarantine_not_priced(client):
    bases=[{"basis_id":"PA-X","item":"001","original_price":"100","new_price":"120","retroactive_from":"2026-03","retroactive_to":"2026-11","status":"待审批","approved":False}]
    p=client.post("/api/runs",json={"sample":"dirty.csv","parameters":{"price_adjustments":bases}}).get_json()
    stage=p["stages"][7]
    assert stage["rows"]==[] and stage["metrics"]["net_adjustment"]=="0.00"
    assert stage["quarantine"][0]["reason"]=="UNAPPROVED_ADJUSTMENT"
    assert stage["metrics"]["signable"] is False

def test_reject_review_releases_settlement(client):
    p=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()
    url="/api/runs/"+p["run_id"]+"/review"
    assert client.post(url,json={"version":1,"decision":"已复核"}).status_code==200
    assert len(client.get("/api/adjustments/settlements").get_json()["settlements"])==4
    assert client.post(url,json={"version":2,"decision":"退回复核"}).status_code==200
    assert client.get("/api/adjustments/settlements").get_json()["settlements"]==[]
    stage=client.get("/api/runs/"+p["run_id"]).get_json()["stages"][7]
    assert stage["metrics"]["pending_rows"]==4 and stage["metrics"]["net_adjustment"]=="2000.00"

def test_adjustment_stage_does_not_change_cumulative_chain(client):
    plain=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()
    bases=[{"basis_id":"PA-UP","change_id":"C1","item":"001","original_price":"100.00","new_price":"120.00","retroactive_from":"2026-03","retroactive_to":"2026-11","status":"已批准","approved":True,"effective_period":"2026-11"}]
    priced=client.post("/api/runs",json={"sample":"dirty.csv","parameters":{"price_adjustments":bases}}).get_json()
    assert plain["stages"][3]==priced["stages"][3]
    assert plain["stages"][4]==priced["stages"][4]
    assert plain["stages"][5]["metrics"]["expected_total"]==priced["stages"][5]["metrics"]["expected_total"]
    assert priced["stages"][7]["metrics"]["net_adjustment"]=="2000.00"

def test_adjustments_preview_accepts_rows(client):
    rows=[{"claim_id":"A","item":"001","period":"2026-05","increment_qty":"25","unit_price":"100.00"}]
    body={"rows":rows,"context":{"parameters":{"price_adjustments":[{"basis_id":"PA","item":"001","original_price":"100","new_price":"120","retroactive_from":"2026-01","retroactive_to":"2026-11","status":"已批准"}]}}}
    r=client.post("/api/adjustments",json=body)
    assert r.status_code==200 and r.get_json()["metrics"]["net_adjustment"]=="500.00"
