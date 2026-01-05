import pandas as pd
import openpyxl
from dataclasses import dataclass, field
from typing import Dict, Any

@dataclass
class InputData:
    
    set: Dict[str, Any] = field(default_factory=dict)
    param: Dict[str, Any] = field(default_factory=dict)

def get_dataframe_from_excel(file_path, sheet_name, header=0):
    """
    Hàm đọc dữ liệu từ Excel linh hoạt hơn:
    - Không bắt buộc phải là Table.
    - Cho phép chọn dòng làm header (vì dữ liệu của bạn có sheet header ở dòng 2).
    """
    try:
        # Dùng pandas đọc trực tiếp cho mạnh mẽ
        df = pd.read_excel(file_path, sheet_name=sheet_name, header=header)

        # Chuẩn hoá tên cột: chuyển thành str, loại bỏ NBSP và khoảng trắng ngoài, rút gọn nhiều khoảng trắng
        if df.columns is not None:
            cols = (
                df.columns.astype(str)
                .str.replace('\xa0', ' ', regex=False)
                .str.replace('\u200b', '', regex=False)
                .str.replace('\s+', ' ', regex=True)
                .str.strip()
            )
            df.columns = cols

        return df
    except ValueError as e:
        print(f"Cảnh báo: Không đọc được sheet '{sheet_name}'. Lỗi: {e}")
        return pd.DataFrame()
    except Exception as e:
        print(f"Lỗi khi đọc file {file_path}: {e}")
        return pd.DataFrame()

def get_dataframe_from_table(file_path, sheet_name, table_name):
    workbook = openpyxl.load_workbook(file_path, data_only=True)
    sheet = workbook[sheet_name]
    if table_name not in sheet.tables:
        raise ValueError(f"Table '{table_name}' not found")
    table = sheet.tables[table_name]
    table_range = table.ref
    data = [[cell.value for cell in row] for row in sheet[table_range]]
    if len(data) > 1:
        df = pd.DataFrame(data[1:], columns=data[0])
    else:
        df = pd.DataFrame(columns=data[0])
    return df
