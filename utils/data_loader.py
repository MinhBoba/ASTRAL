import pandas as pd
import openpyxl
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

@dataclass
class InputData:
    set: Dict[str, Any] = field(default_factory=dict)
    param: Dict[str, Any] = field(default_factory=dict)

def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Chuẩn hóa tên cột: Xóa khoảng trắng thừa, ký tự lạ."""
    if df.columns is not None:
        cols = (
            df.columns.astype(str)
            .str.replace('\xa0', ' ', regex=False)  # Remove non-breaking space
            .str.replace('\u200b', '', regex=False) # Remove zero-width space
            .str.strip()
        )
        df.columns = cols
    return df

def get_dataframe_from_excel(
    file_path: str, 
    sheet_name: str, 
    header: int = 0, 
    expected_columns: Optional[List[str]] = None,
    autodetect_header: bool = False
) -> pd.DataFrame:
    """
    Đọc Excel thông minh.
    
    Parameters
    ----------
    expected_columns : list
        Danh sách các cột BẮT BUỘC phải có (ví dụ: ['Experience', 'Efficiency']).
        Dùng để tìm dòng header nếu autodetect_header=True.
    autodetect_header : bool
        Nếu True, sẽ quét 20 dòng đầu để tìm dòng chứa expected_columns.
    """
    try:
        # Nếu không cần tự động dò header, đọc bình thường
        if not autodetect_header:
            df = pd.read_excel(file_path, sheet_name=sheet_name, header=header)
            return clean_column_names(df)

        # --- LOGIC TỰ ĐỘNG DÒ HEADER ---
        # 1. Đọc dữ liệu thô (không header)
        df_raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
        
        if df_raw.empty:
            return pd.DataFrame()

        # Chuẩn hóa expected_columns về chữ thường để so sánh
        required_cols = set(c.lower() for c in (expected_columns or []))
        
        found_header_idx = -1
        
        # 2. Quét 20 dòng đầu
        for idx, row in df_raw.head(20).iterrows():
            # Lấy giá trị dòng, chuyển về string lowercase
            row_vals = set(str(v).strip().lower() for v in row.values)
            
            # Kiểm tra xem dòng này có chứa tất cả cột mong muốn không
            if required_cols.issubset(row_vals):
                found_header_idx = idx
                break
        
        # 3. Xử lý kết quả
        if found_header_idx != -1:
            # Reload lại file với header chính xác
            df = pd.read_excel(file_path, sheet_name=sheet_name, header=found_header_idx)
            print(f"   -> [Loader] Tìm thấy header sheet '{sheet_name}' tại dòng {found_header_idx + 1}")
        else:
            # Fallback: Nếu không tìm thấy, thử dùng header=0 hoặc header=1
            print(f"   -> [Loader] Cảnh báo: Không tìm thấy cột {expected_columns} trong '{sheet_name}'. Đọc mặc định.")
            df = pd.read_excel(file_path, sheet_name=sheet_name, header=0)

        return clean_column_names(df)

    except ValueError:
        # Lỗi thường gặp: Sheet không tồn tại
        print(f"   -> [Loader] Bỏ qua: Không tìm thấy sheet '{sheet_name}'.")
        return pd.DataFrame()
    except Exception as e:
        print(f"   -> [Loader] Lỗi đọc file {file_path}, sheet {sheet_name}: {e}")
        return pd.DataFrame()