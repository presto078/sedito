import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Párování platebních terminálů", page_icon="💳", layout="centered")

st.title("💳 Kontrola a párování tržeb pro účetní")
st.write("Nahrajte soubory z pokladny a terminálů. Systém je automaticky porovná a vygeneruje přehledný Excel s výsledky.")

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

# 2. Zpracování dat po kliknutí
if st.button("🚀 Spustit analýzu dat", use_container_width=True):
    if not file_pokpol or not file_karty or not file_amex:
        st.error("Prosím, nahrajte všechny 3 požadované soubory.")
    else:
        with st.spinner("Pracuji na párování transakcí..."):
            try:
                # Načtení dat (výpisy z terminálů mají 5 řádků nad hlavičkou)
                pokpol = load_df(file_pokpol, skip_rows=0)
                karty = load_df(file_karty, skip_rows=5)
                amex = load_df(file_amex, skip_rows=5)
                
                # Převod částek na čísla
                pokpol['Cena'] = pd.to_numeric(pokpol['Cena'], errors='coerce')
                karty['Částka brutto'] = pd.to_numeric(karty['Částka brutto'], errors='coerce')
                amex['Částka brutto'] = pd.to_numeric(amex['Částka brutto'], errors='coerce')
                
                # Převod datumů
                pokpol['dt'] = pd.to_datetime(pokpol['Datum a Čas'], errors='coerce', dayfirst=True)
                karty['dt'] = pd.to_datetime(karty['Čas transakce'], errors='coerce', dayfirst=True)
                amex['dt'] = pd.to_datetime(amex['Čas transakce'], errors='coerce', dayfirst=True)
                
                # Sjednocení terminálů
                karty['Zdroj'] = 'Karty'
                amex['Zdroj'] = 'Amex'
                
                term_cols = ['Částka brutto', 'Čas transakce', 'dt', 'Zdroj', 'Číslo karty', 'Typ karty']
                for col in term_cols:
                    if col not in karty.columns: karty[col] = ''
                    if col not in amex.columns: amex[col] = ''
                    
                terminal_all = pd.concat([karty[term_cols], amex[term_cols]], ignore_index=True)
                
                # Rozdělení pokladny na prodeje a storna
                pokpol_pos = pokpol[pokpol['Cena'] > 0].copy()
                pokpol_neg = pokpol[pokpol['Cena'] < 0].copy()
                
                if not pokpol_pos.empty: pokpol_pos = pokpol_pos.sort_values('dt')
                if not terminal_all.empty: terminal_all = terminal_all.sort_values('dt')
                    
                terminal_all['matched'] = False
                matched_list = []
                unmatched_pokpol = []
                
                # Párovací algoritmus 1:1
                for idx, row in pokpol_pos.iterrows():
                    amt = row['Cena']
                    candidates = terminal_all[(terminal_all['Částka brutto'] == amt) & (~terminal_all['matched'])]
                    
                    if not candidates.empty and pd.notna(row['dt']):
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
                
                # Sestavení výsledných tabulek
                df_chybi = pd.DataFrame(unmatched_pokpol)
                if not df_chybi.empty:
                    df_chybi = df_chybi[['Datum a Čas', 'CZAK', 'Cena', 'Platební karta']].rename(
                        columns={'Datum a Čas': 'Datum Pokladna', 'Cena': 'Částka Pokladna', 'Platební karta': 'Očekávaná Karta'}
                    )
                else:
                    df_chybi = pd.DataFrame(columns=['Datum Pokladna', 'CZAK', 'Částka Pokladna', 'Očekávaná Karta'])
                    
                df_prebyva = terminal_all[~terminal_all['matched']].copy()
                if not df_prebyva.empty:
                    df_prebyva = df_prebyva[['Čas transakce', 'Částka brutto', 'Zdroj', 'Číslo karty', 'Typ karty']].rename(
                        columns={'Čas transakce': 'Čas Terminál', 'Částka brutto': 'Částka Terminál'}
                    )
                else:
                    df_prebyva = pd.DataFrame(columns=['Čas Terminál', 'Částka Terminál', 'Zdroj', 'Číslo karty', 'Typ karty'])
                    
                if not pokpol_neg.empty:
                    df_storna = pokpol_neg[['Datum a Čas', 'CZAK', 'Cena', 'Platební karta']].rename(
                        columns={'Datum a Čas': 'Datum Pokladna', 'Cena': 'Částka Storna'}
                    )
                else:
                    df_storna = pd.DataFrame(columns=['Datum Pokladna', 'CZAK', 'Částka Storna', 'Platební karta'])
                    
                df_matched = pd.DataFrame(matched_list)
                
                # Zobrazení rychlého přehledu přímo na webu
                st.success("Analýza hotova!")
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Chybí na terminálu (ks)", len(df_chybi))
                col2.metric("Přebývá na terminálu (ks)", len(df_prebyva))
                col3.metric("V pořádku spárováno (ks)", len(df_matched))
                
                # Příprava Excelu do paměti ke stažení
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_chybi.to_excel(writer, sheet_name='Chybí na terminálu (Ztráty)', index=False)
                    df_prebyva.to_excel(writer, sheet_name='Přebývá na terminálu', index=False)
                    df_storna.to_excel(writer, sheet_name='Storna v Pokladně', index=False)
                    df_matched.to_excel(writer, sheet_name='Správně spárované (1-1)', index=False)
                
                excel_data = output.getvalue()
                
                st.subheader("2. Krok: Stažení výsledků")
                st.download_button(
                    label="📥 Stáhnout výsledný Excel",
                    data=excel_data,
                    file_name="Vysledek_Kontroly_Trzeb.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
                
            except Exception as e:
                st.error(f"Došlo k chybě při zpracování souborů: {str(e)}")