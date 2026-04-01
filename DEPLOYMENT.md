# 🚀 Deployment-Anleitung: Thailand Reise Konfigurator

## Ziel
Deine Streamlit-App soll unter einer öffentlichen URL erreichbar sein, ohne dass Nutzer etwas installieren müssen.

---

## Option 1: Streamlit Cloud (EMPFOHLEN ⭐⭐⭐⭐⭐)

**Kosten:** Kostenlos  
**Aufwand:** 5 Minuten  
**Ergebnis:** App unter `https://xxx-streamlit.app` online

### Schritt 1: GitHub Account & Repo

1. Falls nicht vorhanden: GitHub-Account erstellen → https://github.com/signup
2. GitHub Desktop installieren (optional, aber einfacher): https://desktop.github.com/

### Schritt 2: Dein Code auf GitHub pushen

**Terminal öffnen und folgende Befehle nacheinander eingeben:**

```bash
# Zum Thailand-Verzeichnis gehen
cd /Users/robinhans/PycharmProjects/Thailand

# Git initialisieren
git init
git add .
git commit -m "Initial commit: Thailand Reise Auto-Konfigurator"
```

**Auf GitHub ein neues Repo erstellen:**
- Gehe zu https://github.com/new
- Name: `thailand-reise-konfigurator`
- Beschreibung (optional): `Interaktive Web-App zur Planung von Thailand-Gruppenreisen`
- Public (damit es über Streamlit Cloud deployt werden kann)
- Click "Create repository"

**Zurück im Terminal: Remote hinzufügen & pushen**

```bash
# Ersetze DEIN_USERNAME mit deinem GitHub-Benutzernamen
git remote add origin https://github.com/DEIN_USERNAME/thailand-reise-konfigurator.git
git branch -M main
git push -u origin main
```

**Fertig!** Dein Code ist jetzt auf GitHub: https://github.com/DEIN_USERNAME/thailand-reise-konfigurator

---

### Schritt 3: Streamlit Cloud Setup

1. Gehe zu https://streamlit.io/cloud
2. Klick auf "Sign in" → "Sign in with GitHub"
   - GitHub-Zugriff zulassen
3. Nach dem Login: Klick auf "New app"
4. Fülle die Felder aus:
   - **Repository:** `DEIN_USERNAME/thailand-reise-konfigurator`
   - **Branch:** `main`
   - **Main file path:** `app.py`
5. Klick "Deploy"

**Das war's! 🎉**

Streamlit deployts deine App automatisch. In 1-2 Minuten ist sie live unter einer URL wie:
```
https://thailand-reise-konfigurator-xxxxx.streamlit.app
```

---

### Schritt 4: App-Link teilen

Kopiere die URL von Streamlit Cloud und teile sie mit deinen Freunden:
```
https://thailand-reise-konfigurator-xxxxx.streamlit.app
```

Sie können direkt darauf zugreifen — **keine Installation nötig!**

---

## Option 2: Docker + Heroku (Alternative)

Wenn du mehr Kontrolle willst, kannst du die App auch auf Heroku deployen.

### Voraussetzungen:
- Docker installiert: https://www.docker.com/products/docker-desktop
- Heroku-Account: https://www.heroku.com

### Dockerfile erstellen

Speichere diese Datei als `Dockerfile` im Thailand-Verzeichnis:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

### Deployen

```bash
# Heroku Login
heroku login

# App erstellen
heroku create thailand-reise-konfigurator

# Deployen
git push heroku main

# App öffnen
heroku open
```

---

## Option 3: AWS/Google Cloud (Advanced)

Für größere Anwendungen mit mehr Benutzern — aber komplexer in der Einrichtung.

---

## Nach dem Deployment

### 1. Daten-Persistierung

CSV-Dateien werden auf Streamlit Cloud im Dateisystem der App gespeichert:
- `aktivitaeten_vorschlaege.csv` → Nutzervorschläge
- `traumreisen_speicherstaende.csv` → Gespeicherte Reisen
- `traumreisen_submissions.csv` → Finalisierte Reisen

**Achtung:** Bei jedem Neustart der App werden diese Dateien zurückgesetzt! Wenn du persistente Datenbank brauchst → siehe nächster Punkt.

### 2. (Optional) Persistente Datenbank

Für echte Produktivnutzung: **Supabase** (kostenlosen Tier) oder **Firebase**:

1. Supabase-Account: https://supabase.com
2. Neues Projekt erstellen
3. In `app.py` den CSV-Zugriff durch Supabase-API ersetzen

(Geben Sie Bescheid, wenn Sie das brauchen — mache ich gerne!)

---

## Updates machen

Wenn du Änderungen an `app.py` oder den CSVs machst:

```bash
cd /Users/robinhans/PycharmProjects/Thailand
git add .
git commit -m "Deine Änderung beschreiben"
git push origin main
```

Streamlit Cloud deployts die neue Version **automatisch** innerhalb von 1-2 Minuten!

---

## Troubleshooting

### App lädt nicht / Error beim Deploy

**Häufige Ursachen:**

1. `requirements.txt` nicht gepusht?
   ```bash
   git add requirements.txt
   git commit -m "Add requirements.txt"
   git push
   ```

2. Fehlende Dependencies?
   ```bash
   pip freeze > requirements.txt
   git add requirements.txt
   git commit -m "Update requirements.txt"
   git push
   ```

3. `app.py` hat Fehler?
   - Lokal testen: `streamlit run app.py`
   - Fehler anschauen & fixen
   - Pushen

### Daten gehen verloren nach Neustart

Das ist normal bei Streamlit Cloud — siehe "Nach dem Deployment" → "Persistente Datenbank".

---

## Kontakt & Support

- Streamlit-Docs: https://docs.streamlit.io
- Meine Kontakt-Info: [deine E-Mail]

Viel Erfolg! 🚀

