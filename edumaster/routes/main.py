import json
from io import BytesIO

import openpyxl
import pandas as pd
from flask import Blueprint, flash, redirect, render_template, request, send_file, session, url_for

from core.db import get_db
from core.security import login_required
from core.utils import clean_note, get_appreciation_dynamique

bp = Blueprint("main", __name__)


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
            count = 0
            for nom_onglet, df in all_sheets.items():
                header_row = -1
                for i, row in df.head(20).iterrows():
                    joined = " ".join([str(v) for v in row.values])
                    if "اللقب" in joined or "Nom" in joined:
                        header_row = i
                        break
                if header_row == -1:
                    continue
                df.columns = df.iloc[header_row]
                df = df.iloc[header_row + 1 :]
                c_nom, c_prenom, c_d, c_a, c_c = None, None, None, None, None
                for c in df.columns:
                    cs = str(c).strip()
                    if cs in ["4", "04"] or "Dev" in cs:
                        c_d = c
                    elif cs in ["1", "01"] or "Act" in cs:
                        c_a = c
                    elif cs in ["9", "09"] or "Compo" in cs:
                        c_c = c
                    elif "الفرض" in cs:
                        c_d = c
                    elif "التقويم" in cs or "النشاط" in cs:
                        c_a = c
                    elif "الاختبار" in cs:
                        c_c = c
                    elif "اللقب" in cs or "Nom" in cs:
                        c_nom = c
                    elif "Prénom" in cs or "Prenom" in cs:
                        c_prenom = c

                if c_nom:
                    for _, row in df.iterrows():
                        if str(row[c_nom]) == "nan":
                            continue
                        nom = f"{row[c_nom]} {str(row[c_prenom]) if c_prenom and str(row[c_prenom]) != 'nan' else ''}".strip()
                        d = clean_note(row[c_d]) if c_d else 0
                        a = clean_note(row[c_a]) if c_a else 0
                        c = clean_note(row[c_c]) if c_c else 0
                        moy = ((d + a) / 2 + (c * 2)) / 3
                        rem = get_appreciation_dynamique(moy, user_id)
                        ex = db.execute(
                            "SELECT id FROM eleves WHERE nom_complet = ? AND niveau = ? AND user_id = ?",
                            (nom, nom_onglet.strip(), user_id),
                        ).fetchone()
                        if ex:
                            db.execute(
                                f"UPDATE eleves SET remarques_t{trim}=?, devoir_t{trim}=?, activite_t{trim}=?, compo_t{trim}=? WHERE id=?",
                                (rem, d, a, c, ex["id"]),
                            )
                        else:
                            db.execute(
                                f"INSERT INTO eleves (user_id, nom_complet, niveau, remarques_t{trim}, devoir_t{trim}, activite_t{trim}, compo_t{trim}) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (user_id, nom, nom_onglet.strip(), rem, d, a, c),
                            )
                        count += 1
            db.commit()
            flash(f"Import réussi ({count} élèves)", "success")
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

    niveau = request.args.get("niveau", "")
    search = (request.args.get("recherche") or "").strip()
    sort = request.args.get("sort", "class")
    order = request.args.get("order", "asc")

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
    if order not in ("asc", "desc"):
        order = "asc"

    db = get_db()

    classes = [
        r["niveau"]
        for r in db.execute(
            "SELECT DISTINCT niveau FROM eleves WHERE user_id = ? ORDER BY niveau",
            (user_id,),
        ).fetchall()
    ]

    where = "user_id = ?"
    params: list = [user_id]
    if niveau and niveau != "all":
        where += " AND niveau = ?"
        params.append(niveau)
    if search:
        where += " AND nom_complet LIKE ?"
        params.append(f"%{search}%")

    moy_expr = f"((devoir_t{trim} + activite_t{trim})/2.0 + (compo_t{trim}*2.0))/3.0"

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


@bp.route("/print_list")
@login_required
def print_list():
    user_id = session["user_id"]
    trim = request.args.get("trimestre", "1")
    if trim not in ("1", "2", "3"):
        trim = "1"
    niveau = request.args.get("niveau", "all")

    db = get_db()
    query = "SELECT * FROM eleves WHERE user_id = ?"
    params: list = [user_id]
    if niveau and niveau != "all":
        query += " AND niveau = ?"
        params.append(niveau)
    query += " ORDER BY niveau, id"

    eleves_db = db.execute(query, params).fetchall()
    eleves_list = []
    for el in eleves_db:
        d, a, c = el[f"devoir_t{trim}"], el[f"activite_t{trim}"], el[f"compo_t{trim}"]
        moy = round(((d + a) / 2 + (c * 2)) / 3, 2)
        eleves_list.append(
            {
                "nom_complet": el["nom_complet"],
                "niveau": el["niveau"],
                "activite": a,
                "devoir": d,
                "compo": c,
                "moyenne": moy,
                "remarques": el[f"remarques_t{trim}"],
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
    return "Export Excel: à implémenter"
