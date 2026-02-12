import base64
import hashlib
import json
import sys
import os
import argparse
from datetime import datetime

# Essaie de recuperer le secret depuis la config, sinon fallback
try:
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from core.config import SECRET_LICENCE as SECRET_KEY
except ImportError:
    SECRET_KEY = "ALGERIE_ECOLE_PRO_2026_SUPER_SECRET"

def generer_cle(date_expiration):
    """
    Génère une clé de licence valide jusqu'à la date donnée (AAAA-MM-JJ).
    """
    # 1. Données
    data = f"{date_expiration}|{SECRET_KEY}"
    
    # 2. Signature
    signature = hashlib.sha256(data.encode()).hexdigest()[:16].upper()
    
    # 3. Contenu
    contenu = json.dumps({
        "date": date_expiration, 
        "sig": signature
    })
    
    # 4. Encodage (Préfixe EDUPRO)
    cle_base = base64.b64encode(contenu.encode()).decode()
    cle_finale = f"EDUPRO-{cle_base}"
    
    return cle_finale

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generateur de licence EduMaster Pro")
    parser.add_argument("--date", help="Date d'expiration au format AAAA-MM-JJ")
    args = parser.parse_args()

    print("\n========================================")
    print("   GENERATEUR DE LICENCE EDUMASTER PRO")
    print("========================================")

    date_str = args.date
    if not date_str:
        today = datetime.now()
        next_year = today.year + 1
        default_date = f"{next_year}-07-31"
        try:
            input_date = input(f"Date d'expiration (Defaut: {default_date}) : ").strip()
            date_str = input_date if input_date else default_date
        except KeyboardInterrupt:
            print("\nAnnule.")
            sys.exit(0)

    try:
        # Validation simple du format
        datetime.strptime(date_str, "%Y-%m-%d")
        
        cle = generer_cle(date_str)
        print("\n[SUCCES] Clé générée pour le : " + date_str)
        print("----------------------------------------------------------------")
        print(cle)
        print("----------------------------------------------------------------")
        
        # Sauvegarde optionnelle dans un fichier
        with open("licence_generee.txt", "w") as f:
            f.write(f"Date: {date_str}\nKey: {cle}\n")
        print("(Clé sauvegardée dans 'licence_generee.txt')")
        
    except ValueError:
        print("\n[ERREUR] Format de date invalide. Utilisez AAAA-MM-JJ (ex: 2025-12-31)")
    except Exception as e:
        print(f"\n[ERREUR] {e}")

    if not args.date:
        input("\nAppuyez sur Entree pour quitter...")