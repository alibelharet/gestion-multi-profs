import json
import re
import unicodedata
from io import BytesIO

import openpyxl
import pandas as pd
from flask import Blueprint, flash, redirect, render_template, request, send_file, session, url_for

from core.db import get_db
from core.security import login_required
from core.utils import clean_note, get_appreciation_dynamique

bp = Blueprint("main", __name__)


def _parse_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _normalize_header(value):
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[\s\-_]+", "", text)
    return text


def _build_filters(user_id, trim, args):
    niveau = args.get("niveau", "")
    search = (args.get("recherche") or "").strip()
    sort = args.get("sort", "class")
    order = args.get("order", "asc")
    etat = args.get("etat", "all")
    min_moy = _parse_float(args.get("min_moy", ""))
    max_moy = _parse_float(args.get("max_moy", ""))
    if min_moy is not None and max_moy is not None and min_moy > max_moy:
        min_moy, max_moy = max_moy, min_moy

    if order not in ("asc", "desc"):
        order = "asc"

    moy_expr = f"((devoir_t{trim} + activite_t{trim})/2.0 + (compo_t{trim}*2.0))/3.0"
    where = "user_id = ?"
    params = [user_id]

    if niveau and niveau != "all":
        where += " AND niveau = ?"
        params.append(niveau)
    if search:
        where += " AND nom_complet LIKE ?"
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


@bp.route("/sauvegarder_tout", methods=["POST"])
@login_required
def sauvegarder_tout():
    user_id = session["user_id"]
    trim = request.form.get("trimestre_save")
    ids = request.form.getlist("id_eleve")
    devs = request.form.getlist("devoir")
    acts = request.form.getlist("activite")
    comps = request.form.getlist("compo")

    db = get_db()
    for i in range(len(ids)):
        try:
            d, a, c = clean_note(devs[i]), clean_note(acts[i]), clean_note(comps[i])
            moy = ((d + a) / 2 + (c * 2)) / 3
            db.execute(
                f"UPDATE eleves SET devoir_t{trim}=?, activite_t{trim}=?, compo_t{trim}=?, remarques_t{trim}=? WHERE id=? AND user_id=?",
                (d, a, c, get_appreciation_dynamique(moy, user_id), ids[i], user_id),
            )
        except Exception:
            continue
    db.commit()
    flash("Notes enregistrées.", "success")
    return redirect(request.referrer or url_for("main.index", trimestre=trim))


@bp.route("/ajouter_eleve", methods=["POST"])
@login_required
def ajouter_eleve():
    user_id = session["user_id"]
    trim = request.form.get("trimestre_ajout", "1")
    d = clean_note(request.form.get("devoir"))
    a = clean_note(request.form.get("activite"))
    c = clean_note(request.form.get("compo"))
    moy = ((d + a) / 2 + (c * 2)) / 3

    db = get_db()
    db.execute(
        f"INSERT INTO eleves (user_id, nom_complet, niveau, remarques_t{trim}, devoir_t{trim}, activite_t{trim}, compo_t{trim}) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            user_id,
            request.form["nom_complet"],
            request.form["niveau"],
            get_appreciation_dynamique(moy, user_id),
            d,
            a,
            c,
        ),
    )
    db.commit()
    return redirect(request.referrer or url_for("main.index", trimestre=trim))


@bp.route("/supprimer_multi", methods=["POST"])
@login_required
def supprimer_multi():
    ids = request.form.getlist("ids")
    if ids:
        db = get_db()
        db.execute(
            f"DELETE FROM eleves WHERE id IN ({','.join('?'*len(ids))}) AND user_id = ?",
            ids + [session["user_id"]],
        )
        db.commit()
        flash(f"Supprimés ({len(ids)})", "success")
    return redirect(request.referrer or url_for("main.index"))


