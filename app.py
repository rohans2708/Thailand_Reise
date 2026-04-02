"""Thailand Reiseplaner als bildbasierter Auto-Konfigurator."""

from datetime import datetime
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import quote
from uuid import uuid4
import os

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Thailand Auto-Konfigurator", page_icon="TH", layout="wide")

try:
    from streamlit_cookies_manager import EncryptedCookieManager
    COOKIE_LIB_AVAILABLE = True
except ImportError:
    EncryptedCookieManager = None
    COOKIE_LIB_AVAILABLE = False

# Supabase optional
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    create_client = None
    Client = object
    SUPABASE_AVAILABLE = False

@st.cache_resource
def get_supabase_client() -> Client | None:
    """Erstellt einen Supabase-Client mit Secrets aus Streamlit."""
    if not SUPABASE_AVAILABLE:
        return None
    
    url = st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_ANON_KEY")
    
    if not url or not key:
        # Im lokalen Modus ohne Secrets: auch None akzeptabel (Fallback auf CSV)
        return None
    
    try:
        return create_client(url, key)
    except Exception as e:
        st.warning(f"Supabase-Verbindung fehlgeschlagen: {e}")
        return None


def allow_local_csv_seeding() -> bool:
    """Erlaubt CSV-Seeding nur, wenn es explizit lokal aktiviert wurde."""
    value = st.secrets.get("LOCAL_CSV_SEEDING", False)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def should_seed_csvs_for_user(user_name: str) -> bool:
    """CSV-Seeding nur für Robin und nur lokal."""
    return allow_local_csv_seeding() and str(user_name).strip().lower() == "robin"

BASE_DIR = Path(__file__).parent
CSV_UNTERKUENFTE = BASE_DIR / "unterkuenfte.csv"
CSV_AKTIVITAETEN = BASE_DIR / "aktivitaeten.csv"
CSV_TRANSPORTE = BASE_DIR / "transporte.csv"
CSV_SUBMISSIONS = BASE_DIR / "traumreisen_submissions.csv"
CSV_USER_SAVES = BASE_DIR / "traumreisen_speicherstaende.csv"
CSV_ACTIVITY_SUGGESTIONS = BASE_DIR / "aktivitaeten_vorschlaege.csv"

COOKIE_NAME = "thailand_trip_state"
PERSIST_KEYS = [
    "user_name",
    "sel_flight",
    "sel_bkk_hotel",
    "sel_island_home",
    "sel_bkk_act",
    "sel_island_act",
    "days_bangkok",
    "days_island",
    "local_transport_per_day_pp",
    "food_per_day_pp",
    "breakfast_discount_per_day_pp",
    "num_travelers",
]


def get_cookie_manager():
    if not COOKIE_LIB_AVAILABLE:
        return None
    if "cookie_manager" not in st.session_state:
        st.session_state["cookie_manager"] = EncryptedCookieManager(
            prefix="thailand_app/",
            password="thailand-streamlit-cookie-key",
        )
    return st.session_state["cookie_manager"]


def load_persisted_state() -> None:
    if st.session_state.get("_persist_loaded"):
        return

    payload = None
    cookies = get_cookie_manager()
    if cookies is not None and cookies.ready():
        raw = cookies.get(COOKIE_NAME)
        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = None

    payload = normalize_state_payload(payload)
    if payload:
        for key in PERSIST_KEYS:
            if key in payload and key not in st.session_state:
                st.session_state[key] = payload[key]

    st.session_state["_persist_loaded"] = True


def save_persisted_state() -> None:
    state = normalize_state_payload({key: st.session_state.get(key) for key in PERSIST_KEYS})
    # user_name bleibt als String erhalten
    state["user_name"] = st.session_state.get("user_name")
    cookies = get_cookie_manager()
    if cookies is not None and cookies.ready():
        cookies[COOKIE_NAME] = json.dumps(state)
        cookies.save()


def append_submission(record: dict[str, object]) -> None:
    submission_df = pd.DataFrame([record])
    if CSV_SUBMISSIONS.exists():
        existing = pd.read_csv(CSV_SUBMISSIONS)
        existing = pd.concat([existing, submission_df], ignore_index=True)
        existing.to_csv(CSV_SUBMISSIONS, index=False)
    else:
        submission_df.to_csv(CSV_SUBMISSIONS, index=False)


def save_user_snapshot(record: dict[str, object]) -> None:
    """Speichert Nutzer-Snapshot zu Supabase (primary storage)."""
    client = get_supabase_client()
    if not client:
        st.warning("⚠️ Supabase nicht verbunden - Snapshot nicht gespeichert")
        return
    
    # Konvertiere Record für Supabase
    user_name = str(record.get("Name", "")).strip()
    supabase_record = {
        "user_name": user_name,
        "created_at": record.get("Zeitstempel"),
        "state_json": record.get("StateJson"),
        "num_travelers": int(record.get("Personen", 1)),
        "days_bangkok": int(record.get("TageBangkok", 0)),
        "days_island": int(record.get("TageInsel", 0)),
        "intl_flight": str(record.get("FlugInternational", "")).strip(),
        "bkk_hotel": str(record.get("BangkokHotel", "")).strip(),
        "island_accommodation": str(record.get("InselUnterkunft", "")).strip(),
        "island_destination": str(record.get("InselZiel", "")).strip(),
        "activities_bangkok": str(record.get("AktivitätenBangkok", "")).strip(),
        "activities_island": str(record.get("AktivitätenInsel", "")).strip(),
        "cost_flights": float(record.get("KostenFlügePP", 0)),
        "cost_transport": float(record.get("KostenTransportSonstPP", 0)),
        "cost_hotel": float(record.get("KostenHotelBangkokPP", 0)),
        "cost_island": float(record.get("KostenInselUnterkunftPP", 0)),
        "cost_activities": float(record.get("KostenAktivitätenPP", 0)),
        "cost_food": float(record.get("KostenVerpflegungPP", 0)),
        "total_per_person": float(record.get("PreisProPerson", 0)),
    }
    
    try:
        # Prüfe ob bereits vorhanden (upsert)
        response = client.table("saved_travels").select("id").eq("user_name", user_name).execute()
        if response.data:
            # Update existing
            client.table("saved_travels").update(supabase_record).eq("user_name", user_name).execute()
        else:
            # Insert new
            client.table("saved_travels").insert(supabase_record).execute()
    except Exception as e:
        st.warning(f"⚠️ Snapshot-Fehler: {e}")


def load_user_snapshot(user_name: str) -> dict[str, object] | None:
    """Lädt Nutzer-Snapshot aus Supabase (primary storage)."""
    if not str(user_name).strip():
        return None
    
    client = get_supabase_client()
    if not client:
        st.warning("⚠️ Supabase nicht verbunden")
        return None
    
    try:
        response = client.table("saved_travels").select("*").eq("user_name", user_name.strip()).execute()
        if response.data:
            row = response.data[0]  # Nimm den neuesten (sollte nur 1 sein wegen UNIQUE)
            if row.get("state_json"):
                try:
                    payload = json.loads(row["state_json"])
                    return normalize_state_payload(payload)
                except json.JSONDecodeError:
                    return None
    except Exception as e:
        st.warning(f"⚠️ Fehler beim Laden: {e}")
    
    return None


def get_initial_value(key: str, default: object, snapshot: dict[str, object] | None) -> object:
    """Gibt Wert aus Snapshot, dann Session State, dann Default zurück."""
    if snapshot and key in snapshot:
        return snapshot[key]
    if key in st.session_state:
        return st.session_state[key]
    return default


def _to_optional_int(value: object) -> int | None:
    """Konvertiert gemischte Werte sicher zu int oder None."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan"}:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _to_int_list(value: object) -> list[int]:
    """Konvertiert gemischte Werte (z. B. JSON-String, NaN, Einzelwert) sicher zu int-Liste."""
    if value is None:
        return []
    if isinstance(value, float) and pd.isna(value):
        return []

    items: list[object]
    if isinstance(value, (list, tuple, set)):
        items = list(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"none", "nan"}:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
                items = list(parsed) if isinstance(parsed, list) else [parsed]
            except json.JSONDecodeError:
                items = [part.strip() for part in text.split(",") if part.strip()]
        else:
            items = [part.strip() for part in text.split(",") if part.strip()]
    else:
        items = [value]

    out: list[int] = []
    for item in items:
        val = _to_optional_int(item)
        if val is not None:
            out.append(val)
    return out


def normalize_state_payload(payload: dict[str, object] | None) -> dict[str, object]:
    """Bereinigt gespeicherte Zustände aus CSV/Cookies robust auf erwartete Typen."""
    if not isinstance(payload, dict):
        return {}

    cleaned = dict(payload)
    cleaned["sel_flight"] = _to_optional_int(cleaned.get("sel_flight"))
    cleaned["sel_bkk_hotel"] = _to_optional_int(cleaned.get("sel_bkk_hotel"))
    cleaned["sel_island_home"] = _to_optional_int(cleaned.get("sel_island_home"))
    cleaned["sel_bkk_act"] = _to_int_list(cleaned.get("sel_bkk_act"))
    cleaned["sel_island_act"] = _to_int_list(cleaned.get("sel_island_act"))
    return cleaned


def _empty_suggestions_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "id",
            "created_at",
            "proposed_by",
            "status",
            "reviewed_by",
            "reviewed_at",
            "name",
            "cost",
            "location",
            "link",
            "image_url",
            "details",
        ]
    )


def _normalize_suggestions_df_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalisiert verschiedene Suggestion-Spaltennamen auf snake_case."""
    if df.empty:
        return _empty_suggestions_df()

    mapped = df.copy()
    rename_map = {
        "SuggestionId": "id",
        "Zeitstempel": "created_at",
        "ProposedBy": "proposed_by",
        "Status": "status",
        "ReviewedBy": "reviewed_by",
        "ReviewedAt": "reviewed_at",
        "Name": "name",
        "Kosten": "cost",
        "Standort": "location",
        "Link": "link",
        "Bild": "image_url",
        "Details": "details",
    }
    mapped = mapped.rename(columns=rename_map)

    for col in _empty_suggestions_df().columns:
        if col not in mapped.columns:
            mapped[col] = ""

    mapped["id"] = mapped["id"].astype(str).str.strip()
    mapped["status"] = mapped["status"].astype(str).str.strip().str.lower().replace({"": "pending"})
    return mapped[_empty_suggestions_df().columns]


