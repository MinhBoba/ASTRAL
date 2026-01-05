import pandas as pd
from collections import defaultdict
import os

from utils.data_loader import InputData, get_dataframe_from_excel
from utils.file_handler import save_metaheuristic_result
from metaheuristic.tabu_search import TabuSearchSolver

def load_input(excel_path):
    print(f"Loading data from {excel_path}...")
    data = InputData()
    
    # 1. Styles
    df_s = read_excel_sheet(excel_path, 'style_input', header=0).dropna(subset=['Style'])
    data.set['setS'] = df_s['Style'].astype(str).unique().tolist()
    data.param['paramSAM'] = df_s.set_index('Style')['SAM'].to_dict()
    data.param['paramTfabprocess'] = df_s.set_index('Style')['Fabric Processing Time'].fillna(1).to_dict()
    data.param['paramTprodfinish'] = df_s.set_index('Style')['Product Finishing Time'].fillna(1).to_dict()
    data.param['Plate'] = {s: 50.0 for s in data.set['setS']}

    # 2. Lines
    df_l = read_excel_sheet(excel_path, 'line_input', header=0).dropna(subset=['Line'])
    data.set['setL'] = df_l['Line'].astype(str).unique().tolist()
    data.param['paramN'] = df_l.set_index('Line')['Sewer'].to_dict()
    data.param['paramExp0'] = df_l.set_index('Line')['Experience'].fillna(0).to_dict()
    
    # Initial Setup (Y0)
    data.param['paramY0'] = {}
    for _, row in df_l.iterrows():
        if pd.notna(row.get('Current Style')):
            for s in data.set['setS']:
                data.param['paramY0'][(str(row['Line']), s)] = 1 if s == row['Current Style'] else 0

    # 3. Time Horizon (Header is on row 2 -> index 1)
    df_t = read_excel_sheet(excel_path, 'line_date_input', header=1).dropna(subset=['Date', 'Line'])
    df_t['Date'] = pd.to_datetime(df_t['Date'], errors='coerce').dt.date
    unique_dates = sorted(df_t['Date'].dropna().unique())
    data.set['setT'] = list(range(1, len(unique_dates) + 1))
    date_map = {d: i+1 for i, d in enumerate(unique_dates)}
    
    data.param['paramH'] = defaultdict(float)
    for _, row in df_t.iterrows():
        if str(row['Line']) in data.set['setL'] and row['Date'] in date_map:
            data.param['paramH'][(str(row['Line']), date_map[row['Date']])] = float(row.get('Working Hour', 0))

    # 4. Demand
    df_d = read_excel_sheet(excel_path, 'order_input', header=0)
    data.param['paramD'] = defaultdict(float)
    for _, row in df_d.iterrows():
        s, qty = row.get('Style2'), row.get('Sum') # Adjusted col names based on your JSON
        if s in data.set['setS'] and pd.notna(qty):
            dd = pd.to_datetime(row.get('Exf-SX'), errors='coerce').dt.date
            t = date_map.get(dd, data.set['setT'][-1])
            data.param['paramD'][(s, t)] += float(qty)

    # 5. Capabilities & Experience Matrix
    df_cap = read_excel_sheet(excel_path, 'enable_style_line_input', header=0)
    df_lexp = read_excel_sheet(excel_path, 'line_style_input', header=1)
    
    data.param['paramYenable'] = {}
    data.param['paramLexp'] = {}
    
    for l in data.set['setL']:
        # Capability
        row_cap = df_cap[df_cap.iloc[:, 0].astype(str) == l]
        # Experience
        row_exp = df_lexp[df_lexp.iloc[:, 0].astype(str) == l]
        
        for s in data.set['setS']:
            # Enable
            if not row_cap.empty and s in df_cap.columns:
                data.param['paramYenable'][(l, s)] = int(row_cap.iloc[0][s])
            else:
                 data.param['paramYenable'][(l, s)] = 0
            
            # Lexp
            if not row_exp.empty and s in df_lexp.columns:
                data.param['paramLexp'][(l, s)] = float(row_exp.iloc[0][s])
            else:
                data.param['paramLexp'][(l, s)] = 0.0

    # Defaults
    data.set['setBP'] = [1, 2]
    data.param['paramXp'] = {1: 0, 2: 100}
    data.param['paramFp'] = {1: 0.5, 2: 1.0}
    data.set['setSsame'] = []
    data.set['setSP'] = [(s1, s2) for s1 in data.set['setS'] for s2 in data.set['setS']]
    data.param['paramI0fabric'] = {s: 1e6 for s in data.set['setS']}
    data.param['paramI0product'] = {s: 0 for s in data.set['setS']}
    data.param['paramB0'] = {s: 0 for s in data.set['setS']}
    data.param['Csetup'] = 150.0
    data.param['Rexp'] = 1.0
    
    return data

if __name__ == "__main__":
    EXCEL_FILE = 'StandardInput.xlsx' # Rename your file to this
    
    if os.path.exists(EXCEL_FILE):
        # 1. Load
        input_data = load_input(EXCEL_FILE)
        
        # 2. Solve
        print("Solving...")
        solver = TabuSearchSolver(input_data, max_iter=100, tabu_tenure=10)
        best_solution = solver.solve()
        
        # 3. Save & Report
        save_metaheuristic_result(best_solution, filename="result.pkl", replace=True)
        solver.print_solution_summary()
    else:
        print(f"File {EXCEL_FILE} not found.")