@bp.route("/import_excel", methods=["POST"])
@login_required
def import_excel():
    user_id = session["user_id"]
    trim = request.form.get("trimestre_import", "1")
    file = request.files.get("fichier_excel")
    if file and file.filename:
        try:
            db = get_db()
            all_sheets = pd.read_excel(file, sheet_name=None, header=None)
            inserted = 0
            updated = 0
            skipped = 0

            for nom_onglet, df in all_sheets.items():
                if df is None or df.empty:
                    continue

                header_row = -1
                for i, row in df.head(30).iterrows():
                    joined = " ".join([str(v) for v in row.values])
                    cells = [_normalize_header(v) for v in row.values]
                    if (
                        "Ø§Ù„Ù„Ù‚Ø¨" in joined
                        or "Nom" in joined
                        or "اللقب" in joined
                        or "الاسم" in joined
                        or any(
                            c in {"nom", "prenom", "nomcomplet", "nomprenom", "fullname"}
                            for c in cells
                        )
                    ):
                        header_row = i
                        break

                if header_row == -1:
                    skipped += 1
                    continue

                df.columns = df.iloc[header_row]
                df = df.iloc[header_row + 1 :]

                c_full = None
                c_nom = None
                c_prenom = None
                c_niveau = None
                c_d = None
                c_a = None
                c_c = None
                c_rem = None

                for col in df.columns:
                    raw = str(col).strip()
                    norm = _normalize_header(col)

                    if norm in ("nomcomplet", "nomprenom", "fullname"):
                        c_full = col
                    elif norm in ("nom", "lastname", "surname"):
                        c_nom = col
                    elif norm in ("prenom", "firstname"):
                        c_prenom = col
                    elif norm in ("classe", "niveau", "class"):
                        c_niveau = col
                    elif norm in ("devoir", "dev", "homework", "04", "4"):
                        c_d = col
                    elif norm in ("activite", "activite", "act", "activity", "01", "1"):
                        c_a = col
                    elif norm in ("compo", "composition", "exam", "test", "09", "9"):
                        c_c = col
                    elif norm in ("remarques", "appreciation", "rem", "obs", "commentaire"):
                        c_rem = col
                    elif "اللقب" in raw:
                        c_nom = c_nom or col
                    elif "الاسم" in raw:
                        c_prenom = c_prenom or col
                    elif "القسم" in raw or "المستوى" in raw:
                        c_niveau = c_niveau or col
                    elif "الفرض" in raw:
                        c_d = c_d or col
                    elif "النشاط" in raw:
                        c_a = c_a or col
                    elif "الاختبار" in raw:
                        c_c = c_c or col
                    elif "التقدير" in raw:
                        c_rem = c_rem or col
                    elif "Ø§Ù„Ù„Ù‚Ø¨" in raw or "Nom" in raw:
                        c_nom = c_nom or col
                    elif "PrÃ©nom" in raw or "Prenom" in raw:
                        c_prenom = c_prenom or col
                    elif "Dev" in raw:
                        c_d = c_d or col
                    elif "Act" in raw:
                        c_a = c_a or col
                    elif "Compo" in raw:
                        c_c = c_c or col

                for _, row in df.iterrows():
                    def _val(c):
                        if c is None:
                            return None
                        v = row.get(c, None)
                        return None if pd.isna(v) else v

                    full = ""
                    if c_full:
                        full = str(_val(c_full) or "").strip()
                    else:
                        nom = str(_val(c_nom) or "").strip()
                        prenom = str(_val(c_prenom) or "").strip()
                        full = f"{nom} {prenom}".strip()

                    if not full:
                        continue

                    niveau = str(_val(c_niveau) or "").strip() if c_niveau else ""
                    if not niveau:
                        niveau = str(nom_onglet).strip() or "Global"

                    d = clean_note(_val(c_d)) if c_d else 0
                    a = clean_note(_val(c_a)) if c_a else 0
                    c = clean_note(_val(c_c)) if c_c else 0
                    moy = ((d + a) / 2 + (c * 2)) / 3
                    rem = get_appreciation_dynamique(moy, user_id)
                    if c_rem:
                        custom_rem = _val(c_rem)
                        if custom_rem is not None and str(custom_rem).strip():
                            rem = str(custom_rem).strip()

                    ex = db.execute(
                        "SELECT id FROM eleves WHERE nom_complet = ? AND niveau = ? AND user_id = ?",
                        (full, niveau, user_id),
                    ).fetchone()
                    if ex:
                        db.execute(
                            f"UPDATE eleves SET remarques_t{trim}=?, devoir_t{trim}=?, activite_t{trim}=?, compo_t{trim}=? WHERE id=?",
                            (rem, d, a, c, ex["id"]),
                        )
                        updated += 1
                    else:
                        db.execute(
                            f"INSERT INTO eleves (user_id, nom_complet, niveau, remarques_t{trim}, devoir_t{trim}, activite_t{trim}, compo_t{trim}) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (user_id, full, niveau, rem, d, a, c),
                        )
                        inserted += 1

            db.commit()
            total = inserted + updated
            flash(
                f"Import OK: {total} lignes (nouveaux {inserted}, mis Ã  jour {updated}, onglets ignorÃ©s {skipped})",
                "success",
            )
        except Exception as e:
            flash(f"Erreur: {e}", "danger")
    return redirect(request.referrer or url_for("main.index", trimestre=trim))


