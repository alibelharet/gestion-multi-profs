import json
import os
import re
import unicodedata

from core.utils import clean_note


class ScanImportError(RuntimeError):
    pass


_ARABIC_NORMALIZATION = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ؤ": "و",
        "ئ": "ي",
        "ى": "ي",
        "ة": "ه",
    }
)


def _optional_note(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return clean_note(text)


def normalize_lookup_text(value):
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.translate(_ARABIC_NORMALIZATION)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text, flags=re.UNICODE).strip().lower()
    return text


def _openai_client():
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise ScanImportError(
            "OPENAI_API_KEY manquant. Ajoutez-la dans le fichier .env du serveur avant d'utiliser l'import PDF scanne."
        )
    try:
        from openai import OpenAI
    except Exception as exc:
        raise ScanImportError(
            "Le module openai est manquant. Installez les dependances du projet sur le serveur."
        ) from exc
    return OpenAI(api_key=api_key)


def extract_rows_from_scanned_pdf(pdf_path, *, trim, subject_name="", school_year=""):
    if not os.path.exists(pdf_path):
        raise ScanImportError("Le fichier PDF scanne est introuvable.")

    client = _openai_client()
    model = (os.environ.get("OPENAI_OCR_MODEL") or "gpt-4.1").strip()
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "document_summary": {"type": "string"},
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "full_name": {"type": "string"},
                        "classe": {"type": "string"},
                        "activite": {"type": ["number", "null"]},
                        "devoir": {"type": ["number", "null"]},
                        "compo": {"type": ["number", "null"]},
                        "remarques": {"type": "string"},
                        "confidence": {"type": "number"},
                        "issues": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": [
                        "full_name",
                        "classe",
                        "activite",
                        "devoir",
                        "compo",
                        "remarques",
                        "confidence",
                        "issues",
                    ],
                },
            },
        },
        "required": ["document_summary", "rows"],
    }
    prompt = (
        "Analyse ce PDF scanne de liste de classe remplie a la main. "
        "Extrais une ligne par eleve avec son nom, sa classe et les notes visibles. "
        "Le document peut contenir du francais et de l'arabe. "
        "Respecte l'ordre des lignes du document. "
        "Ne devine jamais une note absente: mets null si la case est vide ou illegible. "
        "Les notes attendues sont activite, devoir et compo sur 20. "
        "Si une remarque manuscrite existe, mets-la dans remarques, sinon une chaine vide. "
        "Ajoute un score confidence entre 0 et 1 et une liste issues quand une ligne semble douteuse. "
        f"Contexte: trimestre T{trim}, matiere {subject_name or 'inconnue'}, annee scolaire {school_year or 'inconnue'}."
    )

    uploaded = None
    try:
        with open(pdf_path, "rb") as handle:
            uploaded = client.files.create(file=handle, purpose="user_data")

        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_file", "file_id": uploaded.id},
                        {"type": "input_text", "text": prompt},
                    ],
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "scan_grade_rows",
                    "schema": schema,
                    "strict": True,
                }
            },
        )
    except ScanImportError:
        raise
    except Exception as exc:
        raise ScanImportError(f"Lecture OpenAI impossible: {exc}") from exc
    finally:
        if uploaded is not None:
            try:
                client.files.delete(uploaded.id)
            except Exception:
                pass

    raw_json = (getattr(response, "output_text", None) or "").strip()
    if not raw_json:
        raise ScanImportError("La reponse OpenAI est vide.")

    try:
        payload = json.loads(raw_json)
    except Exception as exc:
        raise ScanImportError("La reponse OpenAI n'est pas un JSON exploitable.") from exc

    rows = payload.get("rows") or []
    cleaned_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        full_name = str(row.get("full_name") or "").strip()
        classe = str(row.get("classe") or "").strip()
        if not full_name and not classe:
            continue

        confidence_raw = row.get("confidence", 0)
        try:
            confidence = max(0.0, min(1.0, float(confidence_raw)))
        except Exception:
            confidence = 0.0

        issues = row.get("issues") or []
        if not isinstance(issues, list):
            issues = [str(issues)]

        cleaned_rows.append(
            {
                "full_name": full_name,
                "classe": classe,
                "activite": _optional_note(row.get("activite")),
                "devoir": _optional_note(row.get("devoir")),
                "compo": _optional_note(row.get("compo")),
                "remarques": str(row.get("remarques") or "").strip(),
                "confidence": confidence,
                "issues": [str(item).strip() for item in issues if str(item).strip()],
            }
        )

    if not cleaned_rows:
        raise ScanImportError("Aucune ligne exploitable n'a ete detectee dans le PDF scanne.")

    return cleaned_rows


def build_student_catalog(student_rows):
    exact = {}
    normalized = {}
    by_name = {}

    for row in student_rows:
        name = str(row["nom_complet"] or "").strip()
        classe = str(row["niveau"] or "").strip()
        record = {
            "id": int(row["id"]),
            "nom_complet": name,
            "niveau": classe,
            "label": f"{name} - {classe}" if classe else name,
        }
        exact.setdefault((name.casefold(), classe.casefold()), []).append(record)
        normalized.setdefault(
            (normalize_lookup_text(name), normalize_lookup_text(classe)), []
        ).append(record)
        by_name.setdefault(normalize_lookup_text(name), []).append(record)

    return {
        "exact": exact,
        "normalized": normalized,
        "by_name": by_name,
    }


def match_scanned_row(full_name, classe, catalog):
    name = str(full_name or "").strip()
    class_name = str(classe or "").strip()
    if not name:
        return {
            "student_id": None,
            "matched_label": "",
            "status": "warning",
            "reason": "Nom manquant",
        }

    exact_matches = catalog["exact"].get((name.casefold(), class_name.casefold()), [])
    if len(exact_matches) == 1:
        match = exact_matches[0]
        return {
            "student_id": match["id"],
            "matched_label": match["label"],
            "status": "success",
            "reason": "Correspondance exacte",
        }

    normalized_matches = catalog["normalized"].get(
        (normalize_lookup_text(name), normalize_lookup_text(class_name)), []
    )
    if len(normalized_matches) == 1:
        match = normalized_matches[0]
        return {
            "student_id": match["id"],
            "matched_label": match["label"],
            "status": "success",
            "reason": "Correspondance normalisee",
        }

    name_matches = catalog["by_name"].get(normalize_lookup_text(name), [])
    if len(name_matches) == 1:
        match = name_matches[0]
        return {
            "student_id": match["id"],
            "matched_label": match["label"],
            "status": "warning",
            "reason": "Nom trouve sans verifier la classe",
        }
    if len(name_matches) > 1:
        return {
            "student_id": None,
            "matched_label": "",
            "status": "warning",
            "reason": "Plusieurs eleves portent ce nom",
        }
    return {
        "student_id": None,
        "matched_label": "",
        "status": "danger",
        "reason": "Aucun eleve correspondant",
    }

