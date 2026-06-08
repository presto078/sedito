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
                pokpol_ostatni = pokpol[pokpol['ZpPlat'] != 'K'].copy()
                
                # --- 1. KROK: VYRUŠENÍ VNITŘNÍCH STOREN В KASE ---
                pokpol_karty['vnitrni_storno'] = False
                pokpol_k_pos = pokpol_karty[pokpol_karty['Cena'] > 0].copy()
                pokpol_k_neg = pokpol_karty[pokpol_karty['Cena'] < 0].copy()
                
                storna_rows = []
                for n_idx, n_row in pokpol_k_neg.iterrows():
                    target_amt = abs(n_row['Cena'])
                    candidates = pokpol_k_pos[(pokpol_k_pos['Cena'] == target_amt) & (~pokpol_k_pos['vnitrni_storno'])]
                    if not candidates.empty:
                        time_diffs = (candidates['dt'] - n_row['dt']).abs()
                        time_diffs_12h = ((candidates['dt'] - n_row['dt']).abs() - pd.Timedelta(hours=12)).abs()
                        final_diffs = pd.concat([time_diffs, time_diffs_12h], axis=1).min(axis=1)
                        best_p_idx = final_diffs.idxmin()
                        
                        pokpol_k_pos.loc[best_p_idx, 'vnitrni_storno'] = True
                        storna_rows.append({
                            'Datum Pokladna': n_row['Datum a Čas'],
                            'Doklad CZAK (Storno)': n_row['CZAK'],
                            'Částka Storna': n_row['Cena'],
                            'Původní Doklad CZAK': pokpol_k_pos.loc[best_p_idx, 'CZAK'],
                            'Stav': 'Interně stornováno (V pořádku)'
                        })
                    else:
                        storna_rows.append({
                            'Datum Pokladna': n_row['Datum a Čas'],
                            'Doklad CZAK (Storno)': n_row['CZAK'],
                            'Částka Storna': n_row['Cena'],
                            'Původní Doklad CZAK': 'Nenalezen',
                            'Stav': 'Sirotčí storno (Chybí prodej)'
                        })
                
                pokpol_active_karty = pokpol_k_pos[~pokpol_k_pos['vnitrni_storno']].copy()
                
                # --- 2. KROK: INTELIGENTNÍ PÁROVÁNÍ 1:1 S OPRAVOU AM/PM ČASU ---
                matched_list = []
                unmatched_pokpol = []
                
                for idx, row in pokpol_active_karty.iterrows():
                    amt = row['Cena']
                    candidates = terminal_all[(terminal_all['Částka brutto'] == amt) & (~terminal_all['matched'])]
                    
                    if not candidates.empty:
                        diff_normal = (candidates['dt'] - row['dt']).abs()
                        diff_12h = ((candidates['dt'] - (row['dt'] + pd.Timedelta(hours=12))).abs())
                        combined_diffs = pd.concat([diff_normal, diff_12h], axis=1).min(axis=1)
                        best_idx = combined_diffs.idxmin()
                        
                        terminal_all.loc[best_idx, 'matched'] = True
                        matched_list.append({
                            'Pokladna Datum': row['Datum a Čas'],
                            'Doklad CZAK': row['CZAK'],
                            'Částka Pokladna': amt,
                            'Terminál Čas': terminal_all.loc[best_idx, 'Čas transakce'],
                            'Terminál Částka': terminal_all.loc
