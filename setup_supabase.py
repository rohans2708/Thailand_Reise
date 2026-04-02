#!/usr/bin/env python3
"""Supabase-Tabellen Setup Script."""

import sys
import tomllib

from supabase import create_client

# Lade Secrets aus .streamlit/secrets.toml
with open(".streamlit/secrets.toml", "rb") as f:
    secrets = tomllib.load(f)

url = secrets["SUPABASE_URL"]
key = secrets["SUPABASE_ANON_KEY"]

print(f"Verbinde zu Supabase: {url}")
client = create_client(url, key)

# SQL für Tabellen (in Supabase muss man eine spezielle API nutzen)
# Da der anon-Key keine DDL-Rechte hat, nutzen wir die REST-API nicht.
# Stattdessen: Log in mit Service Role Key oder nutze Supabase Dashboard direkt

print("\n⚠️  WICHTIG: Verwende einen Service Role Key oder das Supabase Dashboard!")
print("\nFolgende SQL-Statements müssen manuell im Supabase Dashboard ausgeführt werden:")
print("\n" + "="*60)

sql_statements = """
-- 1. Activity Suggestions Table
CREATE TABLE IF NOT EXISTS activity_suggestions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  proposed_by TEXT NOT NULL,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
  reviewed_by TEXT DEFAULT '',
  reviewed_at TIMESTAMP WITH TIME ZONE DEFAULT NULL,
  name TEXT NOT NULL,
  cost FLOAT DEFAULT 0,
  location TEXT NOT NULL,
  link TEXT DEFAULT '',
  image_url TEXT DEFAULT '',
  details TEXT DEFAULT ''
);

-- 2. Saved Travels Table
CREATE TABLE IF NOT EXISTS saved_travels (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_name TEXT NOT NULL UNIQUE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  state_json JSONB,
  num_travelers INT DEFAULT 1,
  days_bangkok INT DEFAULT 0,
  days_island INT DEFAULT 0,
  intl_flight TEXT DEFAULT '',
  bkk_hotel TEXT DEFAULT '',
  island_accommodation TEXT DEFAULT '',
  island_destination TEXT DEFAULT '',
  activities_bangkok TEXT DEFAULT '',
  activities_island TEXT DEFAULT '',
  cost_flights FLOAT DEFAULT 0,
  cost_transport FLOAT DEFAULT 0,
  cost_hotel FLOAT DEFAULT 0,
  cost_island FLOAT DEFAULT 0,
  cost_activities FLOAT DEFAULT 0,
  cost_food FLOAT DEFAULT 0,
  total_per_person FLOAT DEFAULT 0
);

-- 3. Aktivitaeten Table (Master Catalog)
CREATE TABLE IF NOT EXISTS aktivitaeten (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  name TEXT NOT NULL,
  cost FLOAT NOT NULL,
  location TEXT NOT NULL,
  link TEXT DEFAULT '',
  image_url TEXT DEFAULT '',
  details TEXT DEFAULT ''
);

-- 4. Unterkuenfte Table
CREATE TABLE IF NOT EXISTS unterkuenfte (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  name TEXT NOT NULL,
  cost FLOAT NOT NULL,
  location TEXT NOT NULL,
  link TEXT DEFAULT '',
  image_url TEXT DEFAULT '',
  details TEXT DEFAULT '',
  advantages TEXT DEFAULT '',
  disadvantages TEXT DEFAULT '',
  airport_transfer TEXT DEFAULT 'Selbst',
  transfer_cost FLOAT DEFAULT 0,
  breakfast_included TEXT DEFAULT 'Nein'
);

-- 5. Transporte Table
CREATE TABLE IF NOT EXISTS transporte (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  name TEXT NOT NULL,
  cost FLOAT NOT NULL,
  type TEXT NOT NULL
);

-- RLS Policies (Optional, if using Supabase Auth)
-- Für jetzt: Keine RLS - alle anon-Key-User können lesen/schreiben
ALTER TABLE activity_suggestions DISABLE ROW LEVEL SECURITY;
ALTER TABLE saved_travels DISABLE ROW LEVEL SECURITY;
ALTER TABLE aktivitaeten DISABLE ROW LEVEL SECURITY;
ALTER TABLE unterkuenfte DISABLE ROW LEVEL SECURITY;
ALTER TABLE transporte DISABLE ROW LEVEL SECURITY;
"""

print(sql_statements)
print("="*60)
print("\nSchritte zum Setup:")
print("1. Gehe zu: https://app.supabase.com/project/{project-id}/sql/new")
print("2. Kopiere das obige SQL")
print("3. Klicke 'Run'")
print("\nDanach wird die App automatisch mit Supabase arbeiten (mit CSV-Fallback).")

