import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="SedíTo! - Profesionální párování tržeb", page_icon="💳", layout="centered")

st.title("💳 SedíTo! – Kontrola a párování tržeb")
st.write("Profesionální odsouhlasení pokladních dat Datona vůči bankovním terminálům a Amexu.")

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
        with st.spinner("Provádím vnitřní audit pokladny, kontrolu hotovostí a párování s bankou..."):
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
                
                # Rozdělení pokladny podle nového sloupce ZpPlat (E)
                pokpol_karty = pokpol[pokpol['ZpPlat'] == 'K'].copy()
                pokpol_ostatni = pokpol[pokpol['ZpPlat'] != 'K'].copy()
                
                # --- 1. KROK: VYRUŠENÍ VNITŘNÍCH STOREN V KASE ---
                pokpol_karty['vnitrni_storno'] = False
                pokpol_k_pos = pokpol_karty[pokpol_karty['Cena'] > 0].copy().sort_values('dt')
                pokpol_k_neg = pokpol_karty[pokpol_karty['Cena'] < 0].copy().sort_values('dt')
                
                storna_rows = []
                for n_idx, n_row in pokpol_k_neg.iterrows():
                    target_amt = abs(n_row['Cena'])
                    candidates = pokpol_k_pos[(pokpol_k_pos['Cena'] == target_amt) & (~pokpol_k_pos['vnitrni_storno'])]
                    if not candidates.empty:
                        time_diffs = (candidates['dt'] - n_row['dt']).abs()
                        best_p_idx = time_diffs.idxmin()
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
                
                # Pouze prodeje, které nebyly stornovány
                pokpol_active_karty = pokpol_k_pos[~pokpol_k_pos['vnitrni_storno']].copy()
                
                # --- 2. KROK: PÁROVÁNÍ 1:1 KASA (K) VS BANKA ---
                matched_list = []
                unmatched_pokpol = []
                
                for idx, row in pokpol_active_karty.iterrows():
                    amt = row['Cena']
                    candidates = terminal_all[(terminal_all['Částka brutto'] == amt) & (~terminal_all['matched'])]
                    
                    if not candidates.empty:
                        time_diffs = (candidates['dt'] - row['dt']).abs()
                        best_idx = time_diffs.idxmin()
                        terminal_all.loc[best_idx, 'matched'] = True
                        
                        matched_list.append({
                            'Pokladna Datum': row['Datum a Čas'],
                            'Doklad CZAK': row['CZAK'],
                            'Částka Pokladna': amt,
                            'Terminál Čas': terminal_all.loc[best_idx, 'Čas transakce'],
                            'Terminál Částka': terminal_all.loc[best_idx, 'Částka brutto'],
                            'Typ karty': terminal_all.loc[best_idx, 'Typ karty'],
                            'Číslo karty': terminal_all.loc[best_idx, 'Číslo karty'],
                            'Zdroj': terminal_all.loc[best_idx, 'Zdroj'],
                            'Stav': 'Spárováno 1:1'
                        })
                    else:
                        unmatched_pokpol.append(row)
                
                # --- 3. KROK: AUDIT ZÁMĚN A PŘEKLEPŮ ---
                df_prebyva_terminal = terminal_all[~terminal_all['matched']].copy()
                df_chyby_preklepy_zaměny = []
                
                for row in unmatched_pokpol:
                    df_chyby_preklepy_zaměny.append({
                        'Typ neshody': '❌ Chybí na terminálu (Ztráta)',
                        'Datum / Čas': row['Datum a Čas'],
                        'Částka v Kase': row['Cena'],
                        'Částka v Bance': 0,
                        'Doklad / Karta': row['CZAK'],
                        'Dohledaná poznámka': 'Zavřeno na kartu, ale zákazník neodpípl / transakce neprošla.'
                    })
                
                for t_idx, t_row in df_prebyva_terminal.iterrows():
                    amt = t_row['Částka brutto']
                    t_day = t_row['dt'].date()
                    
                    pokpol_ostatni['date'] = pokpol_ostatni['dt'].dt.date
                    hot_cand = pokpol_ostatni[(pokpol_ostatni['Cena'] == amt) & (pokpol_ostatni['date'] == t_day)]
                    
                    if not hot_cand.empty:
                        best_h_row = hot_cand.iloc[0]
                        df_chyby_preklepy_zaměny.append({
                            'Typ neshody': '⚠️ Záměna: Karta místo HOTOVOSTI',
                            'Datum / Čas': best_h_row['Datum a Čas'],
                            'Částka v Kase': best_h_row['Cena'],
                            'Částka v Bance': amt,
                            'Doklad / Karta': best_h_row['CZAK'],
                            'Dohledaná poznámka': f"V kase je zadáno jako Hotovost (ZpPlat={best_h_row['ZpPlat']}), ale na terminálu prošla karta."
                        })
                        terminal_all.loc[t_idx, 'matched'] = True
                        continue
                    
                    day_unmatched_k = [r for r in unmatched_pokpol if pd.to_datetime(r['Datum a Čas'], dayfirst=True).date() == t_day]
                    found_preklep = False
                    for r_k in day_unmatched_k:
                        if abs(r_k['Cena'] - amt) <= 200:
                            df_chyby_preklepy_zaměny.append({
                                'Typ neshody': '✍️ Překlep obsluhy na terminálu',
                                'Datum / Čas': r_k['Datum a Čas'],
                                'Částka v Kase': r_k['Cena'],
                                'Částka v Bance': amt,
                                'Doklad / Karta': r_k['CZAK'],
                                'Dohledaná poznámka': f"V kase je zadáno {r_k['Cena']} Kč, ale na terminál naťukali {amt} Kč (rozdíl {amt - r_k['Cena']} Kč)."
                            })
                            terminal_all.loc[t_idx, 'matched'] = True
                            df_chyby_preklepy_zaměny = [x for x in df_chyby_preklepy_zaměny if x['Doklad / Karta'] != r_k['CZAK']]
                            found_preklep = True
                            break
                    
                    if found_preklep: continue
                        
                    df_chyby_preklepy_zaměny.append({
                        'Typ neshody': '💰 Přebývá na terminálu (Nezadáno)',
                        'Datum / Čas': t_row['Čas transakce'],
                        'Částka v Kase': 0,
                        'Částka v Bance': amt,
                        'Doklad / Karta': t_row['Číslo karty'],
                        'Dohledaná poznámka': f"Peníze dorazily na účet ({t_row['Zdroj']}), ale v kase chybí jakýkoliv doklad."
                    })
                
                df_neshody_final = pd.DataFrame(df_chyby_preklepy_zaměny)
                df_matched = pd.DataFrame(matched_list)
                df_storna_final = pd.DataFrame(storna_rows)
                
                st.success("Hloubkový audit tržeb hotov!")
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Celkem chyb a neshod", f"{len(df_neshody_final)} ks")
                col2.metric("Úspěšně spárováno", f"{len(df_matched)} ks")
                col3.metric("Vyrušená vnitřní storna", f"{len(df_storna_final)} ks")
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_neshody_final.to_excel(writer, sheet_name='HLAVNÍ ROZDÍLY A CHYBY', index=False)
                    if not df_matched.empty:
                        df_matched.to_excel(writer, sheet_name='V pořádku spárované (1-1)', index=False)
                    if not df_storna_final.empty:
                        df_storna_final.to_excel(writer, sheet_name='Vnitřní storna v kase', index=False)
                        
                excel_data = output.getvalue()
                st.subheader("2. Krok: Stažení kompletního auditu")
                st.download_button(
                    label="📥 Stáhnout pročištěný Excel pro účetní",
                    data=excel_data,
                    file_name="Kompletni_Audit_Trzeb_Datona.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Chyba při hloubkové analýze: {str(e)}")