def load_activity_suggestions() -> pd.DataFrame:
    """Lädt Activity Suggestions aus Supabase (primary)."""
    client = get_supabase_client()

    if client:
        try:
            response = client.table("activity_suggestions").select("*").execute()
            if response.data:
                return _normalize_suggestions_df_columns(pd.DataFrame(response.data))
        except Exception as e:
            st.info(f"ℹ️ Supabase-Suggestions nicht lesbar: {str(e)[:100]}")
    
    return _empty_suggestions_df()


def _seed_activity_suggestions_to_supabase(df: pd.DataFrame) -> None:
    """Schreibt CSV-Aktivitätsvorschläge zu Supabase (einmalig)."""
    client = get_supabase_client()
    if not client or df.empty:
        return
    
    try:
        existing_rows = client.table("activity_suggestions").select("id").execute().data or []
        existing_ids = {str(r.get("id", "")).strip() for r in existing_rows}

        inserts: list[dict[str, object]] = []
        for _, row in df.iterrows():
            sid = str(row.get("SuggestionId", "")).strip()
            if not sid:
                sid = str(uuid4())
            if sid in existing_ids:
                continue

            inserts.append(
                {
                    "id": sid,
                    "created_at": str(row.get("Zeitstempel", datetime.now().isoformat())),
                    "proposed_by": str(row.get("ProposedBy", "migration")).strip(),
                    "status": str(row.get("Status", "pending")).strip().lower() or "pending",
                    "reviewed_by": str(row.get("ReviewedBy", "")).strip(),
                    "reviewed_at": str(row.get("ReviewedAt", "")).strip() or None,
                    "name": str(row.get("Name", "")).strip(),
                    "cost": float(row.get("Kosten", 0) or 0),
                    "location": str(row.get("Standort", "")).strip(),
                    "link": str(row.get("Link", "")).strip(),
                    "image_url": str(row.get("Bild", "")).strip(),
                    "details": str(row.get("Details", "")).strip(),
                }
            )
            existing_ids.add(sid)

        if inserts:
            client.table("activity_suggestions").insert(inserts).execute()
    except Exception as e:
        st.warning(f"CSV-zu-Supabase Seeding fehlgeschlagen: {e}")


def list_open_suggestions_for_user(user_name: str) -> pd.DataFrame:
    """Listet offene Vorschläge des Nutzers aus Supabase auf."""
    df = load_activity_suggestions()
    if df.empty:
        return df
    
    # Spalten sind jetzt snake_case aus Supabase
    try:
        mask = (df["proposed_by"].astype(str).str.lower() == str(user_name).strip().lower()) & (df["status"].astype(str).str.lower() == "pending")
        return df[mask].copy()
    except KeyError:
        # Falls Spalten nicht existieren
        return pd.DataFrame()


def list_pending_suggestions() -> pd.DataFrame:
    """Listet alle offenen (pending) Suggestions aus Supabase auf."""
    df = load_activity_suggestions()
    if df.empty:
        return df
    
    try:
        return df[df["status"].astype(str).str.lower() == "pending"].copy()
    except KeyError:
        return pd.DataFrame()


def submit_activity_suggestion(user_name: str, payload: dict[str, object]) -> None:
    """Speichert Activity Suggestion zu Supabase (primary storage)."""
    client = get_supabase_client()
    if not client:
        st.error("❌ Supabase nicht verbunden. Bitte Secrets prüfen.")
        return
    
    row = {
        "id": str(uuid4()),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "proposed_by": str(user_name).strip(),
        "status": "pending",
        "reviewed_by": "",
        "reviewed_at": None,
        "name": str(payload.get("Name", "Eigene Aktivität")).strip() or "Eigene Aktivitaet",
        "cost": float(payload.get("Kosten", 0) or 0),
        "location": str(payload.get("Standort", "Bangkok")).strip() or "Bangkok",
        "link": str(payload.get("Link", "")).strip(),
        "image_url": str(payload.get("Bild", "")).strip(),
        "details": str(payload.get("Details", "Keine Details angegeben")).strip() or "Keine Details angegeben",
    }
    
    try:
        client.table("activity_suggestions").insert(row).execute()
    except Exception as e:
        st.error(f"❌ Fehler beim Speichern: {e}")


def review_suggestion(suggestion_id: str, approved: bool, reviewer: str) -> bool:
    """Akzeptiert oder lehnt Suggestion ab (Supabase primary)."""
    client = get_supabase_client()
    if not client:
        st.error("❌ Supabase nicht verbunden.")
        return False
    
    try:
        # Update suggestion status
        update_data = {
            "status": "approved" if approved else "rejected",
            "reviewed_by": str(reviewer).strip(),
            "reviewed_at": datetime.now().isoformat(timespec="seconds"),
        }
        
        client.table("activity_suggestions").update(update_data).eq("id", suggestion_id).execute()
        
        # If approved: add to aktivitaeten catalog
        if approved:
            df = load_activity_suggestions()
            match = df[df["id"].astype(str) == str(suggestion_id)]
            if not match.empty:
                row = match.iloc[0]
                _append_activity_to_catalog(row.to_dict())
        
        return True
    except Exception as e:
        st.error(f"❌ Fehler beim Review: {e}")
        return False


def _append_activity_to_catalog(activity: dict[str, object]) -> bool:
    """Fügt eine genehmigte Aktivität in den Supabase-Katalog ein (duplikatsicher)."""
    client = get_supabase_client()
    if not client:
        return False

    # Unterstützt sowohl snake_case (Supabase) als auch Legacy-Spaltennamen.
    name = str(activity.get("name") or activity.get("Name") or "").strip()
    location = str(activity.get("location") or activity.get("Standort") or "").strip()
    cost = float(activity.get("cost") or activity.get("Kosten") or 0)
    link = str(activity.get("link") or activity.get("Link") or "").strip()

    if not name or not location:
        return False

    try:
        existing = client.table("aktivitaeten").select("id").eq("name", name).eq("location", location).eq("cost", cost).eq("link", link).execute()
        if existing.data:
            return True

        row = {
            "name": name,
            "cost": cost,
            "location": location,
            "link": link,
            "image_url": str(activity.get("image_url") or activity.get("Bild") or "").strip(),
            "details": str(activity.get("details") or activity.get("Details") or "").strip() or "Keine Details angegeben",
        }
        client.table("aktivitaeten").insert(row).execute()
        return True
    except Exception:
        return False


def add_unterkunft_to_supabase(payload: dict[str, object]) -> tuple[bool, str]:
    """Fügt eine Unterkunft in Supabase ein (duplikatsicher)."""
    client = get_supabase_client()
    if not client:
        return False, "Supabase nicht verbunden."

    name_raw = str(payload.get("name", "")).strip()
    location = str(payload.get("location", "")).strip()
    name = name_raw
    if name_raw and location:
        suffix = f"({location})"
        if not name_raw.endswith(suffix):
            name = f"{name_raw} {suffix}"

    cost = float(payload.get("cost", 0) or 0)
    link = str(payload.get("link", "")).strip()
    if not name or not location:
        return False, "Name und Standort sind Pflichtfelder."

    payload = dict(payload)
    payload["name"] = name

    try:
        existing = (
            client.table("unterkuenfte")
            .select("id")
            .eq("name", name)
            .eq("location", location)
            .eq("cost", cost)
            .eq("link", link)
            .execute()
        )
        if existing.data:
            return False, "Unterkunft existiert bereits."

        client.table("unterkuenfte").insert(payload).execute()
        return True, "Unterkunft hinzugefügt."
    except Exception as e:
        return False, f"Fehler: {e}"


def add_transport_to_supabase(payload: dict[str, object]) -> tuple[bool, str]:
    """Fügt einen Transport in Supabase ein (duplikatsicher)."""
    client = get_supabase_client()
    if not client:
        return False, "Supabase nicht verbunden."

    name = str(payload.get("name", "")).strip()
    transport_type = str(payload.get("type", "")).strip()
    cost = float(payload.get("cost", 0) or 0)
    if not name or not transport_type:
        return False, "Name und Typ sind Pflichtfelder."

    try:
        existing = (
            client.table("transporte")
            .select("id")
            .eq("name", name)
            .eq("type", transport_type)
            .eq("cost", cost)
            .execute()
        )
        if existing.data:
            return False, "Transport existiert bereits."

        client.table("transporte").insert(payload).execute()
        return True, "Transport hinzugefügt."
    except Exception as e:
        return False, f"Fehler: {e}"


