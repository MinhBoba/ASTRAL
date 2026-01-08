import pandas as pd
from collections import defaultdict
import os

# Import các module từ cấu trúc dự án
from utils.excel_exporter import export_solution_to_excel 
from utils.data_loader import InputData, get_dataframe_from_excel
from utils.file_handler import save_metaheuristic_result
from metaheuristic.tabu_search import TabuSearchSolver

def load_input(excel_path):
    print(f"Loading data from {excel_path}...")
    data = InputData()
    
    # 1. STYLES (Danh sách mã hàng & SAM)
    df_s = get_dataframe_from_excel(excel_path, 'style_input', header=0).dropna(subset=['Style'])
    data.set['setS'] = df_s['Style'].astype(str).unique().tolist()
    
    # Map các tham số Style
    data.param['paramSAM'] = df_s.set_index('Style')['SAM'].to_dict()
    data.param['paramTfabprocess'] = df_s.set_index('Style')['Fabric Processing Time'].fillna(1).to_dict()
    data.param['paramTprodfinish'] = df_s.set_index('Style')['Product Finishing Time'].fillna(1).to_dict()
    
    # Giá phạt trễ mặc định là 50 nếu không có
    data.param['Plate'] = {s: 50.0 for s in data.set['setS']}

    # 2. LINES (Chuyền may & Nhân sự)
    df_l = get_dataframe_from_excel(excel_path, 'line_input', header=0).dropna(subset=['Line'])
    data.set['setL'] = df_l['Line'].astype(str).unique().tolist()
    data.param['paramN'] = df_l.set_index('Line')['Sewer'].to_dict()
    data.param['paramExp0'] = df_l.set_index('Line')['Experience'].fillna(0).to_dict()
    
    # Thiết lập trạng thái ban đầu (Y0) - Line đang may mã nào
    data.param['paramY0'] = {}
    for _, row in df_l.iterrows():
        line_str = str(row['Line'])
        current_style = row.get('Current Style')
        if pd.notna(current_style):
            for s in data.set['setS']:
                data.param['paramY0'][(line_str, s)] = 1 if s == current_style else 0

    # 3. TIME HORIZON (Lịch làm việc)
    # Cố gắng đọc header ở dòng 2 (index 1), nếu không được thì thử dòng 1 (index 0)
    df_t = get_dataframe_from_excel(excel_path, 'line_date_input', header=1)

    # Kiểm tra cột, nếu không khớp thì thử đọc lại với header=0
    expected_cols = {'Date', 'Line'}
    if not expected_cols.issubset(df_t.columns):
        if not df_t.empty:
            # Kiểm tra xem dòng dữ liệu đầu tiên có phải là header không
            first_row_vals = df_t.iloc[0].astype(str).str.strip().tolist()
            if 'Date' in first_row_vals and 'Line' in first_row_vals:
                df_t.columns = first_row_vals
                df_t = df_t[1:]
            else:
                df_t_alt = get_dataframe_from_excel(excel_path, 'line_date_input', header=0)
                if expected_cols.issubset(df_t_alt.columns):
                    df_t = df_t_alt

    if not expected_cols.issubset(df_t.columns):
        raise KeyError(f"Sheet 'line_date_input' thiếu cột quan trọng. Tìm thấy: {list(df_t.columns)}")

    df_t = df_t.dropna(subset=['Date', 'Line'])
    # Convert cột Date sang datetime.date
    df_t['Date'] = pd.to_datetime(df_t['Date'], errors='coerce').dt.date
    
    # Tạo setT (1, 2, 3...) và lưu lại ngày thực tế để mapping sau này
    unique_dates = sorted(df_t['Date'].dropna().unique())
    data.set['setT'] = list(range(1, len(unique_dates) + 1))
    data.set['real_dates'] = unique_dates  # Quan trọng cho việc xuất Excel
    date_map = {d: i+1 for i, d in enumerate(unique_dates)}
    
    # Giờ làm việc (paramH)
    data.param['paramH'] = defaultdict(float)
    for _, row in df_t.iterrows():
        l_str = str(row['Line'])
        if l_str in data.set['setL'] and row['Date'] in date_map:
            data.param['paramH'][(l_str, date_map[row['Date']])] = float(row.get('Working Hour', 0))

    # 4. DEMAND & FABRIC (Đơn hàng & Vải)
    df_d = get_dataframe_from_excel(excel_path, 'order_input', header=0)
    data.param['paramD'] = defaultdict(float)
    data.param['paramF'] = defaultdict(float)
    
    # Helper để parse ngày an toàn từ dòng dữ liệu
    def parse_date(val):
        dt = pd.to_datetime(val, errors='coerce')
        if pd.isna(dt): return None
        if hasattr(dt, 'date'): return dt.date()
        if hasattr(dt, 'dt'): return dt.dt.date
        return None

    last_t = data.set['setT'][-1] if data.set['setT'] else 1

    for _, row in df_d.iterrows():
        s = row.get('Style2') # Tên cột dựa theo file mẫu của bạn
        qty = row.get('Sum')
        
        if s in data.set['setS'] and pd.notna(qty):
            qty_val = float(qty)
            
            # Xử lý Demand (D) - Ngày xuất hàng (Exf-SX)
            d_date = parse_date(row.get('Exf-SX'))
            t_d = date_map.get(d_date, last_t) # Nếu ngày nằm ngoài lịch, gán vào ngày cuối
            data.param['paramD'][(s, t_d)] += qty_val
            
            # Xử lý Fabric (F) - Ngày vải về (Fabric start ETA RG)
            f_date = parse_date(row.get('Fabric start ETA RG'))
            t_f = date_map.get(f_date, last_t)
            data.param['paramF'][(s, t_f)] += qty_val

    # 5. CAPABILITIES & LEARNING PARAMETERS
    df_cap = get_dataframe_from_excel(excel_path, 'enable_style_line_input', header=0)
    df_lexp = get_dataframe_from_excel(excel_path, 'line_style_input', header=1)
    
    data.param['paramYenable'] = {}
    data.param['paramLexp'] = {}
    
    for l in data.set['setL']:
        # Lọc dòng tương ứng với Line
        row_cap = df_cap[df_cap.iloc[:, 0].astype(str) == l]
        row_exp = df_lexp[df_lexp.iloc[:, 0].astype(str) == l]
        
        for s in data.set['setS']:
            # Yenable: Line có được phép may Style này không
            if not row_cap.empty and s in df_cap.columns:
                data.param['paramYenable'][(l, s)] = int(row_cap.iloc[0][s])
            else:
                 data.param['paramYenable'][(l, s)] = 0
            
            # Lexp: Kinh nghiệm ban đầu của Line với Style (nếu có)
            if not row_exp.empty and s in df_lexp.columns:
                data.param['paramLexp'][(l, s)] = float(row_exp.iloc[0][s])
            else:
                data.param['paramLexp'][(l, s)] = 0.0

    # 6. LEARNING CURVE (Đã dùng Smart Loader)
    # Thử tìm trong các sheet tên phổ biến
    lc_sheets = ['learning_curve_input', 'Learning Curve', 'LC_Input', 'Sheet1']
    df_lc = pd.DataFrame()

    for sheet in lc_sheets:
        # Gọi loader thông minh: Tự tìm dòng chứa cột 'Experience' và 'Efficiency'
        df_lc = get_dataframe_from_excel(
            excel_path, 
            sheet, 
            expected_columns=['Experience', 'Efficiency'], 
            autodetect_header=True
        )
        if not df_lc.empty:
            break
            
    if not df_lc.empty and {'Experience', 'Efficiency'}.issubset(df_lc.columns):
        # Chuẩn hóa tên cột lần nữa cho chắc (Loader đã clean rồi nhưng check lại title case)
        df_lc.columns = df_lc.columns.str.strip().str.title()
        
        df_lc = df_lc.dropna(subset=['Experience', 'Efficiency']).sort_values('Experience')
        breakpoints = list(range(1, len(df_lc) + 1))
        
        data.set['setBP'] = breakpoints
        data.param['paramXp'] = dict(zip(breakpoints, df_lc['Experience'].astype(float)))
        data.param['paramFp'] = dict(zip(breakpoints, df_lc['Efficiency'].astype(float)))
        print("-> Đã load Learning Curve thành công.")
    else:
        print("-> Cảnh báo: Không tìm thấy dữ liệu Learning Curve. Sử dụng mặc định.")
        data.set['setBP'] = [1, 2, 3]
        data.param['paramXp'] = {1: 1.0, 2: 10.0, 3: 17.0}
        data.param['paramFp'] = {1: 0.32, 2: 0.66, 3: 0.80}

    # 7. OTHER DEFAULTS
    data.set['setSsame'] = [] # Cặp style giống nhau (giữ nguyên kinh nghiệm khi chuyển đổi)
    data.set['setSP'] = [(s1, s2) for s1 in data.set['setS'] for s2 in data.set['setS']]
    
    # Tồn kho ban đầu
    data.param['paramI0fabric'] = {s: 1e6 for s in data.set['setS']} # Vải vô hạn (giả định nếu thiếu input)
    data.param['paramI0product'] = {s: 0 for s in data.set['setS']}
    data.param['paramB0'] = {s: 0 for s in data.set['setS']} # Backlog ban đầu
    
    # Chi phí
    data.param['Csetup'] = 150.0  # Chi phí đổi mã
    data.param['Rexp'] = 1.0      # Thưởng tích lũy kinh nghiệm
    
    return data

