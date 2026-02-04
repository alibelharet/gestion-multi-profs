import base64
import hashlib
import json

# --- VOTRE SECRET ---
SECRET_KEY = "ALGERIE_ECOLE_PRO_2026_SUPER_SECRET"

def generer_cle(date_expiration):
    """
    Génère une clé standard. Le verrouillage se fera sur le PC du client.
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
    print("\n--- GÉNÉRATEUR DE LICENCE (AUTO-LOCK) ---")
    date = input("Date d'expiration (AAAA-MM-JJ) : ")
    
    try:
        cle = generer_cle(date)
        print("\n✅ CLÉ À DONNER AU CLIENT :")
        print("------------------------------------------------")
        print(cle)
        print("------------------------------------------------")
    except Exception as e:
        print(f"Erreur : {e}")