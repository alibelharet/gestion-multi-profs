from .grading import parse_float
from .import_utils import parse_date

def build_filters(user_id, trim, args, moy_expr_override=None):
    niveau = args.get("niveau", "")
    search = (args.get("recherche") or "").strip()
    sort = args.get("sort", "class")
    order = args.get("order", "asc")
    etat = args.get("etat", "all")
    min_moy = parse_float(args.get("min_moy", ""))
    max_moy = parse_float(args.get("max_moy", ""))
    if min_moy is not None and max_moy is not None and min_moy > max_moy:
        min_moy, max_moy = max_moy, min_moy

    if order not in ("asc", "desc"):
        order = "asc"

    moy_expr = (
        moy_expr_override
        if moy_expr_override
        else f"((devoir_t{trim} + activite_t{trim})/2.0 + (compo_t{trim}*2.0))/3.0"
    )
    where = "e.user_id = ?"
    params = [user_id]

    if niveau and niveau != "all":
        where += " AND e.niveau = ?"
        params.append(niveau)
    if search:
        where += " AND e.nom_complet LIKE ?"
        params.append(f"%{search}%")

    if min_moy is not None:
        where += f" AND {moy_expr} >= ?"
        params.append(min_moy)
    if max_moy is not None:
        where += f" AND {moy_expr} <= ?"
        params.append(max_moy)

    if etat == "admis":
        where += f" AND {moy_expr} >= 10"
    elif etat == "echec":
        where += f" AND {moy_expr} > 0 AND {moy_expr} < 10"
    elif etat == "non_saisi":
        where += f" AND {moy_expr} <= 0"

    return {
        "niveau": niveau,
        "search": search,
        "sort": sort,
        "order": order,
        "etat": etat,
        "min_moy": min_moy,
        "max_moy": max_moy,
        "moy_expr": moy_expr,
        "where": where,
        "params": params,
    }


def build_history_filters(user_id, args):
    action = (args.get("action") or "").strip()
    q = (args.get("q") or "").strip()
    subject_val = (args.get("subject") or "").strip()
    date_from_raw = (args.get("from") or "").strip()
    date_to_raw = (args.get("to") or "").strip()

    subject_id = None
    try:
        if subject_val:
            subject_id = int(subject_val)
    except Exception:
        subject_id = None

    date_from = parse_date(date_from_raw)
    date_to = parse_date(date_to_raw)

    where = "l.user_id = ?"
    params = [user_id]

    if action:
        where += " AND l.action = ?"
        params.append(action)
    if subject_id:
        where += " AND l.subject_id = ?"
        params.append(subject_id)
    if q:
        where += " AND (l.details LIKE ? OR e.nom_complet LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%"])
    if date_from:
        where += " AND l.created_at >= ?"
        params.append(int(date_from.timestamp()))
    if date_to:
        end = date_to.replace(hour=23, minute=59, second=59)
        where += " AND l.created_at <= ?"
        params.append(int(end.timestamp()))

    return {
        "where": where,
        "params": params,
        "action": action,
        "q": q,
        "subject_id": subject_id,
        "date_from": date_from_raw,
        "date_to": date_to_raw,
    }
