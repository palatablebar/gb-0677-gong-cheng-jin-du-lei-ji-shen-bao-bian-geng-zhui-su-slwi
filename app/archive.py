import csv,io,json
def build_archive(run):
    stream=io.StringIO(newline="");writer=csv.writer(stream)
    writer.writerow(["run_id","input_sha256","rule_version","kind","source_lines","reason","evidence"])
    meta=run["manifest"];stages=run.get("stages") or []
    certificate=stages[6] if len(stages)>6 else stages[-1]
    for row in certificate["rows"]:
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"accepted",json.dumps(row.get("_sources",[])),row.get("status",""),json.dumps(row,ensure_ascii=False)])
    for row in certificate.get("cumulative_quarantine",[]):
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"quarantine",json.dumps(row.get("_sources",[])),row.get("reason",""),json.dumps(row,ensure_ascii=False)])
    if len(stages)>7:
        adjustment=stages[7]
        for row in adjustment.get("rows",[]):
            writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"adjustment",json.dumps(row.get("_sources",[])),row.get("status",""),json.dumps(row,ensure_ascii=False)])
        for row in adjustment.get("basis_decisions",[]):
            writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"adjustment_basis","[]",row.get("reason",""),json.dumps(row,ensure_ascii=False)])
        for row in adjustment.get("quarantine",[]):
            writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"adjustment_quarantine","[]",row.get("reason",""),json.dumps(row,ensure_ascii=False)])
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"adjustment_statement","[]","",json.dumps({"statement":adjustment.get("statement",""),"metrics":adjustment.get("metrics",{})},ensure_ascii=False)])
    return "﻿"+stream.getvalue()
