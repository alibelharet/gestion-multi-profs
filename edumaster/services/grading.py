import math
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

def optional_note(value, maximum=20):
    """An empty cell is missing, while an explicit zero is a valid mark."""
    if value is None or str(value).strip().lower() in ('', 'nan', 'none'):
        return None
    try:
        number = float(str(value).replace(',', '.').strip())
    except (ValueError, TypeError):
        raise ValueError('invalid_note') from None
    if not math.isfinite(number) or not 0 <= number <= maximum:
        raise ValueError('invalid_note')
    return round(number, 2)


def assessment_state(activite, devoir, compo, absent=False):
    if absent:
        return 'absent'
    values = (activite, devoir, compo)
    if all(v is not None for v in values):
        return 'graded'
    return 'partial' if any(v is not None for v in values) else 'not_entered'


def note_expr(trim, alias='n'):
    """Missing and absent assessments have no average, including legacy zero rows."""
    if alias not in ('n', 'n1', 'n2', 'n3', 'nc', 'np'):
        raise ValueError('Invalid note alias')
    cols = trim_columns(trim)
    old_entered = ' OR '.join(f'COALESCE(e.{cols[k]}, 0) > 0' for k in ('devoir', 'activite', 'compo'))
    legacy_entered = ' OR '.join(f'COALESCE({alias}.{k}, 0) > 0' for k in ('devoir', 'activite', 'compo'))
    def field(key):
        return (f"(CASE WHEN {alias}.id IS NOT NULL THEN CASE "
                f"WHEN {alias}.assessment_status = 'legacy' AND NOT ({legacy_entered}) THEN NULL "
                f"ELSE {alias}.{key} END "
                f"WHEN ({old_entered}) THEN e.{cols[key]} ELSE NULL END)")
    devoir, activite, compo = (field(k) for k in ('devoir', 'activite', 'compo'))
    raw_average = f"(({devoir} + {activite})/2.0 + ({compo}*2.0))/3.0"
    moy_expr = f"(CASE WHEN {alias}.assessment_status = 'absent' THEN NULL ELSE {raw_average} END)"
    remarques = f"(CASE WHEN {moy_expr} IS NULL THEN '' WHEN {alias}.id IS NOT NULL THEN {alias}.remarques ELSE e.{cols['remarques']} END)"
    return devoir, activite, compo, remarques, moy_expr
