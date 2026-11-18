from flask import Blueprint,request,jsonify
from app.errors import DomainError
from app.pipeline import stage_preview
from app import store
bp=Blueprint("adjustments",__name__)
@bp.route("/api/adjustments",methods=["GET","POST"])
def preview():
    payload=request.get_json(silent=True) if request.method=="POST" else {}
    if payload is None or not isinstance(payload,dict): raise DomainError("BAD_BODY","请求需要对象")
    return jsonify(stage_preview(7,payload))
@bp.route("/api/adjustments/settlements",methods=["GET"])
def settlements():
    return jsonify({"settlements":store.settled_detail()})
