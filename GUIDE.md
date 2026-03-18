# Tennis Bot - Guide complet

## Architecture
- Backend Flask hébergé sur Render.com
- Raccourci iPhone (Shortcuts) déclenché via Siri
- Communication via requêtes HTTP simples

---

## 1. Déploiement sur Render

### Prérequis
- Compte GitHub (gratuit)
- Compte Render.com (gratuit)

### Étapes

1. Crée un repo GitHub nommé `tennis-bot`
2. Upload les 3 fichiers : `app.py`, `requirements.txt`, `Procfile`
3. Sur Render.com > New > Web Service > connecte ton repo GitHub
4. Paramètres Render :
   - **Environment** : Python 3
   - **Build Command** : `pip install -r requirements.txt`
   - **Start Command** : `gunicorn app:app`

5. Dans Render > Environment Variables, ajoute :
   - `TENNIS_LOGIN` = JECHAP
   - `TENNIS_PASSWORD` = ton_mot_de_passe
   - `TENNIS_PARTNER` = Aurelien LANGE

6. Note l'URL de ton service, ex: `https://tennis-bot-xxxx.onrender.com`

---

## 2. Raccourci iPhone (Shortcuts)

### Crée un nouveau raccourci avec ces étapes dans l'ordre :

**Étape 1 - Demander la date**
- Action : "Demander une entrée"
- Question : "Quelle date ? (ex: 20/03/2026 ou 'dans 3 jours')"
- Variable : `date_input`

**Étape 2 - Formater la date**
- Action : "Exécuter un script JavaScript" (ou utilise "Obtenir des détails de la date")
- Logique : si l'input contient "dans X jours", calculer la date correspondante
- Sinon utiliser la date telle quelle au format JJ/MM/AAAA

**Étape 3 - Appeler le backend (créneaux)**
- Action : "Obtenir le contenu d'une URL"
- URL : `https://tennis-bot-xxxx.onrender.com/creneaux?date=[date_formatee]`
- Méthode : GET

**Étape 4 - Parser la réponse**
- Action : "Obtenir la valeur du dictionnaire"
- Clé : `creneaux`

**Étape 5 - Choisir un créneau**
- Action : "Choisir dans la liste"
- Liste : les labels des créneaux (ex: "Court 3TB - 10h")

**Étape 6 - Confirmer**
- Action : "Afficher une alerte"
- Message : "Confirmer la réservation de [créneau choisi] ?"

**Étape 7 - Réserver**
- Action : "Obtenir le contenu d'une URL"
- URL : `https://tennis-bot-xxxx.onrender.com/reserver`
- Méthode : POST
- Corps JSON : `{"idres": "[idres du créneau choisi]"}`

**Étape 8 - Confirmer**
- Action : "Afficher une alerte" ou "Dire" via Siri
- Message : "Réservation confirmée !"

### Activation via Siri
- Nomme le raccourci : "Réserve un court"
- Dis à Siri : "Réserve un court"

---

## 3. Notes importantes

### Sécurité
- Ne jamais stocker le mot de passe dans le code
- Utiliser uniquement les variables d'environnement Render
- Changer le mot de passe ADSL Tennis dès que possible

### Limitations connues
- Le scraping dépend de la structure HTML du site ADSL Tennis
- Si le site change sa structure, le script devra être adapté
- Render free tier : le service "dort" après 15 min d'inactivité
  (premier appel peut prendre ~30 secondes pour se réveiller)

### Pour éviter le "sleep" de Render
- Utilise le plan payant (7$/mois) ou
- Configure un ping automatique toutes les 10 min via cron-job.org

---

## 4. Test

Une fois déployé, teste depuis ton navigateur :
`https://tennis-bot-xxxx.onrender.com/health`

Doit retourner : `{"status": "ok"}`

Puis teste les créneaux :
`https://tennis-bot-xxxx.onrender.com/creneaux?date=20/03/2026`
