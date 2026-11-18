import sqlite3,json
from datetime import datetime,timezone
from app.config import DATA_DIR
from app.errors import DomainError
def connect():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATA_DIR/"records.db",timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,decision TEXT NOT NULL DEFAULT '待复核')")
    db.execute("CREATE TABLE IF NOT EXISTS settlements (settlement_key TEXT PRIMARY KEY,run_id TEXT NOT NULL,basis_id TEXT,claim_id TEXT,item TEXT,period TEXT,amount TEXT,settled_at TEXT NOT NULL)")
    return db
def save(run_id,payload):
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO runs(id,payload) VALUES (?,?)",(run_id,json.dumps(payload,ensure_ascii=False)))
    return get(run_id)
def settled_index():
    with connect() as db: return [(row[0],row[1]) for row in db.execute("SELECT settlement_key,run_id FROM settlements")]
def settled_detail():
    with connect() as db: return [{"settlement_key":k,"run_id":r,"basis_id":b,"claim_id":c,"item":i,"period":p,"amount":a,"settled_at":t} for k,r,b,c,i,p,a,t in db.execute("SELECT settlement_key,run_id,basis_id,claim_id,item,period,amount,settled_at FROM settlements ORDER BY settled_at")]
def overlay(payload,run_id=None):
    from app.modules.m8_adjustments.rules import apply_settlements
    stages=payload.get("stages") or []
    if len(stages)<=7: return payload
    index=settled_index()
    if not index: return payload
    others={key for key,owner in index if owner!=run_id};here={key for key,owner in index if owner==run_id}
    stages=[*stages];stages[7]=apply_settlements(stages[7],others,here)
    return {**payload,"stages":stages}
def get(run_id):
    with connect() as db: row=db.execute("SELECT payload,version,decision FROM runs WHERE id=?",(run_id,)).fetchone()
    if not row: raise DomainError("NOT_FOUND","批次不存在",404)
    return {**overlay(json.loads(row[0]),run_id),"version":row[1],"decision":row[2]}
def latest():
    with connect() as db: rows=db.execute("SELECT id,payload,version,decision FROM runs ORDER BY rowid DESC").fetchall()
    from app.config import RULE_VERSION
    for run_id,payload,version,decision in rows:
        data=json.loads(payload)
        if data.get("manifest",{}).get("rule_version")==RULE_VERSION:
            return {**overlay(data,run_id),"version":version,"decision":decision}
    return None
def history():
    with connect() as db: return [{"run_id":i,"version":v,"decision":d} for i,v,d in db.execute("SELECT id,version,decision FROM runs ORDER BY rowid DESC")]
def review(run_id,version,decision):
    if decision not in {"已复核","退回复核"}: raise DomainError("BAD_DECISION","复核状态无效")
    with connect() as db:
        row=db.execute("SELECT payload,version FROM runs WHERE id=?",(run_id,)).fetchone()
        if not row: raise DomainError("NOT_FOUND","批次不存在",404)
        if row[1]!=version: raise DomainError("STALE_VERSION","版本已更新，请刷新",409)
        cursor=db.execute("UPDATE runs SET version=version+1,decision=? WHERE id=? AND version=?",(decision,run_id,version))
        if cursor.rowcount!=1: raise DomainError("STALE_VERSION","版本已更新，请刷新",409)
        payload=json.loads(row[0])
        if len(payload.get("stages") or [])>7:
            from app.modules.m8_adjustments.rules import apply_settlements
            index=settled_index()
            others={key for key,owner in index if owner!=run_id};here={key for key,owner in index if owner==run_id}
            adjustment=apply_settlements(payload["stages"][7],others,here)
            if decision=="退回复核":
                db.execute("DELETE FROM settlements WHERE run_id=?",(run_id,))
            else:
                now=datetime.now(timezone.utc).isoformat()
                for item in adjustment["rows"]:
                    if item.get("status")!="可结算" or not item.get("settlement_key"): continue
                    db.execute("INSERT OR IGNORE INTO settlements(settlement_key,run_id,basis_id,claim_id,item,period,amount,settled_at) VALUES (?,?,?,?,?,?,?,?)",
                        (item["settlement_key"],run_id,item.get("basis_id"),item.get("claim_id"),item.get("item"),item.get("period"),item.get("adjustment_amount"),now))
    return get(run_id)
