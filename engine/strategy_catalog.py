"""Direct and independently evaluated inverse strategies over each definition."""
import hashlib,json
from pattern_catalog import SEARCHABLE

SUFFIX="__Inverse"
STRATEGIES=[{**p,"variant":"direct","base_pattern":p["name"]} for p in SEARCHABLE]+[
    {**p,"name":p["name"]+SUFFIX,"display_name":p["display_name"]+" · Inverse",
     "variant":"inverse","base_pattern":p["name"]} for p in SEARCHABLE]
BY_STRATEGY={p["name"]:p for p in STRATEGIES}
STRATEGY_HASH=hashlib.sha256(json.dumps(STRATEGIES,sort_keys=True).encode()).hexdigest()


def inverse(event):
    result={**event,"name":event["name"]+SUFFIX,"sign":-event["sign"],"variant":"inverse","base_pattern":event["name"]}
    if "id" in result:
        result["id"]+="-inverse"
    if "direction" in result:
        result["direction"]="SHORT" if event["direction"]=="LONG" else "LONG"
    result["display_name"]=BY_STRATEGY[result["name"]]["display_name"]
    return result


def variants(event):
    return [{**event,"variant":"direct","base_pattern":event["name"]},inverse(event)]


def fixed_configurations(threshold=.85,tf=None):
    """Every applicable detector, fixed before looking at any trade outcome."""
    from research_model import METHODS
    output=[]
    for strategy in STRATEGIES:
        recognition=strategy['recognition']
        if tf is not None and tf!='1w' and recognition=='weekly_context':continue
        methods=METHODS[:4] if recognition=='original_5_point_similarity' else [METHODS[4]] if recognition=='curve_similarity' else METHODS[:3] if recognition in ('roof_geometry','wolfe_geometry') else [METHODS[6]] if recognition=='weekly_context' else [METHODS[7]] if recognition=='gap_classification' else [METHODS[5]]
        for method in methods:
            output.append({**strategy,'method':method,'threshold':threshold})
    return output
