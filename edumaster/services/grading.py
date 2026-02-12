from core.utils import clean_note

def parse_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None

def safe_list_get(values, idx, default=""):
    if idx < len(values):
        return values[idx]
    return default

def clean_component(value, maximum):
    score = clean_note(value)
    if score > maximum:
        score = float(maximum)
    return round(score, 2)

def sum_activite_components(participation, comportement, cahier, projet, assiduite_outils):
    return round(
        float(participation)
        + float(comportement)
        + float(cahier)
        + float(projet)
        + float(assiduite_outils),
        2,
    )

def split_activite_components(total):
    remaining = clean_note(total)
    caps = (3.0, 6.0, 5.0, 4.0, 2.0)
    values = []
    for cap in caps:
        take = min(remaining, cap)
        values.append(round(take, 2))
        remaining = round(max(0.0, remaining - take), 2)
    return tuple(values)

def note_expr(trim):
    devoir = f"COALESCE(n.devoir, e.devoir_t{trim})"
    activite = f"COALESCE(n.activite, e.activite_t{trim})"
    compo = f"COALESCE(n.compo, e.compo_t{trim})"
    remarques = f"COALESCE(n.remarques, e.remarques_t{trim})"
    moy_expr = f"(({devoir} + {activite})/2.0 + ({compo}*2.0))/3.0"
    return devoir, activite, compo, remarques, moy_expr