@bp.route("/remplir_bulletin_officiel", methods=["POST"])
@login_required
def remplir_bulletin_officiel():
    user_id = session["user_id"]
    trim = request.form.get("trimestre_fill", "1")
    file = request.files.get("fichier_vide")
    if file and file.filename:
        try:
            wb = openpyxl.load_workbook(file)
            db = get_db()
            for sheet in wb.worksheets:
                header_row = None
                col_map = {}
                for i, row in enumerate(
                    sheet.iter_rows(min_row=1, max_row=20, values_only=True)
                ):
                    row_str = [str(c).lower() for c in row if c]
                    if any(x in row_str for x in ["nom", "اللقب"]):
                        header_row = i + 1
                        for cell in sheet[header_row]:
                            if not cell.value:
                                continue
                            v = str(cell.value).strip().lower()
                            if v in ["nom", "اللقب"]:
                                col_map["nom"] = cell.column
                            elif v in ["prenom", "الاسم"]:
                                col_map["prenom"] = cell.column
                            elif v in ["01", "act", "النشاطات"]:
                                col_map["act"] = cell.column
                            elif v in ["04", "dev", "الفرض"]:
                                col_map["dev"] = cell.column
                            elif v in ["09", "compo", "الاختبار"]:
                                col_map["compo"] = cell.column
                            elif v in ["obs", "rem", "التقديرات"]:
                                col_map["rem"] = cell.column
                        break

                if header_row and "nom" in col_map:
                    for r in range(header_row + 1, sheet.max_row + 1):
                        nom = sheet.cell(row=r, column=col_map["nom"]).value
                        if not nom:
                            continue
                        prenom = (
                            sheet.cell(row=r, column=col_map.get("prenom")).value
                            if col_map.get("prenom")
                            else ""
                        )
                        full = f"{nom} {prenom}".strip()
                        el = db.execute(
                            "SELECT * FROM eleves WHERE nom_complet = ? AND user_id = ?",
                            (full, user_id),
                        ).fetchone()
                        if el:
                            if "act" in col_map:
                                sheet.cell(row=r, column=col_map["act"]).value = el[
                                    f"activite_t{trim}"
                                ]
                            if "dev" in col_map:
                                sheet.cell(row=r, column=col_map["dev"]).value = el[
                                    f"devoir_t{trim}"
                                ]
                            if "compo" in col_map:
                                sheet.cell(row=r, column=col_map["compo"]).value = el[
                                    f"compo_t{trim}"
                                ]
                            if "rem" in col_map:
                                sheet.cell(row=r, column=col_map["rem"]).value = el[
                                    f"remarques_t{trim}"
                                ]
            out = BytesIO()
            wb.save(out)
            out.seek(0)
            return send_file(
                out,
                download_name="Bulletin_Rempli.xlsx",
                as_attachment=True,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception as e:
            flash(f"Erreur: {e}", "danger")
    return redirect(request.referrer or url_for("main.index"))


@bp.route("/")
@login_required
def index():
    user_id = session["user_id"]
    trim = request.args.get("trimestre", "1")
    if trim not in ("1", "2", "3"):
        trim = "1"

    filters = _build_filters(user_id, trim, request.args)
    niveau = filters["niveau"]
    search = filters["search"]
    sort = filters["sort"]
    order = filters["order"]
    etat = filters["etat"]
    min_moy = filters["min_moy"]
    max_moy = filters["max_moy"]

    try:
        page = int(request.args.get("page", "1") or 1)
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get("per_page", "50") or 50)
    except ValueError:
        per_page = 50

    page = max(1, page)
    per_page = min(200, max(10, per_page))
    db = get_db()

    classes = [
        r["niveau"]
        for r in db.execute(
            "SELECT DISTINCT niveau FROM eleves WHERE user_id = ? ORDER BY niveau",
            (user_id,),
        ).fetchall()
    ]

    where = filters["where"]
    params: list = filters["params"]
    moy_expr = filters["moy_expr"]

    stats_row = db.execute(
        f"""
        SELECT
          COUNT(*) AS nb_total,
          SUM(CASE WHEN {moy_expr} > 0 THEN 1 ELSE 0 END) AS nb_saisis,
          SUM(CASE WHEN {moy_expr} >= 10 THEN 1 ELSE 0 END) AS nb_admis,
          AVG(CASE WHEN {moy_expr} > 0 THEN {moy_expr} END) AS moyenne_generale,
          MAX(CASE WHEN {moy_expr} > 0 THEN {moy_expr} END) AS meilleure_note,
          MIN(CASE WHEN {moy_expr} > 0 THEN {moy_expr} END) AS pire_note
        FROM eleves
        WHERE {where}
        """,
        params,
    ).fetchone()

    total = int(stats_row["nb_total"] or 0)
    pages = max(1, (total + per_page - 1) // per_page)
    if page > pages:
        page = pages
    offset = (page - 1) * per_page

    direction = "DESC" if order == "desc" else "ASC"
    if sort == "name":
        order_clause = f"nom_complet COLLATE NOCASE {direction}, id ASC"
    elif sort == "moy":
        order_clause = f"moyenne {direction}, nom_complet COLLATE NOCASE ASC, id ASC"
    elif sort == "id":
        order_clause = f"id {direction}"
    else:
        order_clause = f"niveau COLLATE NOCASE {direction}, id ASC"

    rows = db.execute(
        f"""
        SELECT
          id,
          nom_complet,
          niveau,
          devoir_t{trim} AS devoir,
          activite_t{trim} AS activite,
          compo_t{trim} AS compo,
          remarques_t{trim} AS remarques,
          ROUND({moy_expr}, 2) AS moyenne
        FROM eleves
        WHERE {where}
        ORDER BY {order_clause}
        LIMIT ? OFFSET ?
        """,
        params + [per_page, offset],
    ).fetchall()

    eleves_list = [
        {
            "id": r["id"],
            "nom_complet": r["nom_complet"],
            "niveau": r["niveau"],
            "remarques": r["remarques"],
            "devoir": r["devoir"],
            "activite": r["activite"],
            "compo": r["compo"],
            "moyenne": float(r["moyenne"] or 0),
        }
        for r in rows
    ]

    nb_admis = int(stats_row["nb_admis"] or 0)
    nb_total = total

    stats = {
        "moyenne_generale": round(float(stats_row["moyenne_generale"] or 0), 2),
        "meilleure_note": round(float(stats_row["meilleure_note"] or 0), 2),
        "pire_note": round(float(stats_row["pire_note"] or 0), 2),
        "nb_admis": nb_admis,
        "taux_reussite": round((nb_admis / nb_total) * 100, 1) if nb_total else 0,
        "nb_total": nb_total,
        "nb_saisis": int(stats_row["nb_saisis"] or 0),
    }

    class_rows = db.execute(
        f"""
        SELECT
          niveau,
          COUNT(*) AS total,
          AVG(CASE WHEN {moy_expr} > 0 THEN {moy_expr} END) AS avg_moy
        FROM eleves
        WHERE {where}
        GROUP BY niveau
        ORDER BY avg_moy DESC, niveau ASC
        """,
        params,
    ).fetchall()

    class_labels = [str(r["niveau"]) for r in class_rows]
    class_avgs = [round(float(r["avg_moy"] or 0), 2) for r in class_rows]

    dist_row = db.execute(
        f"""
        SELECT
          SUM(CASE WHEN {moy_expr} >= 10 THEN 1 ELSE 0 END) AS admis,
          SUM(CASE WHEN {moy_expr} > 0 AND {moy_expr} < 10 THEN 1 ELSE 0 END) AS echec,
          SUM(CASE WHEN {moy_expr} <= 0 THEN 1 ELSE 0 END) AS non_saisi
        FROM eleves
        WHERE {where}
        """,
        params,
    ).fetchone()

    dist_values = [
        int(dist_row["admis"] or 0),
        int(dist_row["echec"] or 0),
        int(dist_row["non_saisi"] or 0),
    ]

    top_rows = db.execute(
        f"""
        SELECT
          nom_complet,
          niveau,
          ROUND({moy_expr}, 2) AS moyenne
        FROM eleves
        WHERE {where}
        ORDER BY moyenne DESC, nom_complet ASC
        LIMIT 10
        """,
        params,
    ).fetchall()

    top_eleves = [
        {
            "nom": r["nom_complet"],
            "niveau": r["niveau"],
            "moyenne": float(r["moyenne"] or 0),
        }
        for r in top_rows
    ]

    chart_data = json.dumps(
        {
            "classes": {"labels": class_labels, "values": class_avgs},
            "distribution": {
                "labels": ["Admis", "Echec", "Non saisi"],
                "values": dist_values,
            },
        }
    )

    base_args = dict(request.args)
    base_args.pop("page", None)

    return render_template(
        "index.html",
        eleves=eleves_list,
        stats=stats,
        trimestre=trim,
        nom_prof=session.get("nom_affichage"),
        niveau_actuel=niveau,
        recherche_actuelle=search,
        liste_classes=classes,
        sort=sort,
        order=order,
        page=page,
        pages=pages,
        per_page=per_page,
        total=total,
        base_args=base_args,
        min_moy=min_moy,
        max_moy=max_moy,
        etat=etat,
        chart_data=chart_data,
        top_eleves=top_eleves,
    )


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user_id = session["user_id"]
    db = get_db()

    if request.method == "POST":
        mins = request.form.getlist("min_val")
        maxs = request.form.getlist("max_val")
        msgs = request.form.getlist("message")

        db.execute("DELETE FROM appreciations WHERE user_id = ?", (user_id,))
        for i in range(len(mins)):
            if not mins[i]:
                continue
            try:
                min_v = float(mins[i])
                max_v = float(maxs[i]) if maxs[i] else min_v
            except ValueError:
                continue
            db.execute(
                "INSERT INTO appreciations (user_id, min_val, max_val, message) VALUES (?, ?, ?, ?)",
                (user_id, min_v, max_v, msgs[i]),
            )
        db.commit()

        # Recalcul rapide des remarques
        for el in db.execute(
            "SELECT * FROM eleves WHERE user_id = ?",
            (user_id,),
        ).fetchall():
            for t in range(1, 4):
                moy = (
                    (el[f"devoir_t{t}"] + el[f"activite_t{t}"]) / 2
                    + (el[f"compo_t{t}"] * 2)
                ) / 3
                db.execute(
                    f"UPDATE eleves SET remarques_t{t} = ? WHERE id = ?",
                    (get_appreciation_dynamique(moy, user_id), el["id"]),
                )
        db.commit()
        flash("Sauvegarde", "success")

    rules = db.execute(
        "SELECT * FROM appreciations WHERE user_id = ? ORDER BY min_val",
        (user_id,),
    ).fetchall()
    return render_template("settings.html", rules=rules)


@bp.route("/bulletin/<int:id>")
@login_required
def bulletin(id: int):
    user_id = session["user_id"]
    trim = request.args.get("trimestre", "1")
    if trim not in ("1", "2", "3"):
        trim = "1"

    db = get_db()
    eleve = db.execute(
        "SELECT * FROM eleves WHERE id = ? AND user_id = ?",
        (id, user_id),
    ).fetchone()
    if not eleve:
        return "Élève introuvable"

    camarades = db.execute(
        "SELECT * FROM eleves WHERE user_id = ? AND niveau = ?",
        (user_id, eleve["niveau"]),
    ).fetchall()
    scores = []
    for c in camarades:
        moy = ((c[f"devoir_t{trim}"] + c[f"activite_t{trim}"]) / 2 + (c[f"compo_t{trim}"] * 2)) / 3
        scores.append((c["id"], moy))
    scores.sort(key=lambda x: x[1], reverse=True)

    rank = next((i + 1 for i, s in enumerate(scores) if s[0] == id), 1)
    moy_eleve = next(s[1] for s in scores if s[0] == id)
    moy_classe = sum(s[1] for s in scores) / len(scores) if scores else 0

    return render_template(
        "bulletin.html",
        eleve=eleve,
        rank=rank,
        total_eleves=len(scores),
        moyenne=round(moy_eleve, 2),
        moyenne_classe=round(moy_classe, 2),
        trimestre=trim,
        nom_prof=session.get("nom_affichage"),
    )


@bp.route("/bulletin_pdf/<int:id>")
@login_required
def bulletin_pdf(id: int):
    user_id = session["user_id"]
    trim = request.args.get("trimestre", "1")
    if trim not in ("1", "2", "3"):
        trim = "1"

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except Exception:
        flash("PDF indisponible. Installez reportlab (pip install reportlab).", "danger")
        return redirect(url_for("main.bulletin", id=id, trimestre=trim))

    db = get_db()
    eleve = db.execute(
        "SELECT * FROM eleves WHERE id = ? AND user_id = ?",
        (id, user_id),
    ).fetchone()
    if not eleve:
        return "Eleve introuvable"

    camarades = db.execute(
        "SELECT * FROM eleves WHERE user_id = ? AND niveau = ?",
        (user_id, eleve["niveau"]),
    ).fetchall()
    scores = []
    for c in camarades:
        moy = ((c[f"devoir_t{trim}"] + c[f"activite_t{trim}"]) / 2 + (c[f"compo_t{trim}"] * 2)) / 3
        scores.append((c["id"], moy))
    scores.sort(key=lambda x: x[1], reverse=True)

    rank = next((i + 1 for i, s in enumerate(scores) if s[0] == id), 1)
    moy_eleve = next(s[1] for s in scores if s[0] == id)
    moy_classe = sum(s[1] for s in scores) / len(scores) if scores else 0

    activite = eleve[f"activite_t{trim}"]
    devoir = eleve[f"devoir_t{trim}"]
    compo = eleve[f"compo_t{trim}"]
    moyenne = round(moy_eleve, 2)
    remarques = eleve[f"remarques_t{trim}"] or ""

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    styles = getSampleStyleSheet()

    story = []
    story.append(Paragraph("Bulletin de notes", styles["Title"]))
    story.append(Paragraph(f"Eleve: <b>{eleve['nom_complet']}</b>", styles["Normal"]))
    story.append(Paragraph(f"Classe: {eleve['niveau']} &nbsp;&nbsp; Trimestre: {trim}", styles["Normal"]))
    story.append(Paragraph(f"Prof: {session.get('nom_affichage', '')}", styles["Normal"]))
    story.append(Spacer(1, 10))

    table_data = [
        ["Matiere", "Activite", "Devoir", "Compo", "Moyenne", "Remarques"],
        ["Sciences", activite, devoir, compo, moyenne, remarques],
    ]
    table = Table(
        table_data,
        colWidths=[35 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm, 51 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("ALIGN", (1, 1), (4, 1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 14))

    summary_data = [
        ["Moyenne classe", round(moy_classe, 2)],
        ["Rang", f"{rank} / {len(scores)}"],
        ["Moyenne eleve", moyenne],
    ]
    summary = Table(summary_data, colWidths=[60 * mm, 40 * mm])
    summary.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (1, -1), "CENTER"),
            ]
        )
    )
    story.append(summary)

    doc.build(story)
    buffer.seek(0)

    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", eleve["nom_complet"])
    filename = f"bulletin_{safe_name}_T{trim}.pdf"
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


