import pandas as pd
from collections import defaultdict
import os

# import modules from project structure
from utils.excel_exporter import export_solution_to_excel
from utils.data_loader import InputData, get_dataframe_from_excel
from utils.file_handler import save_metaheuristic_result
from metaheuristic.tabu_search import TabuSearchSolver

def load_input(excel_path):
    print(f"Loading data from {excel_path}...")
    data = InputData()

    # 1. STYLES (Item codes & SAM)
    df_s = get_dataframe_from_excel(excel_path, 'style_input', header=0).dropna(subset=['Style'])
    data.set['setS'] = df_s['Style'].astype(str).unique().tolist()

    # map style parameters
    data.param['paramSAM'] = df_s.set_index('Style')['SAM'].to_dict()
    data.param['paramTfabprocess'] = df_s.set_index('Style')['Fabric Processing Time'].fillna(1).to_dict()
    data.param['paramTprodfinish'] = df_s.set_index('Style')['Product Finishing Time'].fillna(1).to_dict()

    # default late penalty is 50 if missing
    data.param['Plate'] = {s: 50.0 for s in data.set['setS']}

    # 2. LINES (Sewing lines & manpower)
    df_l = get_dataframe_from_excel(excel_path, 'line_input', header=0).dropna(subset=['Line'])
    data.set['setL'] = df_l['Line'].astype(str).unique().tolist()
    data.param['paramN'] = df_l.set_index('Line')['Sewer'].to_dict()
    data.param['paramExp0'] = df_l.set_index('Line')['Experience'].fillna(0).to_dict()

    # initial status (Y0) - which style each line is currently sewing
    data.param['paramY0'] = {}
    for _, row in df_l.iterrows():
        line_str = str(row['Line'])
        current_style = row.get('Current Style')
        if pd.notna(current_style):
            for s in data.set['setS']:
                data.param['paramY0'][(line_str, s)] = 1 if s == current_style else 0

    # 3. TIME HORIZON (Work schedule)
    df_t = get_dataframe_from_excel(excel_path, 'line_date_input', header=1)

    # check required columns and try alternative header if necessary
    expected_cols = {'Date', 'Line'}
    if not expected_cols.issubset(df_t.columns):
        if not df_t.empty:
            first_row_vals = df_t.iloc[0].astype(str).str.strip().tolist()
            if 'Date' in first_row_vals and 'Line' in first_row_vals:
                df_t.columns = first_row_vals
                df_t = df_t[1:]
            else:
                df_t_alt = get_dataframe_from_excel(excel_path, 'line_date_input', header=0)
                if expected_cols.issubset(df_t_alt.columns):
                    df_t = df_t_alt

    if not expected_cols.issubset(df_t.columns):
        raise KeyError(f"Sheet 'line_date_input' missing required columns. Found: {list(df_t.columns)}")

    df_t = df_t.dropna(subset=['Date', 'Line'])
    df_t['Date'] = pd.to_datetime(df_t['Date'], errors='coerce').dt.date

    unique_dates = sorted(df_t['Date'].dropna().unique())
    data.set['setT'] = list(range(1, len(unique_dates) + 1))
    data.set['real_dates'] = unique_dates
    date_map = {d: i+1 for i, d in enumerate(unique_dates)}

    data.param['paramH'] = defaultdict(float)
    for _, row in df_t.iterrows():
        l_str = str(row['Line'])
        if l_str in data.set['setL'] and row['Date'] in date_map:
            data.param['paramH'][(l_str, date_map[row['Date']])] = float(row.get('Working Hour', 0))

    # 4. DEMAND & FABRIC
    df_d = get_dataframe_from_excel(excel_path, 'order_input', header=0)
    data.param['paramD'] = defaultdict(float)
    data.param['paramF'] = defaultdict(float)

    def parse_date(val):
        dt = pd.to_datetime(val, errors='coerce')
        if pd.isna(dt): return None
        return dt.date()

    last_t = data.set['setT'][-1] if data.set['setT'] else 1

    for _, row in df_d.iterrows():
        s = str(row.get('Style2'))
        qty = row.get('Sum')

        if s in data.set['setS'] and pd.notna(qty):
            qty_val = float(qty)

            # handle demand (D)
            d_date = parse_date(row.get('Exf-SX'))
            t_d = date_map.get(d_date, last_t)
            data.param['paramD'][(s, t_d)] += qty_val

            # fabric arrival (F) half first day, half second day
            f_start_date = parse_date(row.get('Fabric start ETA RG'))
            t_start = date_map.get(f_start_date)

            if t_start:
                data.param['paramF'][(s, t_start)] += qty_val * 0.5
                t_next = t_start + 1
                if t_next <= last_t:
                    data.param['paramF'][(s, t_next)] += qty_val * 0.5
                else:
                    data.param['paramF'][(s, t_start)] += qty_val * 0.5
            else:
                data.param['paramF'][(s, last_t)] += qty_val

    # 5. CAPABILITIES & LEARNING PARAMETERS
    df_cap = get_dataframe_from_excel(excel_path, 'enable_style_line_input', header=0)
    df_lexp = get_dataframe_from_excel(excel_path, 'line_style_input', header=1)

    data.param['paramYenable'] = {}
    data.param['paramLexp'] = {}

    for l in data.set['setL']:
        row_cap = df_cap[df_cap.iloc[:, 0].astype(str) == l]
        row_exp = df_lexp[df_lexp.iloc[:, 0].astype(str) == l]

        for s in data.set['setS']:
            if not row_cap.empty and s in df_cap.columns:
                data.param['paramYenable'][(l, s)] = int(row_cap.iloc[0][s])
            else:
                data.param['paramYenable'][(l, s)] = 0

            if not row_exp.empty and s in df_lexp.columns:
                data.param['paramLexp'][(l, s)] = float(row_exp.iloc[0][s])
            else:
                data.param['paramLexp'][(l, s)] = 0.0

    # 6. LEARNING CURVE (build table and lookup -> O(1))
    lc_sheets = ['learning_curve_input', 'Learning Curve', 'LC_Input', 'Sheet1']
    df_lc = pd.DataFrame()

    for sheet in lc_sheets:
        df_lc = get_dataframe_from_excel(
            excel_path,
            sheet,
            expected_columns=['Experience', 'Efficiency'],
            autodetect_header=True
        )
        if not df_lc.empty:
            break

    if not df_lc.empty and {'Experience', 'Efficiency'}.issubset(df_lc.columns):
        df_lc.columns = df_lc.columns.str.strip().str.title()

        df_lc = df_lc.dropna(subset=['Experience', 'Efficiency']).sort_values('Experience')
        breakpoints = list(range(1, len(df_lc) + 1))

        data.set['setBP'] = breakpoints
        data.param['paramXp'] = dict(zip(breakpoints, df_lc['Experience'].astype(float)))
        data.param['paramFp'] = dict(zip(breakpoints, df_lc['Efficiency'].astype(float)))
        print("-> Learning Curve loaded successfully.")
    else:
        print("-> No Learning Curve data found. Using defaults.")
        data.set['setBP'] = [1, 2, 3]
        data.param['paramXp'] = {1: 1.0, 2: 10.0, 3: 17.0}
        data.param['paramFp'] = {1: 0.32, 2: 0.66, 3: 0.80}

    # 7. OTHER DEFAULTS
    data.set['setSsame'] = []  # style pairs considered the same (keep experience when switching)
    data.set['setSP'] = [(s1, s2) for s1 in data.set['setS'] for s2 in data.set['setS']]

    # initial inventory
    data.param['paramI0fabric'] = {s: 0 for s in data.set['setS']}
    data.param['paramI0product'] = {s: 0 for s in data.set['setS']}
    data.param['paramB0'] = {s: 0 for s in data.set['setS']}

    # costs
    data.param['Csetup'] = 150.0  # setup change cost
    data.param['Rexp'] = 10.0    # experience reward

    return data

