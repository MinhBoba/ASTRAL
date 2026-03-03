import pandas as pd
import openpyxl
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

@dataclass
class InputData:
    set: Dict[str, Any] = field(default_factory=dict)
    param: Dict[str, Any] = field(default_factory=dict)

def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names by stripping whitespace and removing odd characters."""
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
    Smart Excel reader.

    Parameters
    ----------
    expected_columns : list
        List of required column names (e.g. ['Experience', 'Efficiency']).
        Used to detect the header row when ``autodetect_header`` is True.
    autodetect_header : bool
        If True, scans the first 20 rows for a header containing the expected columns.
    """
    try:
        # straightforward read if no header detection required
        if not autodetect_header:
            df = pd.read_excel(file_path, sheet_name=sheet_name, header=header)
            return clean_column_names(df)

        # 1. read raw data without header
        df_raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
        
        if df_raw.empty:
            return pd.DataFrame()

        # normalize expected_columns to lowercase for comparison
        required_cols = set(c.lower() for c in (expected_columns or []))
        
        found_header_idx = -1
        
        # 2. scan first 20 rows
        for idx, row in df_raw.head(20).iterrows():
            # take row values as lowercase strings
            row_vals = set(str(v).strip().lower() for v in row.values)
            
            # check if this row contains all required columns
            if required_cols.issubset(row_vals):
                found_header_idx = idx
                break
        
        # 3. handle result
        if found_header_idx != -1:
            # reload the file using the detected header row
            df = pd.read_excel(file_path, sheet_name=sheet_name, header=found_header_idx)
            print(f"   -> [Loader] found header for sheet '{sheet_name}' at row {found_header_idx + 1}")
        else:
            # fallback: if not found, use default header
            print(f"   -> [Loader] Warning: columns {expected_columns} not found in '{sheet_name}'. Using default header.")
            df = pd.read_excel(file_path, sheet_name=sheet_name, header=0)

        return clean_column_names(df)

    except ValueError:
        # common error: sheet does not exist
        print(f"   -> [Loader] skipping: sheet '{sheet_name}' not found.")
        return pd.DataFrame()
    except Exception as e:
        print(f"   -> [Loader] error reading file {file_path}, sheet {sheet_name}: {e}")
        return pd.DataFrame()