@bp.route("/print_list")
@login_required
def print_list():
    user_id = session["user_id"]
    trim = request.args.get("trimestre", "1")
    if trim not in ("1", "2", "3"):
        trim = "1"
    filters = _build_filters(user_id, trim, request.args)
    niveau = filters["niveau"]

    db = get_db()
    where = filters["where"]
    params: list = filters["params"]
    moy_expr = filters["moy_expr"]

    eleves_db = db.execute(
        f"""
        SELECT
          nom_complet,
          niveau,
          devoir_t{trim} AS devoir,
          activite_t{trim} AS activite,
          compo_t{trim} AS compo,
          remarques_t{trim} AS remarques,
          ROUND({moy_expr}, 2) AS moyenne
        FROM eleves
        WHERE {where}
        ORDER BY niveau, id
        """,
        params,
    ).fetchall()
    eleves_list = []
    for el in eleves_db:
        eleves_list.append(
            {
                "nom_complet": el["nom_complet"],
                "niveau": el["niveau"],
                "activite": el["activite"],
                "devoir": el["devoir"],
                "compo": el["compo"],
                "moyenne": float(el["moyenne"] or 0),
                "remarques": el["remarques"],
            }
        )

    return render_template(
        "print_template.html",
        eleves=eleves_list,
        nom_prof=session.get("nom_affichage"),
        trimestre=trim,
        niveau=niveau,
    )


