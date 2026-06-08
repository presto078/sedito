import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="SedíTo! - Párování tržeb", page_icon="💳", layout="centered")

st.title("💳 SedíTo! – Kontrola a párování tržeb")
st.write("Chytré odsouhlasení pokladny Datona vůči bankovním terminálům a Amexu.")

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

if st.button("🚀 Spustit chytrou analýzu", use_container_width=True):
    if not file_pokpol or not file_karty or not file_amex:
        st.error("Prosím, nahrajte všechny 3 požadované soubory.")
    else:
        with st.spinner("Provádím vnitřní kontrolu pokladny a párování s bankou..."):
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
                
                # --- VNITŘNÍ PÁROVÁNÍ POKLADNY (Prodeje vs Storna) ---
                pokpol['vnitrni_storno'] = False
                pokpol_pos = pokpol[pokpol['Cena'] > 0].copy().sort_values('dt')
                pokpol_neg = pokpol[pokpol['Cena'] < 0].copy().sort_values('dt')
                
                storna_rows = []
                # Pro každé storno najdeme v pokladně jeho plusové dvojče ve stejný den
                for n_idx, n_row in pokpol_neg.iterrows():
                    target_amt = abs(n_row['Cena'])
                    # Hledáme plusový doklad se stejnou částkou, který ještě nebyl stornován a je blízko časově
                    candidates = pokpol_pos[(pokpol_pos['Cena'] == target_amt) & (~pokpol_pos['vnitrni_storno'])]
                    if not candidates.empty:
                        time_diffs = (candidates['dt'] - n_row['dt']).abs()
                        best_p_idx = time_diffs.idxmin()
                        pokpol_pos.loc[best_p_idx, 'vnitrni_storno'] = True
                        
                        storna_rows.append({
                            'Datum Pokladna': n_row['Datum a Čas'],
                            'Doklad CZAK (Storno)': n_row['CZAK'],
                            'Částka Storna': n_row['Cena'],
                            'Původní Doklad CZAK': pokpol_pos.loc[best_p_idx, 'CZAK'],
                            'Stav': 'Interně vyrušeno (V pořádku)'
                        })
                    else:
                        storna_rows.append({
                            'Datum Pokladna': n_row['Datum a Čas'],
                            'Doklad CZAK (Storno)': n_row['CZAK'],
                            'Částka Storna': n_row['Cena'],
                            'Původní Doklad CZAK': 'Nenalezen',
                            'Stav': 'Sirotčí storno (Chybí plusový doklad)'
                        })
                
                # Pro párování s bankou použijeme POUZE ta plusová data, která nebyla interně stornována!
                pokpol_for_bank = pokpol_pos[~pokpol_pos['vnitrni_storno']].copy()
                
                # --- PÁROVÁNÍ S BANKOVNÍM TERMINÁLEM ---
                matched_list = []
                unmatched_pokpol = []
                
                for idx, row in pokpol_for_bank.iterrows():
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
                
                # 1. Chybí na terminálu (Skutečné ztráty)
                df_chybi = pd.DataFrame(unmatched_pokpol)
                if not df_chybi.empty:
                    df_chybi = df_chybi[['Datum a Čas', 'CZAK', 'Cena', 'Platební karta']].rename(
                        columns={'Datum a Čas': 'Datum Pokladna', 'Cena': 'Částka Pokladna', 'Platební karta': 'Očekávaná Karta'}
                    )
                else:
                    df_chybi = pd.DataFrame(columns=['Datum Pokladna', 'CZAK', 'Částka Pokladna', 'Očekávaná Karta'])
                
                # 2. Přebývá na terminálu
                df_prebyva = terminal_all[~terminal_all['matched']].copy()
                if not df_prebyva.empty:
                    df_prebyva = df_prebyva[['Čas transakce', 'Částka brutto', 'Zdroj', 'Číslo karty', 'Typ karty']].rename(
                        columns={'Čas transakce': 'Čas Terminál', 'Částka brutto': 'Částka Terminál'}
                    )
                else:
                    df_prebyva = pd.DataFrame(columns=['Čas Terminál', 'Částka Terminál', 'Zdroj', 'Číslo karty', 'Typ karty'])
                
                # 3. Interní storna
                df_storna_final = pd.DataFrame(storna_rows)
                if df_storna_final.empty:
                    df_storna_final = pd.DataFrame(columns=['Datum Pokladna', 'Doklad CZAK (Storno)', 'Částka Storna', 'Původní Doklad CZAK', 'Stav'])
                
                # 4. V pořádku spárované
                df_matched = pd.DataFrame(matched_list)
                
                # Zobrazení výsledků na webu
                st.success("Chytrá analýza dokončena!")
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Skutečně chybí v bance", f"{len(df_chybi)} ks")
                col2.metric("Přebývá na terminálu", f"{len(df_prebyva)} ks")
                col3.metric("Vyrušená storna v kase", f"{len(df_storna_final)} ks")
                
                # Vygenerování Excelu do paměti
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_chybi.to_excel(writer, sheet_name='Skutečně chybí v bance', index=False)
                    df_prebyva.to_excel(writer, sheet_name='Přebývá na terminálu', index=False)
                    df_storna_final.to_excel(writer, sheet_name='Vyrušená storna v kase', index=False)
                    if not df_matched.empty:
                        df_matched.to_excel(writer, sheet_name='V pořádku spárované (1-1)', index=False)
                
                excel_data = output.getvalue()
                
                st.subheader("2. Krok: Stažení pročištěného přehledu")
                st.download_button(
                    label="📥 Stáhnout opravený Excel",
                    data=excel_data,
                    file_name="Cisty_Prehled_Trzeb.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
                
            except Exception as e:
                st.error(f"Chyba při analýze dat: {str(e)}")
