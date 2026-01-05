# utils/excel_exporter.py

import pandas as pd
import random

def generate_hex_colors(names):
    """Tạo bảng màu cố định cho từng Style để giống hình ảnh minh họa."""
    # Các màu tương tự như trong file Excel mẫu (Red, Green, Yellow, Blue, Purple...)
    palette = [
        '#FF0000', # Red
        '#00FF00', # Green
        '#FFFF00', # Yellow
        '#0000FF', # Blue
        '#800080', # Purple
        '#FFA500', # Orange
        '#00FFFF', # Cyan
        '#FFC0CB', # Pink
        '#A52A2A', # Brown
        '#808080'  # Grey
    ]
    color_map = {}
    for i, name in enumerate(names):
        color_map[name] = palette[i % len(palette)]
    return color_map

def export_solution_to_excel(solution, input_data, filename="Line_Schedule.xlsx"):
    """
    Xuất kết quả lập kế hoạch ra Excel với định dạng Gantt chart.
    """
    
    # 1. Chuẩn bị dữ liệu ngày tháng (Header)
    # Vì input_data lưu setT là 1, 2, 3... ta cần map lại ngày thực tế nếu có
    # Ở đây ta sẽ lấy ngày từ input gốc nếu có thể, hoặc dùng T1, T2...
    # Giả sử chúng ta truyền list các ngày thực tế vào hoặc tạo dummy
    dates = sorted(list(input_data.set['setT']))
    # Nếu muốn hiển thị ngày dạng "Jun 01", ta cần map từ index. 
    # Tạm thời dùng index T1, T2... hoặc mapping nếu main.py cung cấp.
    date_headers = [f"T{t}" for t in dates] 

    # 2. Xây dựng cấu trúc dữ liệu cho DataFrame
    rows = []
    
    # Lấy danh sách Style để tạo màu
    all_styles = sorted(list(input_data.set['setS']))
    style_colors = generate_hex_colors(all_styles)
    
    lines = sorted(list(input_data.set['setL']))
    
    for line in lines:
        # Tạo 5 dòng cho mỗi Line: Style, Qty, Eff, Exp, MaxEff
        row_style = {'Line': line, 'Type': 'Style'}
        row_qty = {'Line': line, 'Type': 'Qty'}
        row_eff = {'Line': line, 'Type': 'Eff'}
        row_exp = {'Line': line, 'Type': 'Exp'}
        row_maxeff = {'Line': line, 'Type': 'MaxEff'}
        
        for t in dates:
            col_name = f"T{t}" # Tên cột khớp với header
            
            # Lấy dữ liệu từ solution
            style = solution['assignment'].get((line, t))
            
            # Qty: Tổng sản lượng của line đó trong ngày t
            # (Lưu ý: solution['production'] lưu key (line, style, t))
            qty = 0
            if style:
                qty = solution['production'].get((line, style, t), 0)
            
            eff = solution['efficiency'].get((line, t), 0)
            exp = solution['experience'].get((line, t), 0)
            
            # MaxEff: Trong hình mẫu, MaxEff thường giống Eff hoặc là Eff tối đa lý thuyết
            # Ta tạm lấy bằng Eff để hiển thị
            max_eff = eff 

            # Fill data
            row_style[col_name] = style if style else ""
            row_qty[col_name] = qty if qty > 0 else 0
            row_eff[col_name] = eff
            row_exp[col_name] = exp
            row_maxeff[col_name] = max_eff

        rows.extend([row_style, row_qty, row_eff, row_exp, row_maxeff])

    # 3. Tạo DataFrame
    df = pd.DataFrame(rows)
    
    # Sắp xếp lại cột: Line, Type, rồi đến các ngày
    cols = ['Line', 'Type'] + [f"T{t}" for t in dates]
    df = df[cols]
    
    # 4. Xuất ra Excel với định dạng (XlsxWriter)
    with pd.ExcelWriter(filename, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Line-Schedule', index=False)
        workbook = writer.book
        worksheet = writer.sheets['Line-Schedule']
        
        # --- Định dạng ---
        
        # Format chung
        center_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1})
        num_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1, 'num_format': '#,##0'})
        percent_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1, 'num_format': '0%'})
        
        # Format tiêu đề
        header_fmt = workbook.add_format({'bold': True, 'align': 'center', 'bg_color': '#D3D3D3', 'border': 1})
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_fmt)

        # Định dạng style màu sắc (Text màu trắng, nền màu Style)
        style_formats = {}
        for style_name, color_code in style_colors.items():
            style_formats[style_name] = workbook.add_format({
                'bg_color': color_code,
                'font_color': '#FFFFFF',
                'bold': True,
                'align': 'center',
                'border': 1
            })

        # Duyệt qua từng dòng để format và merge cells
        # Dữ liệu bắt đầu từ row 1 (row 0 là header)
        for i in range(0, len(df), 5):
            # i là index của dòng 'Style' trong nhóm 5 dòng của 1 Line
            
            # 1. Merge cột Line (Line Name)
            # Merge từ dòng i+1 đến i+5 (trong Excel index là 1-based, nhưng write dùng 0-based)
            # xlsxwriter: merge_range(first_row, first_col, last_row, last_col, data, cell_format)
            # Row index trong Excel = i + 1 (header)
            
            start_row = i + 1
            end_row = i + 5
            line_name = df.iloc[i]['Line']
            
            worksheet.merge_range(start_row, 0, end_row, 0, line_name, center_fmt)
            
            # 2. Format cột Type
            worksheet.write(start_row, 1, "Style", center_fmt)
            worksheet.write(start_row + 1, 1, "Qty", center_fmt)
            worksheet.write(start_row + 2, 1, "Eff", center_fmt)
            worksheet.write(start_row + 3, 1, "Exp", center_fmt)
            worksheet.write(start_row + 4, 1, "MaxEff", center_fmt)
            
            # 3. Format dữ liệu các cột ngày
            for col_idx in range(2, len(cols)):
                # Dòng Style: Tô màu nền dựa vào tên Style
                style_val = df.iloc[i, col_idx]
                if style_val and style_val in style_formats:
                    worksheet.write(start_row, col_idx, style_val, style_formats[style_val])
                else:
                    worksheet.write(start_row, col_idx, style_val, center_fmt)
                
                # Dòng Qty: Số nguyên
                qty_val = df.iloc[i+1, col_idx]
                worksheet.write(start_row + 1, col_idx, qty_val, num_fmt)
                
                # Dòng Eff: Phần trăm
                eff_val = df.iloc[i+2, col_idx]
                worksheet.write(start_row + 2, col_idx, eff_val, percent_fmt)
                
                # Dòng Exp: Số nguyên/thập phân
                exp_val = df.iloc[i+3, col_idx]
                worksheet.write(start_row + 3, col_idx, exp_val, center_fmt)
                
                # Dòng MaxEff: Phần trăm
                maxeff_val = df.iloc[i+4, col_idx]
                worksheet.write(start_row + 4, col_idx, maxeff_val, percent_fmt)
                
        # Set column width
        worksheet.set_column(0, 0, 15) # Cột Line rộng hơn
        worksheet.set_column(1, 1, 10) # Cột Type
        worksheet.set_column(2, len(cols)-1, 12) # Các cột ngày

    print(f"Đã xuất file báo cáo: {filename}")