def build_flight_transport_name(
    von: str,
    nach: str,
    flugzeit_hin: str,
    flugzeit_zurueck: str,
    zwischenstop_ort: str,
    sonstiges: str,
) -> str:
    """Baut den Transport-Namen fuer Flug-Eintraege konsistent zusammen."""
    return (
        f"Flug ({von} - {nach}); "
        f"Flugzeit hin: {flugzeit_hin}; "
        f"Flugzeit zurück: {flugzeit_zurueck}; "
        f"Zwischenstop Ort: {zwischenstop_ort}; "
        f"Sonstiges: {sonstiges}"
    )


def apply_snapshot_to_state(payload: dict[str, object] | None) -> None:
    """Übernimmt gespeicherte Werte in den Session-State (ohne user_name zu überschreiben)."""
    if not payload:
        return
    for key in PERSIST_KEYS:
        if key == "user_name":
            continue
        if key in payload:
            st.session_state[key] = payload[key]


def selected_names(df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    return " | ".join(df["Name"].astype(str).tolist())


def create_dummy_csv_files() -> None:
    """Bewusst deaktiviert: Es werden keine Default-/Demo-Daten mehr erzeugt."""
    return


def _read_clean_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [str(col).strip() for col in df.columns]
    return df


def _norm_seed_text(value: object) -> str:
    """Normalisiert Seed-Texte robust fuer Duplikat-Pruefung."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan"}:
        return ""
    return normalize_text(text)


def _norm_seed_float(value: object) -> float:
    """Normalisiert Seed-Floats robust fuer Duplikat-Pruefung."""
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _seed_unterkuenfte_to_supabase_from_csv(client: Client) -> None:
    if not CSV_UNTERKUENFTE.exists():
        return

    csv_df = ensure_columns(
        _read_clean_csv(CSV_UNTERKUENFTE),
        {
            "Link": "",
            "Bild": "",
            "Details": "",
            "Vorteile": "",
            "Nachteile": "",
            "AirportTransfer": "Selbst",
            "TransferKosten": 0,
            "FruehstueckInklusive": "Nein",
        },
    )

    try:
        existing_rows = client.table("unterkuenfte").select("name,location,cost,link").execute().data or []
        existing_keys = {
            (
                _norm_seed_text(r.get("name", "")),
                _norm_seed_text(r.get("location", "")),
                _norm_seed_float(r.get("cost", 0)),
                _norm_seed_text(r.get("link", "")),
            )
            for r in existing_rows
        }

        inserts: list[dict[str, object]] = []
        seen_csv_keys: set[tuple[str, str, float, str]] = set()
        for _, row in csv_df.iterrows():
            key = (
                _norm_seed_text(row.get("Name", "")),
                _norm_seed_text(row.get("Standort", "")),
                _norm_seed_float(row.get("Kosten", 0)),
                _norm_seed_text(row.get("Link", "")),
            )
            if key in existing_keys or key in seen_csv_keys:
                continue
            seen_csv_keys.add(key)
            existing_keys.add(key)

            inserts.append(
                {
                    "name": str(row.get("Name", "")).strip(),
                    "cost": float(row.get("Kosten", 0) or 0),
                    "location": str(row.get("Standort", "")).strip(),
                    "link": str(row.get("Link", "")).strip(),
                    "image_url": str(row.get("Bild", "")).strip(),
                    "details": str(row.get("Details", "")).strip(),
                    "advantages": str(row.get("Vorteile", "")).strip(),
                    "disadvantages": str(row.get("Nachteile", "")).strip(),
                    "airport_transfer": str(row.get("AirportTransfer", "Selbst")).strip() or "Selbst",
                    "transfer_cost": float(row.get("TransferKosten", 0) or 0),
                    "breakfast_included": str(row.get("FruehstueckInklusive", "Nein")).strip() or "Nein",
                }
            )

        if inserts:
            client.table("unterkuenfte").insert(inserts).execute()
    except Exception as e:
        st.warning(f"Seed Unterkuenfte fehlgeschlagen: {e}")


def _seed_transporte_to_supabase_from_csv(client: Client) -> None:
    if not CSV_TRANSPORTE.exists():
        return

    csv_df = _read_clean_csv(CSV_TRANSPORTE)
    try:
        existing_rows = client.table("transporte").select("name,type,cost").execute().data or []
        existing_keys = {
            (
                _norm_seed_text(r.get("name", "")),
                _norm_seed_text(r.get("type", "")),
                _norm_seed_float(r.get("cost", 0)),
            )
            for r in existing_rows
        }

        inserts: list[dict[str, object]] = []
        seen_csv_keys: set[tuple[str, str, float]] = set()
        for _, row in csv_df.iterrows():
            key = (
                _norm_seed_text(row.get("Name", "")),
                _norm_seed_text(row.get("Typ", "")),
                _norm_seed_float(row.get("Kosten", 0)),
            )
            if key in existing_keys or key in seen_csv_keys:
                continue
            seen_csv_keys.add(key)
            existing_keys.add(key)

            inserts.append(
                {
                    "name": str(row.get("Name", "")).strip(),
                    "cost": float(row.get("Kosten", 0) or 0),
                    "type": str(row.get("Typ", "")).strip(),
                }
            )

        if inserts:
            client.table("transporte").insert(inserts).execute()
    except Exception as e:
        st.warning(f"Seed Transporte fehlgeschlagen: {e}")


def _seed_aktivitaeten_to_supabase_from_csv(client: Client) -> None:
    if not CSV_AKTIVITAETEN.exists():
        return

    csv_df = ensure_columns(_read_clean_csv(CSV_AKTIVITAETEN), {"Link": "", "Bild": "", "Details": ""})
    try:
        existing_rows = client.table("aktivitaeten").select("name,location,cost,link").execute().data or []
        existing_keys = {
            (
                _norm_seed_text(r.get("name", "")),
                _norm_seed_text(r.get("location", "")),
                _norm_seed_float(r.get("cost", 0)),
                _norm_seed_text(r.get("link", "")),
            )
            for r in existing_rows
        }

        inserts: list[dict[str, object]] = []
        seen_csv_keys: set[tuple[str, str, float, str]] = set()

        for _, row in csv_df.iterrows():
            key = (
                _norm_seed_text(row.get("Name", "")),
                _norm_seed_text(row.get("Standort", "")),
                _norm_seed_float(row.get("Kosten", 0)),
                _norm_seed_text(row.get("Link", "")),
            )
            if key in existing_keys or key in seen_csv_keys:
                continue

            seen_csv_keys.add(key)
            existing_keys.add(key)

            inserts.append(
                {
                    "name": str(row.get("Name", "")).strip(),
                    "cost": float(row.get("Kosten", 0) or 0),
                    "location": str(row.get("Standort", "")).strip(),
                    "link": str(row.get("Link", "")).strip(),
                    "image_url": str(row.get("Bild", "")).strip(),
                    "details": str(row.get("Details", "")).strip(),
                }
            )

        if inserts:
            client.table("aktivitaeten").insert(inserts).execute()
    except Exception as e:
        st.warning(f"Seed Aktivitaeten fehlgeschlagen: {e}")


def _load_unterkuenfte_from_supabase(client: Client) -> pd.DataFrame:
    response = client.table("unterkuenfte").select("*").execute()
    rows = response.data or []
    if not rows:
        return pd.DataFrame(columns=["Name", "Kosten", "Standort", "Link", "Bild", "Details", "Vorteile", "Nachteile", "AirportTransfer", "TransferKosten", "FruehstueckInklusive"])

    mapped = pd.DataFrame(
        {
            "Name": [str(r.get("name", "")) for r in rows],
            "Kosten": [float(r.get("cost", 0) or 0) for r in rows],
            "Standort": [str(r.get("location", "")) for r in rows],
            "Link": [str(r.get("link", "")) for r in rows],
            "Bild": [str(r.get("image_url", "")) for r in rows],
            "Details": [str(r.get("details", "")) for r in rows],
            "Vorteile": [str(r.get("advantages", "")) for r in rows],
            "Nachteile": [str(r.get("disadvantages", "")) for r in rows],
            "AirportTransfer": [str(r.get("airport_transfer", "Selbst")) for r in rows],
            "TransferKosten": [float(r.get("transfer_cost", 0) or 0) for r in rows],
            "FruehstueckInklusive": [str(r.get("breakfast_included", "Nein")) for r in rows],
        }
    )
    return mapped


def _load_transporte_from_supabase(client: Client) -> pd.DataFrame:
    response = client.table("transporte").select("*").execute()
    rows = response.data or []
    if not rows:
        return pd.DataFrame(columns=["Name", "Kosten", "Typ"])

    return pd.DataFrame(
        {
            "Name": [str(r.get("name", "")) for r in rows],
            "Kosten": [float(r.get("cost", 0) or 0) for r in rows],
            "Typ": [str(r.get("type", "")) for r in rows],
        }
    )


def _load_aktivitaeten_from_supabase(client: Client) -> pd.DataFrame:
    response = client.table("aktivitaeten").select("*").execute()
    rows = response.data or []
    if not rows:
        return pd.DataFrame(columns=["Name", "Kosten", "Standort", "Link", "Bild", "Details"])

    return pd.DataFrame(
        {
            "Name": [str(r.get("name", "")) for r in rows],
            "Kosten": [float(r.get("cost", 0) or 0) for r in rows],
            "Standort": [str(r.get("location", "")) for r in rows],
            "Link": [str(r.get("link", "")) for r in rows],
            "Bild": [str(r.get("image_url", "")) for r in rows],
            "Details": [str(r.get("details", "")) for r in rows],
        }
    )


def seed_csv_data_to_supabase_for_robin() -> None:
    """Seedet CSVs in Supabase nur lokal und nur für Robin."""
    if not should_seed_csvs_for_user(str(st.session_state.get("user_name", ""))):
        return

    client = get_supabase_client()
    if client is None:
        return

    if CSV_ACTIVITY_SUGGESTIONS.exists():
        _seed_activity_suggestions_to_supabase(_read_clean_csv(CSV_ACTIVITY_SUGGESTIONS))
    _seed_unterkuenfte_to_supabase_from_csv(client)
    _seed_transporte_to_supabase_from_csv(client)
    _seed_aktivitaeten_to_supabase_from_csv(client)


def load_csv_files() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    def _read_clean(path: Path) -> pd.DataFrame:
        df = pd.read_csv(path)
        # Nutzer-CSV kann Spalten mit Leerzeichen enthalten (z. B. " Bild").
        df.columns = [str(col).strip() for col in df.columns]
        return df

    client = get_supabase_client()
    if client is None:
        st.error("Supabase nicht verfügbar. Bitte SUPABASE_URL und SUPABASE_ANON_KEY prüfen.")
        st.stop()

    # Katalogdaten: nur lesen, kein Seeding hier
    unterkuenfte_df = _load_unterkuenfte_from_supabase(client)
    transporte_df = _load_transporte_from_supabase(client)
    aktivitaeten_df = _load_aktivitaeten_from_supabase(client)
    return unterkuenfte_df, aktivitaeten_df, transporte_df


def ensure_columns(df: pd.DataFrame, defaults: dict[str, object]) -> pd.DataFrame:
    out = df.copy()
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default
    return out


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text.lower()).strip()


def normalize_location(raw_location: str, row_name: str) -> str:
    loc = normalize_text(raw_location)
    name = normalize_text(row_name)
    if "bangkok" in loc:
        return "Bangkok"
    if "samui" in loc:
        return "Ko Samui"
    if "phuket" in loc:
        return "Phuket"
    if "insel" in loc or "island" in loc:
        if "samui" in name:
            return "Ko Samui"
        if "phuket" in name:
            return "Phuket"
        return "Insel"
    if "samui" in name:
        return "Ko Samui"
    if "phuket" in name:
        return "Phuket"
    return "Bangkok"


def prepare_location_column(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized["StandortNorm"] = [
        normalize_location(loc, name) for loc, name in zip(df["Standort"], df["Name"], strict=False)
    ]
    return normalized


def format_currency(amount: float) -> str:
    return f"EUR {amount:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def build_default_image_url(name: str, prefix: str) -> str:
    slug = re.sub(r"[^a-z0-9-]", "-", normalize_text(name)).strip("-")
    return f"https://picsum.photos/seed/{quote(prefix + '-' + slug)}/640/360"


def attach_image_column(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    enriched = df.copy()
    urls: list[str] = []
    for _, row in enriched.iterrows():
        candidate = str(row.get("Bild", "")).strip()
        urls.append(candidate if candidate else build_default_image_url(str(row["Name"]), prefix))
    enriched["BildUrl"] = urls
    return enriched


def find_domestic_flight(transporte_df: pd.DataFrame, destination: str) -> pd.Series | None:
    flights = transporte_df[transporte_df["Typ"].astype(str).str.lower() == "flug"].copy()
    if flights.empty:
        return None
    if destination not in {"Phuket", "Ko Samui"}:
        return None
    flights.loc[:, "NameNorm"] = flights["Name"].map(normalize_text)
    dest_keys = ["phuket"] if destination == "Phuket" else ["ko samui", "koh samui", "samui"]
    matches = flights[
        flights["NameNorm"].str.contains("bangkok", na=False)
        & flights["NameNorm"].apply(lambda n: any(k in n for k in dest_keys))
    ]
    if matches.empty:
        return None
    return matches.sort_values("Kosten", ascending=True).iloc[0]


def resolve_island_destination(accommodation: pd.Series | None) -> str | None:
    """Leitet die Zielinsel robust aus Standort, Name und Link ab."""
    if accommodation is None:
        return None

    normalized_location = normalize_text(accommodation.get("StandortNorm", ""))
    if "phuket" in normalized_location:
        return "Phuket"
    if "samui" in normalized_location:
        return "Ko Samui"

    hints = normalize_text(f"{accommodation.get('Name', '')} {accommodation.get('Link', '')}")
    if "phuket" in hints:
        return "Phuket"
    if "samui" in hints or "koh samui" in hints or "ko samui" in hints:
        return "Ko Samui"
    return None


def is_island_accommodation(row: pd.Series) -> bool:
    """Erkennt Insel-Unterkuenfte robust auch bei inkonsistenten Standortfeldern."""
    loc = normalize_text(row.get("StandortNorm", ""))
    if loc in {"ko samui", "phuket", "insel"}:
        return True
    hints = normalize_text(f"{row.get('Standort', '')} {row.get('Name', '')} {row.get('Link', '')}")
    return any(token in hints for token in ["samui", "phuket", "island", "insel"])


def render_accommodation_info(row: pd.Series, expanded: bool = False) -> None:
    offered = str(row.get("AirportTransfer", "Selbst")).strip().lower() in {"angeboten", "ja", "yes"}
    transfer_mode = "Angeboten" if offered else "Selbst organisieren"
    transfer_cost = float(row.get("TransferKosten", 0) or 0)
    with st.expander("Infos anzeigen", expanded=expanded):
        st.write(f"**Kurzbeschreibung:** {str(row.get('Details', '')).strip() or 'Keine Angabe'}")
        st.write(f"**Vorteile:** {str(row.get('Vorteile', '')).strip() or 'Keine Angabe'}")
        st.write(f"**Nachteile:** {str(row.get('Nachteile', '')).strip() or 'Keine Angabe'}")
        breakfast = str(row.get("FruehstueckInklusive", "Nein")).strip().lower() in {"ja", "yes", "true", "1"}
        st.write(f"**Frühstück inklusive:** {'Ja' if breakfast else 'Nein'}")
        st.write(f"**Airport-Transfer:** {transfer_mode}")
        st.write(f"**Transferkosten:** {format_currency(transfer_cost)}")
        link = str(row.get("Link", "")).strip()
        if link:
            st.markdown(f"[Zum Anbieter]({link})")
        else:
            city = quote(str(row.get("StandortNorm", "Thailand")))
            st.markdown(f"[Beispiel auf Airbnb suchen](https://www.airbnb.com/s/{city}/homes)")


def render_activity_info(row: pd.Series, expanded: bool = False) -> None:
    with st.expander("Infos anzeigen", expanded=expanded):
        st.write(f"**Beschreibung:** {str(row.get('Details', '')).strip() or 'Keine Angabe'}")
        link = str(row.get("Link", "")).strip()
        if link:
            st.markdown(f"[Zur Aktivität]({link})")
        else:
            query = quote(f"{row.get('Name', '')} {row.get('StandortNorm', 'Thailand')}")
            st.markdown(f"[Beispiel-Link (Suche)](https://www.google.com/search?q={query})")


def image_select_grid(
    df: pd.DataFrame,
    scope: str,
    selected: list[int] | int | None,
    multiple: bool,
    subtitle: str,
    info_mode: str | None = None,
) -> None:
    st.caption(subtitle)
    cols_per_row = 3
    indices = df.index.tolist()
    for start in range(0, len(indices), cols_per_row):
        row_cols = st.columns(cols_per_row)
        for col, idx in zip(row_cols, indices[start : start + cols_per_row], strict=False):
            row = df.loc[idx]
            is_selected = idx in selected if isinstance(selected, list) else idx == selected
            border = "3px solid #16a34a" if is_selected else "1px solid #d1d5db"
            with col:
                st.markdown(
                    f'<img src="{row["BildUrl"]}" style="width:100%;height:180px;object-fit:cover;border-radius:10px;border:{border};"/>',
                    unsafe_allow_html=True,
                )
                st.markdown(f"**{row['Name']}**")
                st.write(f"{format_currency(float(row['Kosten']))}")
                if "StandortNorm" in row:
                    st.caption(f"Ort: {row['StandortNorm']}")
                if info_mode == "accommodation":
                    render_accommodation_info(row)
                if info_mode == "activity":
                    render_activity_info(row)
                if multiple:
                    btn_label = "Markierung entfernen" if is_selected else "Markieren"
                    if st.button(btn_label, key=f"btn_{scope}_{idx}", use_container_width=True):
                        state_key = f"sel_{scope}"
                        selected_set = set(st.session_state.get(state_key, []))
                        if idx in selected_set:
                            selected_set.remove(idx)
                        else:
                            selected_set.add(idx)
                        st.session_state[state_key] = sorted(selected_set)
                        # Bei manuellem rerun sonst keine Persistierung -> Fortschritt geht beim Reload verloren.
                        save_persisted_state()
                        st.rerun()
                else:
                    btn_label = "Ausgewählt" if is_selected else "Auswählen"
                    if st.button(btn_label, key=f"btn_{scope}_{idx}", use_container_width=True):
                        st.session_state[f"sel_{scope}"] = idx
                        save_persisted_state()
                        st.rerun()


def calculate_summary(
    intl_flight: pd.Series | None,
    domestic_flight: pd.Series | None,
    bkk_hotel: pd.Series | None,
    island_home: pd.Series | None,
    bkk_acts: pd.DataFrame,
    island_acts: pd.DataFrame,
    num_travelers: int,
    days_bangkok: int,
    days_island: int,
    local_transport_per_day_pp: float,
    food_per_day_pp: float,
    breakfast_discount_per_day_pp: float,
) -> tuple[float, list[dict[str, object]], float, float, float, float, float, float, float]:
    rows: list[dict[str, object]] = []
    costs_flights = 0.0
    costs_transport_other = 0.0
    costs_accommodation = 0.0
    costs_bkk_hotel = 0.0
    costs_island_home = 0.0
    costs_activities = 0.0
    costs_food = 0.0

    if intl_flight is not None:
        costs_flights += float(intl_flight["Kosten"])
        rows.append({"Kategorie": "Flug nach Bangkok", "Name": intl_flight["Name"], "Kosten": float(intl_flight["Kosten"])})

    if domestic_flight is not None:
        costs_flights += float(domestic_flight["Kosten"])
        rows.append({"Kategorie": "Inlandsflug", "Name": domestic_flight["Name"], "Kosten": float(domestic_flight["Kosten"])})

    # Endberechnung pro Person:
    # - Alle Positionen gelten als bereits pro Kopf
    # - Nur die Ferienwohnung wird anteilig durch die Personenzahl geteilt
    for accom, label in ((bkk_hotel, "Hotel Bangkok"), (island_home, "Ferienwohnung")):
        if accom is None:
            continue
        nightly_cost = float(accom["Kosten"])
        nights = max(0, days_bangkok if label == "Hotel Bangkok" else days_island)
        transfer_cost = float(accom.get("TransferKosten", 0) or 0)
        if label == "Ferienwohnung":
            total_home_cost = nightly_cost * float(nights)
            share_per_person = total_home_cost / float(num_travelers)
            costs_accommodation += share_per_person
            costs_island_home += share_per_person
            rows.append(
                {
                    "Kategorie": "Ferienwohnung (anteilig pro Person)",
                    "Name": f"{accom['Name']} ({nights} Nächte, gesamt {format_currency(total_home_cost)})",
                    "Kosten": share_per_person,
                }
            )
        else:
            hotel_cost_pp = nightly_cost * float(nights)
            costs_accommodation += hotel_cost_pp
            costs_bkk_hotel += hotel_cost_pp
            rows.append(
                {
                    "Kategorie": label,
                    "Name": f"{accom['Name']} ({nights} Nächte)",
                    "Kosten": hotel_cost_pp,
                }
            )

        costs_transport_other += transfer_cost
        rows.append(
            {
                "Kategorie": f"Airport-Transfer {label}",
                "Name": str(accom.get("AirportTransfer", "Selbst")),
                "Kosten": transfer_cost,
            }
        )

    for _, row in pd.concat([bkk_acts, island_acts]).iterrows():
        activity_cost = float(row["Kosten"])
        costs_activities += activity_cost
        rows.append({"Kategorie": "Aktivität", "Name": row["Name"], "Kosten": activity_cost})

    total_days = max(0, days_bangkok) + max(0, days_island)
    local_transport_total = float(local_transport_per_day_pp) * float(total_days)
    costs_transport_other += local_transport_total
    rows.append(
        {
            "Kategorie": "Transport vor Ort (Schätzung, pro Person)",
            "Name": f"{total_days} Tage",
            "Kosten": local_transport_total,
        }
    )

    food_gross = float(food_per_day_pp) * float(total_days)
    breakfast_days = 0
    if bkk_hotel is not None:
        bkk_breakfast = str(bkk_hotel.get("FruehstueckInklusive", "Nein")).strip().lower() in {"ja", "yes", "true", "1"}
        if bkk_breakfast:
            breakfast_days += max(0, days_bangkok)
    if island_home is not None:
        island_breakfast = str(island_home.get("FruehstueckInklusive", "Nein")).strip().lower() in {"ja", "yes", "true", "1"}
        if island_breakfast:
            breakfast_days += max(0, days_island)

    breakfast_discount = float(breakfast_discount_per_day_pp) * float(breakfast_days)
    breakfast_discount = min(food_gross, breakfast_discount)
    costs_food = max(0.0, food_gross - breakfast_discount)

    rows.append({"Kategorie": "Verpflegung (Schätzung, pro Person)", "Name": f"{total_days} Tage", "Kosten": food_gross})
    if breakfast_discount > 0:
        rows.append(
            {
                "Kategorie": "Abzug Fruehstueck inklusive (pro Person)",
                "Name": f"{breakfast_days} Tage",
                "Kosten": -breakfast_discount,
            }
        )

    rows.append({"Kategorie": "Verpflegung netto", "Name": "Nach Abzug", "Kosten": costs_food})

    per_person = costs_flights + costs_transport_other + costs_accommodation + costs_activities + costs_food
    return (
        per_person,
        rows,
        costs_flights,
        costs_transport_other,
        costs_accommodation,
        costs_bkk_hotel,
        costs_island_home,
        costs_activities,
        costs_food,
    )


def render_login_gate() -> str | None:
    """Zeigt eine eigenständige Login-Seite im Main-Bereich und liefert den aktiven Nutzernamen."""
    if st.session_state.get("is_authenticated") and str(st.session_state.get("auth_user", "")).strip():
        return str(st.session_state["auth_user"]).strip()

    st.markdown("## Anmeldung")
    st.caption("Bitte Namen eingeben, um deine gespeicherte Traumreise automatisch zu laden.")
    st.info("Hinweis: Die Preise bei Unterkünften sind pro Nacht kalkuliert und werden in der Endrechnung durch die Anzahl der Personen geteilt.")

    default_name = str(st.session_state.get("user_name", "")).strip()
    with st.form("login_form", clear_on_submit=False):
        login_name = st.text_input("Dein Name", value=default_name, placeholder="z. B. Robin")
        submitted = st.form_submit_button("Weiter")

    if submitted:
        clean_name = str(login_name).strip()
        if clean_name:
            st.session_state["is_authenticated"] = True
            st.session_state["auth_user"] = clean_name
            st.session_state["user_name"] = clean_name
            save_persisted_state()
            st.rerun()
        st.error("Bitte einen Namen eingeben.")

    return None


def main() -> None:
    load_persisted_state()

    st.title("Thailand Reise Auto-Konfigurator")
    st.info(
        "ℹ️ Alle Preise bei Unterkünften sind pro Nacht. "
        "Bei der Unterkunft auf der Insel wird der Gesamtpreis zusätzlich durch die Anzahl der Reisenden geteilt. "
        "Aktuell ist geplant: 4 Tage Bangkok, dann 9 Tage Insel und danach noch 1 Nacht in Bangkok."
    )

    user_name = render_login_gate()
    if not user_name:
        st.stop()


    if should_seed_csvs_for_user(user_name) and not st.session_state.get("_csv_seed_done"):
        seed_csv_data_to_supabase_for_robin()
        st.session_state["_csv_seed_done"] = True

    df_unterkuenfte, df_aktivitaeten, df_transporte = load_csv_files()

    df_unterkuenfte = ensure_columns(
        df_unterkuenfte,
        {
            "Bild": "",
            "Details": "",
            "Vorteile": "",
            "Nachteile": "",
            "AirportTransfer": "Selbst",
            "TransferKosten": 0,
            "FruehstueckInklusive": "Nein",
        },
    )
    df_unterkuenfte = attach_image_column(prepare_location_column(df_unterkuenfte), "unterkunft")

    available_locations = sorted(df_unterkuenfte["StandortNorm"].dropna().astype(str).unique().tolist())
    if not available_locations:
        available_locations = ["Bangkok", "Ko Samui", "Phuket"]

    df_aktivitaeten = ensure_columns(df_aktivitaeten, {"Bild": "", "Details": "", "Link": ""})
    df_aktivitaeten = attach_image_column(prepare_location_column(df_aktivitaeten), "aktivitaet")


    top_left, top_right = st.columns([4, 1])
    with top_left:
        st.caption(f"Angemeldet als: {user_name}")
    with top_right:
        if st.button("Abmelden", key="logout_main", use_container_width=True):
            st.session_state["is_authenticated"] = False
            st.session_state["auth_user"] = ""
            st.session_state["_snapshot_loaded_for"] = None
            save_persisted_state()
            st.rerun()

    # Bestimme Seitenliste: Statistik nur für Robin
    st.sidebar.markdown("### Nutzer")
    st.sidebar.write(f"Angemeldet als: **{user_name}**")
    if st.sidebar.button("Abmelden", use_container_width=True):
        st.session_state["is_authenticated"] = False
        st.session_state["auth_user"] = ""
        st.session_state["_snapshot_loaded_for"] = None
        save_persisted_state()
        st.rerun()

    active_user_key = str(user_name).strip().lower()

    seiten_liste = ["Konfigurator", "Übersicht"]
    admin_data_users = {"robin", "sarh", "sarah"}
    if active_user_key in admin_data_users:
        seiten_liste.append("Unterkunft/Transport hinzufügen")
    if active_user_key == "robin":
        seiten_liste.append("Statistik")

    page = st.sidebar.radio("Seiten", seiten_liste)

    # Lade Snapshot ganz am Anfang, BEVOR Widgets erstellt werden
    snapshot = None
    if st.session_state.get("_snapshot_loaded_for") != active_user_key:
        snapshot = load_user_snapshot(user_name)
        if snapshot:
            apply_snapshot_to_state(snapshot)
            st.session_state["_snapshot_loaded_for"] = active_user_key
            st.sidebar.success(f"✓ Gespeicherte Auswahl fuer '{user_name}' wiederhergestellt")
            save_persisted_state()
        else:
            st.session_state["_snapshot_loaded_for"] = active_user_key

    st.sidebar.markdown("### Schätzungen vor Ort")
    st.sidebar.info(
        "Hinweis: Die Werte in der Seitenleiste (z. B. Transportkosten, Verpflegung, Frühstücks-Abzug) "
        "sind Schätzungen von uns/der KI und können jederzeit angepasst werden."
    )
    num_travelers = int(
        st.sidebar.number_input(
            "Anzahl Reisende",
            min_value=1,
            max_value=50,
            value=int(get_initial_value("num_travelers", 4, snapshot)),
            step=1,
            key="num_travelers",
        )
    )
    days_bangkok = int(
        st.sidebar.number_input(
            "Tage Bangkok",
            min_value=0,
            max_value=30,
            value=int(get_initial_value("days_bangkok", 5, snapshot)),
            step=1,
            key="days_bangkok",
        )
    )
    days_island = int(
        st.sidebar.number_input(
            "Tage Insel",
            min_value=0,
            max_value=30,
            value=int(get_initial_value("days_island", 9, snapshot)),
            step=1,
            key="days_island",
        )
    )
    local_transport_per_day_pp = float(
        st.sidebar.number_input(
            "Transport vor Ort / Person / Tag",
            min_value=0.0,
            value=float(get_initial_value("local_transport_per_day_pp", 5.0, snapshot)),
            step=1.0,
            key="local_transport_per_day_pp",
        )
    )
    food_per_day_pp = float(
        st.sidebar.number_input(
            "Verpflegung / Person / Tag",
            min_value=0.0,
            value=float(get_initial_value("food_per_day_pp", 15.0, snapshot)),
            step=1.0,
            key="food_per_day_pp",
        )
    )
    breakfast_discount_per_day_pp = float(
        st.sidebar.number_input(
            "Abzug bei Fruehstueck inkl. / Person / Tag",
            min_value=0.0,
            value=float(get_initial_value("breakfast_discount_per_day_pp", 3.0, snapshot)),
            step=1.0,
            key="breakfast_discount_per_day_pp",
        )
    )


    if active_user_key == "robin":
        st.sidebar.markdown("### Admin")
        admin_cmd = st.sidebar.text_input("Befehl", placeholder="download")
        if admin_cmd.strip().lower() in {"download", "download_csv", "export"}:
            if CSV_USER_SAVES.exists():
                st.sidebar.download_button(
                    "Speicherstände CSV herunterladen",
                    data=CSV_USER_SAVES.read_bytes(),
                    file_name="init_data/traumreisen_speicherstaende.csv",
                    mime="text/csv",
                )
            else:
                st.sidebar.info("Noch keine Speicherstände vorhanden.")

        # Neue Export-Buttons
        st.sidebar.markdown("### Daten-Export")
        col1, col2, col3 = st.sidebar.columns(3)
        
        with col1:
            if CSV_USER_SAVES.exists():
                st.download_button(
                    "📥 Reisen",
                    CSV_USER_SAVES.read_bytes(),
                    "speicherstaende.csv",
                    use_container_width=True
                )
        
        with col2:
            if CSV_ACTIVITY_SUGGESTIONS.exists():
                st.download_button(
                    "📥 Vorschläge",
                    CSV_ACTIVITY_SUGGESTIONS.read_bytes(),
                    "aktivitaeten_vorschlaege.csv",
                    use_container_width=True
                )
        
        with col3:
            if CSV_AKTIVITAETEN.exists():
                st.download_button(
                    "📥 Aktivitäten",
                    CSV_AKTIVITAETEN.read_bytes(),
                    "aktivitaeten.csv",
                    use_container_width=True
                )

    flight_df = df_transporte[df_transporte["Typ"].astype(str).str.lower() == "flug"].copy()
    flight_df.loc[:, "NameNorm"] = flight_df["Name"].map(normalize_text)
    intl_df = flight_df[
        flight_df["NameNorm"].str.contains("bangkok", na=False)
        & ~flight_df["NameNorm"].str.contains("phuket|samui", na=False)
    ]
    if intl_df.empty:
        intl_df = flight_df[flight_df["NameNorm"].str.contains("bangkok", na=False)]

    bkk_hotels = df_unterkuenfte[df_unterkuenfte["StandortNorm"] == "Bangkok"]
    # Robuster Filter: nimmt auch uneinheitliche CSV-Eintraege fuer Insel-Unterkuenfte mit.
    island_homes = df_unterkuenfte[df_unterkuenfte.apply(is_island_accommodation, axis=1)]
    bkk_activities = df_aktivitaeten[df_aktivitaeten["StandortNorm"] == "Bangkok"]

    selected_flight_idx = _to_optional_int(st.session_state.get("sel_flight"))
    selected_bkk_hotel_idx = _to_optional_int(st.session_state.get("sel_bkk_hotel"))
    selected_island_home_idx = _to_optional_int(st.session_state.get("sel_island_home"))
    selected_bkk_act_idx = _to_int_list(st.session_state.get("sel_bkk_act", []))
    selected_island_act_idx = _to_int_list(st.session_state.get("sel_island_act", []))

    # Bereinigte Werte zurückschreiben, damit Widgets und Persistenz identisch bleiben.
    st.session_state["sel_flight"] = selected_flight_idx
    st.session_state["sel_bkk_hotel"] = selected_bkk_hotel_idx
    st.session_state["sel_island_home"] = selected_island_home_idx
    st.session_state["sel_bkk_act"] = selected_bkk_act_idx
    st.session_state["sel_island_act"] = selected_island_act_idx

    selected_flight = intl_df.loc[selected_flight_idx] if selected_flight_idx in intl_df.index else None
    selected_bkk_hotel = bkk_hotels.loc[selected_bkk_hotel_idx] if selected_bkk_hotel_idx in bkk_hotels.index else None
    selected_island_home = (
        island_homes.loc[selected_island_home_idx] if selected_island_home_idx in island_homes.index else None
    )

    destination = resolve_island_destination(selected_island_home)
    domestic_flight = find_domestic_flight(df_transporte, destination) if destination else None

    island_activities = pd.DataFrame(columns=df_aktivitaeten.columns)
    if destination:
        island_activities = df_aktivitaeten[df_aktivitaeten["StandortNorm"] == destination]

    samui_activities = df_aktivitaeten[df_aktivitaeten["StandortNorm"] == "Ko Samui"]
    phuket_activities = df_aktivitaeten[df_aktivitaeten["StandortNorm"] == "Phuket"]

    selected_bkk_acts = bkk_activities[bkk_activities.index.isin(selected_bkk_act_idx)]
    selected_island_acts = island_activities[island_activities.index.isin(selected_island_act_idx)]

    (
        per_person,
        rows,
        costs_flights,
        costs_transport_other,
        costs_accommodation,
        costs_bkk_hotel,
        costs_island_home,
        costs_activities,
        costs_food,
    ) = calculate_summary(
        selected_flight,
        domestic_flight,
        selected_bkk_hotel,
        selected_island_home,
        selected_bkk_acts,
        selected_island_acts,
        num_travelers,
        days_bangkok,
        days_island,
        local_transport_per_day_pp,
        food_per_day_pp,
        breakfast_discount_per_day_pp,
    )

    # Auto-Snapshot je Nutzer: sorgt für Wiederherstellung bei Reload und auf anderen Geräten.
    autosave_payload = normalize_state_payload({key: st.session_state.get(key) for key in PERSIST_KEYS})
    autosave_record = {
        "Zeitstempel": datetime.now().isoformat(timespec="seconds"),
        "Name": user_name.strip(),
        "StateJson": json.dumps(autosave_payload, ensure_ascii=True),
        "Personen": num_travelers,
        "TageBangkok": days_bangkok,
        "TageInsel": days_island,
        "FlugInternational": selected_flight["Name"] if selected_flight is not None else "",
        "BangkokHotel": selected_bkk_hotel["Name"] if selected_bkk_hotel is not None else "",
        "InselUnterkunft": selected_island_home["Name"] if selected_island_home is not None else "",
        "InselZiel": destination or "",
        "AktivitätenBangkok": selected_names(selected_bkk_acts),
        "AktivitätenInsel": selected_names(selected_island_acts),
        "KostenFluegePP": round(costs_flights, 2),
        "KostenTransportSonstPP": round(costs_transport_other, 2),
        "KostenHotelBangkokPP": round(costs_bkk_hotel, 2),
        "KostenInselUnterkunftPP": round(costs_island_home, 2),
        "KostenAktivitätenPP": round(costs_activities, 2),
        "KostenVerpflegungPP": round(costs_food, 2),
        "PreisProPerson": round(per_person, 2),
    }
    save_user_snapshot(autosave_record)

    if page == "Konfigurator":
        st.subheader("1) Flug nach Bangkok")
        st.selectbox(
            "Internationaler Flug",
            options=intl_df.index.tolist(),
            format_func=lambda idx: f"{intl_df.loc[idx, 'Name']} - {format_currency(float(intl_df.loc[idx, 'Kosten']))}",
            key="sel_flight",
            index=None if selected_flight_idx not in intl_df.index else intl_df.index.tolist().index(selected_flight_idx),
            placeholder="Bitte Flug wählen",
        )

        st.subheader("2) Hotel in Bangkok")
        image_select_grid(
            bkk_hotels,
            "bkk_hotel",
            selected_bkk_hotel_idx,
            False,
            "Hotelbild anklicken",
            info_mode="accommodation",
        )

        st.subheader("3) Aktivitäten in Bangkok")
        image_select_grid(
            bkk_activities,
            "bkk_act",
            selected_bkk_act_idx,
            True,
            "Mehrfachauswahl per Bildklick",
            info_mode="activity",
        )

        st.subheader("4) Ferienwohnung auf der Insel")
        image_select_grid(
            island_homes,
            "island_home",
            selected_island_home_idx,
            False,
            "Ferienwohnung per Bildklick auswählen",
            info_mode="accommodation",
        )

        st.subheader("5) Automatischer Inlandsflug")
        if domestic_flight is None and destination:
            st.warning(f"Kein passender Flug Bangkok -> {destination} gefunden.")
        elif domestic_flight is not None:
            st.success(
                f"Auto-Flug: {domestic_flight['Name']} - {format_currency(float(domestic_flight['Kosten']))}"
            )
        else:
            st.info("Wähle zuerst eine Ferienwohnung, dann wird der Inlandsflug automatisch gesucht.")

        st.subheader("6) Aktivitäten auf der Insel")
        if destination:
            image_select_grid(
                island_activities,
                "island_act",
                selected_island_act_idx,
                True,
                f"Aktivitäten in {destination}",
                info_mode="activity",
            )
        else:
            st.info("Sobald eine Ferienwohnung gewählt ist, erscheinen hier die Insel-Aktivitäten.")

        st.subheader("7) Eigene Aktivität vorschlagen")
        st.caption("Leere Felder bekommen automatisch sinnvolle Default-Werte. Robin kann Vorschläge freigeben oder ablehnen.")
        with st.form("custom_activity_form", clear_on_submit=True):
            ca1, ca2 = st.columns(2)
            custom_name = ca1.text_input("Name der Aktivitaet")
            custom_cost = ca2.number_input("Kosten pro Person", min_value=0.0, value=0.0, step=1.0)

            cb1, cb2 = st.columns(2)
            custom_location = cb1.selectbox("Standort", options=available_locations)
            custom_link = cb2.text_input("Link (optional)", placeholder="https://...")

            custom_details = st.text_area("Details", placeholder="Was ist wichtig? Dauer, Treffpunkt, Besonderheiten...")
            custom_image = st.text_input("Bild-Link", placeholder="https://...jpg")
            add_custom = st.form_submit_button("Aktivitaet zur Liste hinzufügen")

        if add_custom:
            new_activity = {
                "Name": custom_name.strip() or "Eigene Aktivitaet",
                "Kosten": float(custom_cost) if custom_cost is not None else 0.0,
                "Standort": str(custom_location).strip() or "Bangkok",
                "Link": custom_link.strip(),
                "Bild": custom_image.strip(),
                "Details": custom_details.strip() or "Keine Details angegeben",
            }
            submit_activity_suggestion(user_name, new_activity)
            st.success("Vorschlag gespeichert. Robin kann ihn jetzt annehmen oder ablehnen.")
            st.rerun()

        my_open = list_open_suggestions_for_user(user_name)
        if not my_open.empty:
            st.markdown("**Deine offenen Vorschläge**")
            st.dataframe(
                my_open[["created_at", "name", "location", "cost", "details", "link", "image_url"]],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("Du hast aktuell keine offenen Vorschläge.")

        if active_user_key == "robin":
            st.markdown("### Admin: Vorschläge prüfen")
            pending = list_pending_suggestions()
            if pending.empty:
                st.caption("Keine offenen Vorschläge vorhanden.")
            else:
                for _, suggestion in pending.sort_values("created_at", ascending=False).iterrows():
                    st.markdown(
                        f"**{suggestion['name']}** ({suggestion['location']}) - {format_currency(float(suggestion['cost'] or 0))}"
                    )
                    st.caption(f"Vorgeschlagen von: {suggestion['proposed_by']} | {suggestion['created_at']}")
                    st.write(str(suggestion.get("details", "")).strip() or "Keine Details angegeben")
                    if str(suggestion.get("link", "")).strip():
                        st.markdown(f"[Link öffnen]({str(suggestion['link']).strip()})")
                    if str(suggestion.get("image_url", "")).strip():
                        st.caption(f"Bild: {str(suggestion['image_url']).strip()}")

                    a1, a2 = st.columns(2)
                    if a1.button("Annehmen", key=f"approve_{suggestion['id']}", use_container_width=True):
                        if review_suggestion(str(suggestion["id"]), approved=True, reviewer=user_name):
                            st.success("Vorschlag angenommen und global hinzugefügt.")
                            st.rerun()
                    if a2.button("Ablehnen", key=f"reject_{suggestion['id']}", use_container_width=True):
                        if review_suggestion(str(suggestion["id"]), approved=False, reviewer=user_name):
                            st.info("Vorschlag abgelehnt.")
                            st.rerun()
                    st.divider()

        st.divider()
        st.metric("Preis pro Person", format_currency(per_person))

        st.markdown("### Traumreise speichern")
        if st.button("Traumreise speichern", type="primary"):
            state_payload = normalize_state_payload({key: st.session_state.get(key) for key in PERSIST_KEYS})
            snapshot_record = {
                "Zeitstempel": datetime.now().isoformat(timespec="seconds"),
                "Name": user_name.strip(),
                "StateJson": json.dumps(state_payload, ensure_ascii=True),
                "Personen": num_travelers,
                "TageBangkok": days_bangkok,
                "TageInsel": days_island,
                "FlugInternational": selected_flight["Name"] if selected_flight is not None else "",
                "BangkokHotel": selected_bkk_hotel["Name"] if selected_bkk_hotel is not None else "",
                "InselUnterkunft": selected_island_home["Name"] if selected_island_home is not None else "",
                "InselZiel": destination or "",
                "AktivitätenBangkok": selected_names(selected_bkk_acts),
                "AktivitätenInsel": selected_names(selected_island_acts),
                "KostenFlügePP": round(costs_flights, 2),
                "KostenTransportSonstPP": round(costs_transport_other, 2),
                "KostenHotelBangkokPP": round(costs_bkk_hotel, 2),
                "KostenInselUnterkunftPP": round(costs_island_home, 2),
                "KostenAktivitätenPP": round(costs_activities, 2),
                "KostenVerpflegungPP": round(costs_food, 2),
                "PreisProPerson": round(per_person, 2),
            }
            save_user_snapshot(snapshot_record)
            st.success(f"Gespeichert für {user_name.strip()}.")

    elif page == "Übersicht":
        st.subheader("Übersicht")
        c1, c2, c3 = st.columns(3)
        c1.metric("Gesamt pro Person", format_currency(per_person))
        c2.metric("Flüge pro Person", format_currency(costs_flights))
        c3.metric("Unterkünfte gesamt p.P.", format_currency(costs_accommodation))

        if rows:
            detail_df = pd.DataFrame(rows)
            total_row = pd.DataFrame(
                [{"Kategorie": "Gesamt pro Person", "Name": "Endsumme", "Kosten": float(per_person)}]
            )
            detail_df = pd.concat([detail_df, total_row], ignore_index=True)
            detail_df["Kosten"] = detail_df["Kosten"].map(format_currency)
            st.dataframe(detail_df, use_container_width=True, hide_index=True)
        else:
            st.info("Noch keine Positionen ausgewählt.")


    elif page == "Unterkunft/Transport hinzufügen":
        st.subheader("Neue Unterkunft oder neuen Transport hinzufügen")
        st.caption("Nur sichtbar für sarh/sarah und robin.")

        tab_u, tab_t = st.tabs(["Unterkunft", "Transport"])

        with tab_u:
            with st.form("add_unterkunft_form", clear_on_submit=True):
                u1, u2 = st.columns(2)
                u_name = u1.text_input("Name")
                u_cost = u2.number_input("Kosten pro Nacht", min_value=0.0, value=0.0, step=1.0)

                u3, u4 = st.columns(2)
                u_location = u3.selectbox("Standort", options=available_locations)
                u_link = u4.text_input("Link", placeholder="https://...")

                u_image = st.text_input("Bild-Link", placeholder="https://...jpg")
                u_details = st.text_area("Details")
                uv1, uv2 = st.columns(2)
                u_adv = uv1.text_area("Vorteile")
                u_disadv = uv2.text_area("Nachteile")

                ut1, ut2, ut3 = st.columns(3)
                u_transfer_mode = ut1.selectbox("Airport-Transfer", options=["Selbst", "Angeboten"])
                u_transfer_cost = ut2.number_input("Transferkosten", min_value=0.0, value=0.0, step=1.0)
                u_breakfast = ut3.selectbox("Frühstück inklusive", options=["Nein", "Ja"])

                submit_u = st.form_submit_button("Unterkunft hinzufügen")

            if submit_u:
                success, msg = add_unterkunft_to_supabase(
                    {
                        "name": u_name.strip(),
                        "cost": float(u_cost),
                        "location": str(u_location).strip(),
                        "link": u_link.strip(),
                        "image_url": u_image.strip(),
                        "details": u_details.strip(),
                        "advantages": u_adv.strip(),
                        "disadvantages": u_disadv.strip(),
                        "airport_transfer": u_transfer_mode,
                        "transfer_cost": float(u_transfer_cost),
                        "breakfast_included": u_breakfast,
                    }
                )
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

        with tab_t:
            with st.form("add_transport_form", clear_on_submit=True):
                t1, t2 = st.columns(2)
                t_cost = t1.number_input("Kosten", min_value=0.0, value=0.0, step=1.0)
                t_type = t2.selectbox("Typ", options=["Flug", "Fähre"])

                t_von = ""
                t_nach = ""
                t_flugzeit_hin = ""
                t_flugzeit_zurueck = ""
                t_zwischenstop_ort = ""
                t_sonstiges = ""
                if t_type == "Flug":
                    f1, f2 = st.columns(2)
                    t_von = f1.text_input("von")
                    t_nach = f2.selectbox("nach", options=["Bangkok", "Ko Samui", "Phuket"], key="transport_nach_flug")

                    f3, f4 = st.columns(2)
                    t_flugzeit_hin = f3.text_input("Flugzeit hin")
                    t_flugzeit_zurueck = f4.text_input("Flugzeit zurück")

                    f5, f6 = st.columns(2)
                    t_zwischenstop_ort = f5.text_input("Zwischenstop Ort")
                    t_sonstiges = f6.text_input("Sonstiges")
                else:
                    f1, f2 = st.columns(2)
                    t_von = f1.text_input("von")
                    t_nach = f2.selectbox("nach", options=["Bangkok", "Ko Samui", "Phuket"], key="transport_nach_faehre")
                    t_sonstiges = st.text_input("Sonstiges")

                submit_t = st.form_submit_button("Transport hinzufügen")

            if submit_t:
                final_transport_name = ""
                if t_type == "Flug":
                    if not t_von.strip() or not t_nach.strip():
                        st.error("Für Flug bitte mindestens 'von' und 'nach' angeben.")
                        final_transport_name = ""
                    else:
                        final_transport_name = build_flight_transport_name(
                            von=t_von.strip(),
                            nach=t_nach.strip(),
                            flugzeit_hin=t_flugzeit_hin.strip() or "k. A.",
                            flugzeit_zurueck=t_flugzeit_zurueck.strip() or "k. A.",
                            zwischenstop_ort=t_zwischenstop_ort.strip() or "kein",
                            sonstiges=t_sonstiges.strip() or "-",
                        )
                else:
                    von_text = t_von.strip() or "k. A."
                    nach_text = t_nach.strip() or "k. A."
                    sonstiges_text = t_sonstiges.strip() or "-"
                    final_transport_name = f"Fähre ({von_text} - {nach_text}); Sonstiges: {sonstiges_text}"

                if not final_transport_name:
                    pass
                else:
                    success, msg = add_transport_to_supabase(
                        {
                            "name": final_transport_name,
                            "cost": float(t_cost),
                            "type": t_type,
                        }
                    )
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

    elif page == "Statistik":
        st.subheader("📊 Traumreisen Statistik")
        saves_df = pd.DataFrame()
        client = get_supabase_client()
        if client is not None:
            try:
                response = client.table("saved_travels").select("*").execute()
                if response.data:
                    raw = pd.DataFrame(response.data)
                    saves_df = pd.DataFrame(
                        {
                            "Zeitstempel": raw.get("created_at", ""),
                            "Name": raw.get("user_name", ""),
                            "Personen": raw.get("num_travelers", 0),
                            "TageBangkok": raw.get("days_bangkok", 0),
                            "TageInsel": raw.get("days_island", 0),
                            "BangkokHotel": raw.get("bkk_hotel", ""),
                            "InselUnterkunft": raw.get("island_accommodation", ""),
                            "InselZiel": raw.get("island_destination", ""),
                            "PreisProPerson": raw.get("total_per_person", 0),
                            "KostenFluegePP": raw.get("cost_flights", 0),
                            "KostenTransportSonstPP": raw.get("cost_transport", 0),
                            "KostenHotelBangkokPP": raw.get("cost_hotel", 0),
                            "KostenInselUnterkunftPP": raw.get("cost_island", 0),
                            "KostenAktivitätenPP": raw.get("cost_activities", 0),
                            "KostenVerpflegungPP": raw.get("cost_food", 0),
                        }
                    )
            except Exception:
                saves_df = pd.DataFrame()

        if saves_df.empty and CSV_USER_SAVES.exists():
            saves_df = pd.read_csv(CSV_USER_SAVES)
            saves_df.columns = [str(col).strip() for col in saves_df.columns]

        if not saves_df.empty:
            for num_col in [
                "PreisProPerson",
                "KostenFluegePP",
                "KostenTransportSonstPP",
                "KostenHotelBangkokPP",
                "KostenInselUnterkunftPP",
                "KostenAktivitätenPP",
                "KostenVerpflegungPP",
            ]:
                if num_col in saves_df.columns:
                    saves_df[num_col] = pd.to_numeric(saves_df[num_col], errors="coerce").fillna(0.0)
            
            # Grundstatistiken
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Gesamte Traumreisen gespeichert", len(saves_df))
            col2.metric("Verschiedene Nutzer", saves_df["Name"].nunique())
            col3.metric("Durchschn. Preis pro Person", format_currency(saves_df["PreisProPerson"].mean()))
            col4.metric("Höchster Preis pro Person", format_currency(saves_df["PreisProPerson"].max()))

            m1, m2, m3 = st.columns(3)
            m1.metric("Niedrigster Preis pro Person", format_currency(saves_df["PreisProPerson"].min()))
            m2.metric("Median Preis pro Person", format_currency(float(saves_df["PreisProPerson"].median())))
            m3.metric("Spannweite (Max-Min)", format_currency(saves_df["PreisProPerson"].max() - saves_df["PreisProPerson"].min()))
            
            st.divider()
            
            # Detaillierte Tabelle
            st.markdown("### Alle Traumreisen")
            display_df = saves_df[
                ["Zeitstempel", "Name", "Personen", "TageBangkok", "TageInsel", 
                 "BangkokHotel", "InselUnterkunft", "InselZiel", "PreisProPerson"]
            ].copy()
            display_df["PreisProPerson"] = display_df["PreisProPerson"].apply(format_currency)
            st.dataframe(display_df, use_container_width=True, hide_index=True)
            
            st.divider()
            
            # Kostenverteilung
            st.markdown("### Kostenverteilung pro Person (Durchschnitt)")
            cost_cols = [
                "KostenFlügePP",
                "KostenTransportSonstPP", 
                "KostenHotelBangkokPP",
                "KostenInselUnterkunftPP",
                "KostenAktivitätenPP",
                "KostenVerpflegungPP"
            ]
            cost_labels = [
                "Flüge",
                "Transport sonstig",
                "Hotel Bangkok",
                "Insel-Unterkunft",
                "Aktivitäten",
                "Verpflegung"
            ]
            
            avg_costs = saves_df[cost_cols].mean().values
            
            # Zeige Kosten als Metriken statt Balkendiagramm (robuster, keine Altair-Abhängigkeit)
            cost_cols_ui = st.columns(3)
            for idx, (label, cost) in enumerate(zip(cost_labels, avg_costs)):
                with cost_cols_ui[idx % 3]:
                    st.metric(label, format_currency(cost))
            
            st.divider()
            
            # Beliebte Hotels & Inseln
            st.markdown("### Beliebte Destinationen")
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**Top Bangkok Hotels**")
                bkk_top = saves_df["BangkokHotel"].value_counts().head(5)
                for hotel, count in bkk_top.items():
                    if hotel:
                        st.write(f"• {hotel}: {count}x")
            
            with col2:
                st.markdown("**Top Inseln**")
                island_top = saves_df["InselZiel"].value_counts().head(5)
                for island, count in island_top.items():
                    if island:
                        st.write(f"• {island}: {count}x")

            st.divider()
            st.markdown("### Wünsche nach Unterkunft")

            st.markdown("**Bangkok Hotels (Häufigkeit)**")
            bangkok_hotel_counts = (
                saves_df["BangkokHotel"].astype(str).str.strip().replace({"": pd.NA}).dropna().value_counts().head(10)
            )
            if not bangkok_hotel_counts.empty:
                st.bar_chart(bangkok_hotel_counts)
            else:
                st.caption("Noch keine Daten für Bangkok-Hotels vorhanden.")

            island_targets = (
                saves_df["InselZiel"].astype(str).str.strip().replace({"": pd.NA}).dropna().unique().tolist()
            )
            if island_targets:
                for island in sorted(island_targets):
                    st.markdown(f"**Unterkünfte auf {island} (Häufigkeit)**")
                    mask = saves_df["InselZiel"].astype(str).str.strip().eq(island)
                    island_counts = (
                        saves_df.loc[mask, "InselUnterkunft"]
                        .astype(str)
                        .str.strip()
                        .replace({"": pd.NA})
                        .dropna()
                        .value_counts()
                        .head(10)
                    )
                    if not island_counts.empty:
                        st.bar_chart(island_counts)
                    else:
                        st.caption(f"Noch keine Unterkunftsdaten für {island} vorhanden.")
            
        else:
            st.info("Noch keine Traumreisen gespeichert.")

    save_persisted_state()


if __name__ == "__main__":
    main()

