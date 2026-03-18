import os
import re
import time
from datetime import datetime
from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

app = Flask(__name__)

CLUB_ID = "57920393"
LOGIN = os.environ.get("TENNIS_LOGIN", "JECHAP")
PASSWORD = os.environ.get("TENNIS_PASSWORD", "")
PARTNER_NAME = os.environ.get("TENNIS_PARTNER", "Aurelien LANGE")
PLANNING_URL = f"https://www.premier-service.fr/_start/index.php?club={CLUB_ID}"

JOURS_FR = {0:"Lundi",1:"Mardi",2:"Mercredi",3:"Jeudi",4:"Vendredi",5:"Samedi",6:"Dimanche"}

COURT_NAMES = {
    "1": "Court 1TB", "2": "Court 2TB", "3": "Court 3TB", "4": "Court 4TB",
    "5": "Court 5TB", "6": "Court 6TB", "7": "Court 7DUR", "8": "Court 8DUR",
}


def make_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.binary_location = os.environ.get("CHROME_BIN", "/usr/bin/google-chrome")
    service = Service(os.environ.get("CHROMEDRIVER_PATH", "/usr/bin/chromedriver"))
    return webdriver.Chrome(service=service, options=options)


def login(driver):
    driver.get(PLANNING_URL)
    wait = WebDriverWait(driver, 10)

    # Attendre le formulaire de login
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text']")))

    # Remplir identifiant
    inputs_text = driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
    inputs_pwd = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")

    for inp in inputs_text:
        if inp.is_displayed():
            inp.clear()
            inp.send_keys(LOGIN)
            break

    for inp in inputs_pwd:
        if inp.is_displayed():
            inp.clear()
            inp.send_keys(PASSWORD)
            break

    # Cliquer sur Entrer
    btns = driver.find_elements(By.CSS_SELECTOR, "button, input[type='submit']")
    for btn in btns:
        if btn.is_displayed() and ("entrer" in btn.text.lower() or "valider" in btn.text.lower() or "login" in btn.text.lower()):
            btn.click()
            break

    # Attendre le planning
    time.sleep(3)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "p.prc_visible")))
    return True


def navigate_to_date(driver, date_str):
    """Navigue vers une date en cliquant sur les flèches du planning."""
    today = datetime.now().strftime("%d/%m/%Y")
    if date_str == today:
        return

    target = datetime.strptime(date_str, "%d/%m/%Y")
    current = datetime.now()
    delta = (target - current).days

    wait = WebDriverWait(driver, 10)
    for _ in range(abs(delta)):
        if delta > 0:
            # Cliquer sur >> (suivant)
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(),'>>') or contains(@class,'suivant')]")))
        else:
            # Cliquer sur << (précédent)
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(),'<<') or contains(@class,'precedent')]")))
        btn.click()
        time.sleep(1)


def get_slots(driver):
    """Récupère les créneaux libres depuis le planning."""
    wait = WebDriverWait(driver, 10)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "p.prc_visible")))

    elements = driver.find_elements(By.CSS_SELECTOR, "p.prc_visible[ondblclick]")
    slots = []
    seen = set()

    for el in elements:
        slot_id = el.get_attribute("id")
        if not slot_id or slot_id in seen:
            continue

        parts = slot_id.split("_")
        if len(parts) < 3:
            continue

        heure_num = parts[0]
        minutes = parts[1]
        court = parts[2]

        # Heures pleines uniquement
        if minutes != "0":
            continue

        seen.add(slot_id)
        heure = f"{heure_num}h"
        court_label = COURT_NAMES.get(court, f"Court {court}")

        slots.append({
            "label": f"{court_label} - {heure}",
            "heure": heure,
            "court": court,
            "court_label": court_label,
            "slot_id": slot_id,
        })

    slots.sort(key=lambda x: (
        int(x["slot_id"].split("_")[0]),
        int(x["court"]) if x["court"].isdigit() else 99
    ))
    return slots


def reserve_slot(driver, slot_id):
    """Clique sur un créneau et valide avec Aurelien LANGE."""
    wait = WebDriverWait(driver, 10)

    # Double-cliquer sur le créneau via JS
    el = driver.find_element(By.ID, slot_id)
    driver.execute_script("arguments[0].dispatchEvent(new MouseEvent('dblclick', {bubbles: true}))", el)
    time.sleep(2)

    # Sélectionner le partenaire
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "select")))
    selects = driver.find_elements(By.CSS_SELECTOR, "select")
    for sel in selects:
        options = sel.find_elements(By.TAG_NAME, "option")
        for opt in options:
            if PARTNER_NAME.lower() in opt.text.lower():
                opt.click()
                time.sleep(2)
                break

    # Valider
    btns = driver.find_elements(By.CSS_SELECTOR, "button")
    for btn in btns:
        if "valider" in btn.text.lower():
            btn.click()
            time.sleep(2)
            break

    # Vérifier confirmation
    page_text = driver.find_element(By.TAG_NAME, "body").text
    if "erreur" in page_text.lower():
        return False, page_text[:200]
    return True, "Reservation confirmee"


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/creneaux")
def creneaux():
    date_str = request.args.get("date", datetime.now().strftime("%d/%m/%Y"))
    driver = None
    try:
        driver = make_driver()
        login(driver)
        navigate_to_date(driver, date_str)
        slots = get_slots(driver)
        return jsonify({"date": date_str, "creneaux": slots})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if driver:
            driver.quit()


@app.route("/reserver", methods=["POST"])
def reserver():
    data = request.json
    slot_id = data.get("slot_id")
    date_str = data.get("date", datetime.now().strftime("%d/%m/%Y"))
    if not slot_id:
        return jsonify({"error": "slot_id manquant"}), 400

    driver = None
    try:
        driver = make_driver()
        login(driver)
        navigate_to_date(driver, date_str)
        success, message = reserve_slot(driver, slot_id)
        if success:
            return jsonify({"status": "ok", "message": message})
        else:
            return jsonify({"error": message}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