@bp.route("/export_excel")
@login_required
def export_excel():
    user_id = session["user_id"]
    trim = request.args.get("trimestre", "1")
    if trim not in ("1", "2", "3"):
        trim = "1"

    filters = _build_filters(user_id, trim, request.args)
    where = filters["where"]
    params = filters["params"]
    moy_expr = filters["moy_expr"]
    sort = filters["sort"]
    order = filters["order"]

    direction = "DESC" if order == "desc" else "ASC"
    if sort == "name":
        order_clause = f"nom_complet COLLATE NOCASE {direction}, id ASC"
    elif sort == "moy":
        order_clause = f"moyenne {direction}, nom_complet COLLATE NOCASE ASC, id ASC"
    elif sort == "id":
        order_clause = f"id {direction}"
    else:
        order_clause = f"niveau COLLATE NOCASE {direction}, id ASC"

    db = get_db()
    rows = db.execute(
        f"""
        SELECT
          id,
          nom_complet,
          niveau,
          devoir_t{trim} AS devoir,
          activite_t{trim} AS activite,
          compo_t{trim} AS compo,
          remarques_t{trim} AS remarques,
          ROUND({moy_expr}, 2) AS moyenne
        FROM eleves
        WHERE {where}
        ORDER BY {order_clause}
        """,
        params,
    ).fetchall()

    data = []
    for r in rows:
        moy = float(r["moyenne"] or 0)
        if moy >= 10:
            etat = "Admis"
        elif moy > 0:
            etat = "Echec"
        else:
            etat = "Non saisi"
        data.append(
            {
                "ID": r["id"],
                "Nom complet": r["nom_complet"],
                "Classe": r["niveau"],
                "Activite": r["activite"],
                "Devoir": r["devoir"],
                "Compo": r["compo"],
                "Moyenne": moy,
                "Etat": etat,
                "Remarques": r["remarques"],
            }
        )

    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=f"T{trim}")
    output.seek(0)

    filename = f"export_eleves_T{trim}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


