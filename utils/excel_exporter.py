import pandas as pd
import xlsxwriter

def generate_hex_colors(names):
    palette = [
        '#E6194B', '#3CB44B', '#FFE119', '#4363D8', '#F58231', 
        '#911EB4', '#46FBEB', '#F032E6', '#BCF60C', '#FABEBE', 
        '#008080', '#E6BEFF', '#9A6324', '#FFFAC8', '#800000'
    ]
    color_map = {}
    for i, name in enumerate(names):
        color_map[name] = palette[i % len(palette)]
    return color_map

def get_date(date_obj):
    """Chuyển đổi ngày sang thứ tiếng Việt (Th 2, Th 3...)"""
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return days[date_obj.weekday()]

def export_solution_to_excel(solution, input_data, filename="Line_Schedule.xlsx"):
    # 1. Khởi tạo dữ liệu cơ bản
    dates = sorted(list(input_data.set['setT']))
    all_styles = sorted(list(input_data.set['setS']))
    lines = sorted(list(input_data.set['setL']))
    
    # Tạo header Ngày và Thứ ---
    date_headers = []
    day_headers = []
    
    if 'real_dates' in input_data.set and len(input_data.set['real_dates']) == len(dates):
        # Sắp xếp real_dates khớp với dates (setT)
        # real_dates đã được load đúng thứ tự hoặc là list
        real_dates_list = sorted(list(input_data.set['real_dates']))
        
        for d in real_dates_list:
            date_headers.append(d.strftime("%d/%m")) # Định dạng ngày/tháng
            day_headers.append(get_date(d)) # Lấy thứ (Th 2...)
    else:
        # Fallback nếu không có ngày thực
        date_headers = [f"T{t}" for t in dates]
        day_headers = [""] * len(dates)
    
    style_colors = generate_hex_colors(all_styles)

    with pd.ExcelWriter(filename, engine='xlsxwriter') as writer:
        workbook = writer.book
        
        # Format styles
        header_fmt = workbook.add_format({'bold': True, 'align': 'center', 'bg_color': '#D3D3D3', 'border': 1})
        day_fmt = workbook.add_format({'bold': True, 'align': 'center', 'bg_color': '#EFEFEF', 'border': 1, 'font_size': 9}) # Format cho dòng Thứ
        center_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1})
        num_fmt = workbook.add_format({'align': 'center', 'border': 1, 'num_format': '#,##0'})
        pct_fmt = workbook.add_format({'align': 'center', 'border': 1, 'num_format': '0%'})
        
        # --- SHEET 1: LINE-SCHEDULE (TỔNG HỢP) ---
        rows_main = []
        for line in lines:
            for r_type in ['Style', 'Qty', 'Eff', 'Exp', 'MaxEff']:
                row_data = {'Line': line, 'Type': r_type}
                for i, t in enumerate(dates):
                    # Dùng index i để map đúng cột
                    col_key = date_headers[i] 
                    
                    if r_type == 'Style':
                        val = solution['assignment'].get((line, t), "")
                    elif r_type == 'Qty':
                        style = solution['assignment'].get((line, t))
                        val = solution['production'].get((line, style, t), 0) if style else 0
                    elif r_type == 'Eff':
                        val = solution['efficiency'].get((line, t), 0)
                    elif r_type == 'Exp':
                        val = solution['experience'].get((line, t), 0)
                    else: # MaxEff
                        val = solution['efficiency'].get((line, t), 0) # Logic tạm
                    row_data[col_key] = val
                rows_main.append(row_data)

        df_main = pd.DataFrame(rows_main)
        # Không write header mặc định của pandas để tự control vị trí
        df_main.to_excel(writer, sheet_name='Line-Schedule', index=False, startrow=2, header=False)
        
        ws_main = writer.sheets['Line-Schedule']

        # 1. Viết Header Ngày (Dòng 0)
        ws_main.write(0, 0, "Line", header_fmt)
        ws_main.write(0, 1, "Type", header_fmt)
        for i, val in enumerate(date_headers):
            ws_main.write(0, i + 2, val, header_fmt)

        # 2. Viết Header Thứ (Dòng 1)
        ws_main.write(1, 0, "", header_fmt)
        ws_main.write(1, 1, "Thứ", day_fmt)
        for i, val in enumerate(day_headers):
            ws_main.write(1, i + 2, val, day_fmt)

        # 3. Format Dữ liệu
        # Style formats cache
        style_formats = {s: workbook.add_format({'bg_color': c, 'font_color': 'white', 'bold': 1, 'border': 1, 'align': 'center'}) 
                         for s, c in style_colors.items()}

        # Duyệt qua từng block Line (5 dòng mỗi block)
        start_row_idx = 2 
        for i in range(0, len(df_main), 5):
            current_row = start_row_idx + i
            
            # Merge cột Line
            ws_main.merge_range(current_row, 0, current_row + 4, 0, df_main.iloc[i]['Line'], center_fmt)
            types = ['Style', 'Qty', 'Eff', 'Exp', 'MaxEff']
            for idx, t_name in enumerate(types):
                ws_main.write(current_row + idx, 1, t_name, center_fmt)

            # Format các cột dữ liệu ngày tháng
            for t_idx in range(len(dates)):
                col_idx = t_idx + 2
                
                # Style row
                s_val = df_main.iloc[i, t_idx + 2] # Data offset là 2 do dataframe cấu trúc dictionary
                fmt = style_formats.get(s_val, center_fmt) if s_val else center_fmt
                ws_main.write(current_row, col_idx, s_val, fmt) 
                
                # Qty row
                ws_main.write(current_row + 1, col_idx, df_main.iloc[i+1, t_idx + 2], num_fmt)
                # Eff row
                ws_main.write(current_row + 2, col_idx, df_main.iloc[i+2, t_idx + 2], pct_fmt)
                # Exp row (số thường)
                ws_main.write(current_row + 3, col_idx, df_main.iloc[i+3, t_idx + 2], workbook.add_format({'align': 'center', 'border': 1, 'num_format': '0.0'}))
                # MaxEff row
                ws_main.write(current_row + 4, col_idx, df_main.iloc[i+4, t_idx + 2], pct_fmt)

        # Freeze panes để cố định 2 dòng đầu và 2 cột đầu
        ws_main.freeze_panes(2, 2)

        # --- SHEET TIẾP THEO: STYLE SHEETS ---
        for style in all_styles:
            style_rows = []
            
            # ... (Logic tính toán tồn kho giữ nguyên) ...
            inv_fab = input_data.param.get('paramI0fabric', {}).get(style, 0)
            inv_fg = input_data.param.get('paramI0product', {}).get(style, 0)
            backlog = input_data.param.get('paramB0', {}).get(style, 0)

            data_map = {m: {} for m in [
                'Demand', 'Fabric Receiving', 'Beg. Inv Fabric', 'Producing', 
                'End. Inv Fabric', 'Beg. Inv FG', 'Shipping', 'End. Inv FG', 'Backlog'
            ]}

            for t in dates:
                demand_t = input_data.param.get('paramD', {}).get((style, t), 0)
                fab_recv_t = input_data.param.get('paramF', {}).get((style, t), 0)
                prod_t = sum(solution['production'].get((l, style, t), 0) for l in lines)
                
                data_map['Beg. Inv Fabric'][t] = inv_fab
                inv_fab = inv_fab + fab_recv_t - prod_t
                data_map['End. Inv Fabric'][t] = inv_fab
                
                data_map['Beg. Inv FG'][t] = inv_fg
                total_available = inv_fg + prod_t
                total_needed = demand_t + backlog
                
                ship_t = min(total_available, total_needed)
                inv_fg = total_available - ship_t
                backlog = total_needed - ship_t
                
                data_map['Demand'][t] = demand_t
                data_map['Fabric Receiving'][t] = fab_recv_t
                data_map['Producing'][t] = prod_t
                data_map['Shipping'][t] = ship_t
                data_map['End. Inv FG'][t] = inv_fg
                data_map['Backlog'][t] = backlog

            # Tạo rows cho DataFrame
            for metric, vals in data_map.items():
                row = {'Metric': metric}
                for i, t in enumerate(dates):
                    # Dùng header ngày làm key
                    row[date_headers[i]] = vals[t]
                style_rows.append(row)

            df_style = pd.DataFrame(style_rows)
            sheet_name = f"S_{str(style)[:28]}"
            
            # Xuất dữ liệu bắt đầu từ dòng 2
            df_style.to_excel(writer, sheet_name=sheet_name, index=False, startrow=2, header=False)
            
            ws_s = writer.sheets[sheet_name]
            style_header_fmt = workbook.add_format({'bold': True, 'bg_color': style_colors.get(style, '#D7E4BC'), 
                                                   'font_color': 'white', 'border': 1, 'align': 'center'})
            
            # 1. Viết Header Ngày (Dòng 0)
            ws_s.write(0, 0, "Metric", style_header_fmt)
            for col_num, value in enumerate(date_headers):
                ws_s.write(0, col_num + 1, value, style_header_fmt)

            # 2. Viết Header Thứ (Dòng 1)
            ws_s.write(1, 0, "Thứ", day_fmt)
            for col_num, value in enumerate(day_headers):
                ws_s.write(1, col_num + 1, value, day_fmt)

            # Format column width & data
            ws_s.set_column(0, 0, 22)
            ws_s.set_column(1, len(dates), 10, num_fmt)
            
            # Freeze pane cho sheet con
            ws_s.freeze_panes(2, 1)

    print(f"Hoàn tất xuất file: {filename}")
