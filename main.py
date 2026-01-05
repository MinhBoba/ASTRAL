import pandas as pd
from collections import defaultdict
import os
from utils.excel_exporter import export_solution_to_excel 
from utils.data_loader import InputData, get_dataframe_from_excel
from utils.file_handler import save_metaheuristic_result
from metaheuristic.tabu_search import TabuSearchSolver

def load_input(excel_path):
    print(f"Loading data from {excel_path}...")
    data = InputData()
    
    # 1. Styles
    df_s = get_dataframe_from_excel(excel_path, 'style_input', header=0).dropna(subset=['Style'])
    data.set['setS'] = df_s['Style'].astype(str).unique().tolist()
    data.param['paramSAM'] = df_s.set_index('Style')['SAM'].to_dict()
    data.param['paramTfabprocess'] = df_s.set_index('Style')['Fabric Processing Time'].fillna(1).to_dict()
    data.param['paramTprodfinish'] = df_s.set_index('Style')['Product Finishing Time'].fillna(1).to_dict()
    data.param['Plate'] = {s: 50.0 for s in data.set['setS']}

    # 2. Lines
    df_l = get_dataframe_from_excel(excel_path, 'line_input', header=0).dropna(subset=['Line'])
    data.set['setL'] = df_l['Line'].astype(str).unique().tolist()
    data.param['paramN'] = df_l.set_index('Line')['Sewer'].to_dict()
    data.param['paramExp0'] = df_l.set_index('Line')['Experience'].fillna(0).to_dict()
    
    # Initial Setup (Y0)
    data.param['paramY0'] = {}
    for _, row in df_l.iterrows():
        if pd.notna(row.get('Current Style')):
            for s in data.set['setS']:
                data.param['paramY0'][(str(row['Line']), s)] = 1 if s == row['Current Style'] else 0

    # 3. Time Horizon: try to read with header=1 but be resilient if the real header is the first row
    df_t = get_dataframe_from_excel(excel_path, 'line_date_input', header=1)

    # If expected columns not found, check if the first data row contains header names
    if not set(['Date', 'Line']).issubset(df_t.columns):
        if not df_t.empty:
            first_row_vals = df_t.iloc[0].astype(str).str.strip().tolist()
            if 'Date' in first_row_vals and 'Line' in first_row_vals:
                df_t.columns = first_row_vals
                df_t = df_t[1:]
            else:
                # fallback: try reading with header=0
                df_t_alt = get_dataframe_from_excel(excel_path, 'line_date_input', header=0)
                if set(['Date', 'Line']).issubset(df_t_alt.columns):
                    df_t = df_t_alt

    if not set(['Date', 'Line']).issubset(df_t.columns):
        print(f"Sheet 'line_date_input' columns: {list(df_t.columns)}")
        raise KeyError("Expected columns 'Date' and 'Line' not found in 'line_date_input' sheet")

    df_t = df_t.dropna(subset=['Date', 'Line'])
    df_t['Date'] = pd.to_datetime(df_t['Date'], errors='coerce').dt.date
    unique_dates = sorted(df_t['Date'].dropna().unique())
    data.set['setT'] = list(range(1, len(unique_dates) + 1))
    date_map = {d: i+1 for i, d in enumerate(unique_dates)}
    data.set['real_dates'] = unique_dates 
    
    data.param['paramH'] = defaultdict(float)
    for _, row in df_t.iterrows():
        if str(row['Line']) in data.set['setL'] and row['Date'] in date_map:
            data.param['paramH'][(str(row['Line']), date_map[row['Date']])] = float(row.get('Working Hour', 0))

    # 4. Demand
    df_d = get_dataframe_from_excel(excel_path, 'order_input', header=0)
    data.param['paramD'] = defaultdict(float)
    for _, row in df_d.iterrows():
        s, qty = row.get('Style2'), row.get('Sum') # Adjusted col names based on your JSON
        if s in data.set['setS'] and pd.notna(qty):
            # Robust parse: pd.to_datetime may return a Timestamp (scalar) when iterating rows.
            dt_parsed = pd.to_datetime(row.get('Exf-SX'), errors='coerce')
            if pd.isna(dt_parsed):
                dd = None
            else:
                # If Timestamp or datetime, use .date(); if Series-like, handle .dt
                if hasattr(dt_parsed, 'date'):
                    try:
                        dd = dt_parsed.date()
                    except Exception:
                        dd = None
                elif hasattr(dt_parsed, 'dt'):
                    try:
                        dd = dt_parsed.dt.date
                    except Exception:
                        dd = None
                else:
                    dd = None

            t = date_map.get(dd, data.set['setT'][-1])
            data.param['paramD'][(s, t)] += float(qty)

    # 4b. Fabric arrivals per style and time (paramF)
    data.param['paramF'] = defaultdict(float)
    for _, row in df_d.iterrows():
        s, qty = row.get('Style2'), row.get('Sum')
        if s in data.set['setS'] and pd.notna(qty):
            dt_fab = pd.to_datetime(row.get('Fabric start ETA RG'), errors='coerce')
            if pd.isna(dt_fab):
                dd_f = None
            else:
                if hasattr(dt_fab, 'date'):
                    try:
                        dd_f = dt_fab.date()
                    except Exception:
                        dd_f = None
                elif hasattr(dt_fab, 'dt'):
                    try:
                        dd_f = dt_fab.dt.date
                    except Exception:
                        dd_f = None
                else:
                    dd_f = None

            t_f = date_map.get(dd_f, data.set['setT'][-1])
            data.param['paramF'][(s, t_f)] += float(qty)

    # 5. Capabilities & Experience Matrix
    df_cap = get_dataframe_from_excel(excel_path, 'enable_style_line_input', header=0)
    df_lexp = get_dataframe_from_excel(excel_path, 'line_style_input', header=1)
    
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
    EXCEL_FILE = 'StandardInput.xlsx' 
    
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
        
        # Cập nhật lại list ngày thực tế nếu có trong input_data
        # Nếu load_input chưa lưu 'real_dates', ta tạo giả lập hoặc sửa load_input như trên.
        if 'real_dates' in input_data.set:
            # Map index T (1, 2...) sang string ngày ("May 29")
            # Hàm export cần sửa nhẹ để nhận label ngày, hoặc ta sửa input.set['setT'] tạm thời
            # Tuy nhiên, cách tốt nhất là sửa file excel_exporter.py một chút để nhận mapping.
            # Nhưng để đơn giản, ta format lại ngày thành string ngay đây:
            date_labels = [d.strftime("%b %d") for d in input_data.set['real_dates']]
            
            pass
        
        export_solution_to_excel(best_solution, input_data, filename="Production_Plan_Report.xlsx")
        
    else:
        print(f"File {EXCEL_FILE} not found.")
