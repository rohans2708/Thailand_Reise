# Thailand Reise Auto-Konfigurator

Streamlit-App zur Thailand-Gruppenreise mit bildbasiertem Raster-Konfigurator.

## Flow (wie Auto-Konfigurator)

1. Flug nach Bangkok
2. Hotel in Bangkok (Bild anklicken)
3. Aktivitaeten in Bangkok
4. Ferienwohnung auf der Insel (Ko Samui oder Phuket, Bild anklicken)
5. Automatische Flugsuche Bangkok -> Insel anhand `transporte.csv`
6. Aktivitaeten auf der gewaehlten Insel

Die App rechnet Kosten inkl. Airport-Transfer und zeigt im Konfigurator unten nur den Preis pro Person.

Endberechnung: Alle Positionen werden als pro-Kopf-Werte behandelt. Nur die Ferienwohnung wird anteilig durch die Anzahl der Reisenden geteilt.

Zusatz: Aktivitaeten zeigen ebenfalls Info-Boxen mit Link (falls vorhanden, sonst Beispiel-Suchlink).

## Seiten in der App

- `Konfigurator`
- `Uebersicht Kosten`
- `Uebersicht Auswahl`
- `Uebersicht Notizen`

## 🚀 Schnellstart lokal

### 1. Dependencies installieren

```bash
pip install -r requirements.txt
```

### 2. App starten

```bash
streamlit run app.py
```

Die App läuft dann unter `http://localhost:8501`.

---

## 🚀 Deployment auf Streamlit Cloud (für externe Nutzer)

### So geht's in 3 Schritten:

#### 1. GitHub Repo erstellen & pushen

```bash
cd /Users/robinhans/PycharmProjects/Thailand

# Falls noch nicht initialisiert:
git init
git add .
git commit -m "Initial commit: Thailand Reise Konfigurator"

# Repo auf GitHub erstellen (https://github.com/new)
# Dann lokalen Repo mit GitHub verbinden:
git remote add origin https://github.com/DEIN_USERNAME/thailand-reise-konfigurator.git
git branch -M main
git push -u origin main
```

#### 2. Auf Streamlit Cloud deployen

- Gehe zu https://streamlit.io/cloud
- Melde dich mit deinem GitHub-Account an
- Klicke "**New app**"
- Wähle dein Repo: `thailand-reise-konfigurator`
- Branch: `main`
- File path: `app.py`
- Klicke "**Deploy**"

#### 3. Nutzer einladen

- Deine App ist jetzt unter einer URL wie `https://xxx-streamlit.app` erreichbar
- Teile diesen Link mit anderen — sie können sofort zugreifen, ohne Software zu installieren!

---

## Datenmodell

- `unterkuenfte.csv`: Hotels & Ferienwohnungen (Name, Kosten/Nacht, Standort, Link, Bild, Details, AirportTransfer, TransferKosten, FruehstueckInklusive)
- `aktivitaeten.csv`: Aktivitäten (Name, Kosten/Person, Standort, Link, Bild, Details)
- `transporte.csv`: Flüge & Transfers (Name, Kosten, Typ: Flug/Fähre)
- `aktivitaeten_vorschlaege.csv`: Von Nutzern vorgeschlagene Aktivitäten (automatisch erstellt, Status: pending/approved/rejected)
- `traumreisen_speicherstaende.csv`: Gespeicherte Reisen pro Nutzer mit vollständiger Konfiguration
- `traumreisen_submissions.csv`: Finalisierte Traumreisen

---

## Nutzerrollen

- **Alle Nutzer:**
  - Reise konfigurieren (Flüge, Unterkünfte, Aktivitäten wählen)
  - Eigene Aktivitäten vorschlagen
  - Auswahl speichern & später laden
  - Kostenübersicht ansehen

- **Robin (Admin):**
  - Alle Standard-Features
  - **Zusätzlich:** Admin-Panel zum Genehmigen/Ablehnen von Aktivitätsvorschlägen
  - Statistik-Seite: Überblick aller Reisen, beliebte Destinationen, Kostenverteilung

## Projektstruktur

```
Thailand/
├── app.py
├── requirements.txt
├── unterkuenfte.csv
├── aktivitaeten.csv
├── transporte.csv
└── README.md
```

## Datenstruktur

### `unterkuenfte.csv`
- Spalten: `Name`, `Kosten`, `Standort`, `Link`
- `Standort` sollte `Bangkok`, `Ko Samui` oder `Phuket` sein.
- Optional: `Bild` (URL). Wenn leer/fehlend, nutzt die App automatische Platzhalterbilder.
- Optional fuer Notizen/Transfer: `Details`, `Vorteile`, `Nachteile`, `AirportTransfer`, `TransferKosten`
- Optional: `FruehstueckInklusive` (`Ja`/`Nein`) fuer Verpflegungsabzug

### `aktivitaeten.csv`
- Spalten: `Name`, `Kosten`, `Standort`, `Link`
- Optional: `Bild`, `Details`

### `aktivitaeten.csv`
- Spalten: `Name`, `Kosten`, `Standort`, `Link`
- `Standort` sollte `Bangkok`, `Ko Samui` oder `Phuket` sein.
- Optional: `Bild` (URL). Wenn leer/fehlend, nutzt die App automatische Platzhalterbilder.

### `transporte.csv`
- Spalten: `Name`, `Kosten`, `Typ`
- Fuer die Auto-Zuordnung braucht es Flugnamen mit Bangkok + Ziel, z. B.
  - `Flug Bangkok - Phuket`
  - `Flug Bangkok - Ko Samui`

## Hinweise

- Falls CSV-Dateien fehlen, erstellt `app.py` Demo-Daten automatisch.
- Alte Standortwerte wie `Insel` werden unterstuetzt; diese Aktivitaeten werden bei der Insel-Auswahl mit angeboten.
- Aktivitaeten fuer `Ko Samui` und `Phuket` werden getrennt (individuell) gefuehrt.
- Wenn kein passender Inlandsflug gefunden wird, zeigt die App eine Warnung.
- Airport-Transfer bei Bangkok-Hotel und Ferienwohnung wird als Transportkosten mitgerechnet.
- In der Sidebar kannst du Schaetzungen fuer lokalen Transport und Verpflegung setzen.
- Wenn Unterkunft/Ferienwohnung `FruehstueckInklusive=Ja` hat, wird ein taeglicher Verpflegungsabzug beruecksichtigt.


