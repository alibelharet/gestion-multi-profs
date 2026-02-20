from core.utils import clean_note

# ── Safe trimester column mapping ──────────────────────────────────
# Whitelist of allowed trimester values → column name suffixes.
# This prevents SQL injection via f-string interpolation.
_TRIM_COLS = {
    "1": {"devoir": "devoir_t1", "activite": "activite_t1", "compo": "compo_t1", "remarques": "remarques_t1"},
    "2": {"devoir": "devoir_t2", "activite": "activite_t2", "compo": "compo_t2", "remarques": "remarques_t2"},
    "3": {"devoir": "devoir_t3", "activite": "activite_t3", "compo": "compo_t3", "remarques": "remarques_t3"},
}


def validated_trim(raw) -> str:
    """Return a safe trimester string ('1', '2', or '3'). Raises ValueError otherwise."""
    val = str(raw or "1").strip()
    if val not in _TRIM_COLS:
        raise ValueError(f"Invalid trimester value: {raw!r}")
    return val


def trim_columns(trim):
    """Return a dict of safe column names for the given trimester.

    Keys: 'devoir', 'activite', 'compo', 'remarques'
    """
    t = validated_trim(trim)
    return dict(_TRIM_COLS[t])


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
    """Build SQL expressions for a given trimester using safe column mapping."""
    cols = trim_columns(trim)
    devoir = f"COALESCE(n.devoir, e.{cols['devoir']})"
    activite = f"COALESCE(n.activite, e.{cols['activite']})"
    compo = f"COALESCE(n.compo, e.{cols['compo']})"
    remarques = f"COALESCE(n.remarques, e.{cols['remarques']})"
    moy_expr = f"(({devoir} + {activite})/2.0 + ({compo}*2.0))/3.0"
    return devoir, activite, compo, remarques, moy_expr