if __name__ == "__main__":
    EXCEL_FILE = 'Small.xlsx'
    RESULT_DIR = 'result'

    if os.path.exists(EXCEL_FILE):
        # 1. Load Data
        try:
            input_data = load_input(EXCEL_FILE)
        except Exception as e:
            print(f"Error reading Excel file: {e}")
            exit(1)

        # 2. Solve (run algorithm)
        print("\n--- Run ---")
        # max_iter: maximum number of iterations
        # max_time: maximum run time in seconds
        solver = TabuSearchSolver(input_data, max_iter=5000, tabu_tenure=15, max_time=600)
        best_solution = solver.solve()

        # 3. Save & report
        os.makedirs(RESULT_DIR, exist_ok=True)

        # save binary result (pickle) for reuse when needed
        save_metaheuristic_result(best_solution, filename="result.pkl", folder=RESULT_DIR)

        # print summary to console
        solver.print_solution_summary()

        # export report to Excel
        report_path = os.path.join(RESULT_DIR, 'Production_Plan_Report.xlsx')
        print(f"Exporting report to: {report_path}...")

        # exporter will now read 'real_dates' from input_data
        export_solution_to_excel(best_solution, input_data, filename=report_path)

        print("Done!")

    else:
        print(f"Error: input data file '{EXCEL_FILE}' not found.")