if __name__ == "__main__":
    EXCEL_FILE = 'Small.xlsx' 
    RESULT_DIR = 'result'
    
    if os.path.exists(EXCEL_FILE):
        # 1. Load Data
        try:
            input_data = load_input(EXCEL_FILE)
        except Exception as e:
            print(f"Lỗi khi đọc file Excel: {e}")
            exit(1)
        
        # 2. Solve (Chạy thuật toán)
        print("\n--- BẮT ĐẦU TỐI ƯU HÓA ---")
        # max_iter: Số vòng lặp tối đa
        # max_time: Thời gian chạy tối đa (giây)
        solver = TabuSearchSolver(input_data, max_iter=5000, tabu_tenure=15, max_time=600)
        best_solution = solver.solve()
        
        # 3. Save & Report
        os.makedirs(RESULT_DIR, exist_ok=True)
        
        # Lưu kết quả dạng nhị phân (pickle) để dùng lại nếu cần
        save_metaheuristic_result(best_solution, filename = "result.pkl", folder=RESULT_DIR)
        
        # In tóm tắt ra màn hình
        solver.print_solution_summary()
        
        # Xuất ra Excel báo cáo
        report_path = os.path.join(RESULT_DIR, 'Production_Plan_Report.xlsx')
        print(f"Đang xuất báo cáo ra file: {report_path}...")
        
        # Hàm export đã được cập nhật logic nhận 'real_dates' từ input_data
        export_solution_to_excel(best_solution, input_data, filename=report_path)
        
        print("Hoàn tất!")
        
    else:
        print(f"Lỗi: Không tìm thấy file dữ liệu đầu vào '{EXCEL_FILE}'")
