import streamlit as st
import pandas as pd
import io
from openpyxl.styles import Font

st.set_page_config(page_title="SedíTo! - Profesionální párování tržeb", page_icon="💳", layout="centered")

st.title("💳 SedíTo! – Kontrola a párování tržeb")
st.write("Profesionální odsouhlasení pokladních dat Datona vůči bankovním terminálům a Amexu s finančním auditem.")

# 1. Nahrání souborů
st.subheader("1. Krok: Nahrání podkladů")

file_pokpol = st.file_uploader("Soubor prodejů Datona (pokpol.csv / xlsx)", type=["csv", "xlsx"])
file_karty = st.file_uploader("Soubor transakcí - KARTY (bankovní výpis)", type=["csv", "xlsx"])
file_amex = st.file_uploader("Soubor transakcí - AMEX", type=["csv", "xlsx"])

def load_df(uploaded_file, skip_rows=0):
    if uploaded_file.name.lower().endswith('.csv'):
        try:
            return pd.read_csv(uploaded_file, skiprows=skip_rows)
        except:
            return pd.read_csv(uploaded_file, skiprows=skip_rows, encoding='cp1250', sep=None, engine='python')
    else:
        return pd.read_excel(uploaded_file, skiprows=skip_rows)

if st.button("🚀 Spustit hloubkovou analýzu", use_container_width=True):
    if not file_pokpol or not file_karty or not file_amex:
        st.error("Prosím, nahrajte všechny 3 požadované soubory.")
    else:
        with st.spinner("Provádím finanční audit tržeb..."):
            try:
                # Načtení dat
                pokpol = load_df(file_pokpol, skip_rows=0)
                karty = load_df(file_karty, skip_rows=5)
                amex = load_df(file_amex, skip_rows=5)
                
                # Převod částek a datumů
                pokpol['Cena'] = pd.to_numeric(pokpol['Cena'], errors='coerce')
                karty['Částka brutto'] = pd.to_numeric(karty['Částka brutto'], errors='coerce')
                amex['Částka brutto'] = pd.to_numeric(amex['Částka brutto'], errors='coerce')
                
                pokpol['dt'] = pd.to_datetime(pokpol['Datum a Čas'], errors='coerce', dayfirst=True)
                karty['dt'] = pd.to_datetime(karty['Čas transakce'], errors='coerce', dayfirst=True)
                amex['dt'] = pd.to_datetime(amex['Čas transakce'], errors='coerce', dayfirst=True)
                
                # Sjednocení bankovních terminálů
                karty['Zdroj'] = 'Karty'
                amex['Zdroj'] = 'Amex'
                term_cols = ['Částka brutto', 'Čas transakce', 'dt', 'Zdroj', 'Číslo karty', 'Typ karty']
                for col in term_cols:
                    if col not in karty.columns: karty[col] = ''
                    if col not in amex.columns: amex[col] = ''
                terminal_all = pd.concat([karty[term_cols], amex[term_cols]], ignore_index=True).sort_values('dt')
                terminal_all['matched'] = False
                
                # Rozdělení pokladny podle sloupce ZpPlat
                pokpol_karty = pokpol[pokpol['ZpPlat'] == 'K'].copy()
                pokpol_ostatni = pokpol[pokpol['ZpPlat']
