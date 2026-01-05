import pandas as pd
import openpyxl
from dataclasses import dataclass

def get_dataframe_from_table(file_path, sheet_name, table_name):
    """
    Reads a specific table from an Excel sheet into a Pandas DataFrame.
    """
    # Load the workbook and specified sheet
    workbook = openpyxl.load_workbook(file_path, data_only=True)
    sheet = workbook[sheet_name]

    # Get the table by its name
    if table_name not in sheet.tables:
        raise ValueError(f"Table '{table_name}' not found in sheet '{sheet_name}'")
    
    table = sheet.tables[table_name]

    # Extract the range of the table using the `ref` attribute
    table_range = table.ref

    # Extract data from the table range using list comprehension
    data = [[cell.value for cell in row] for row in sheet[table_range]]

    # Create a DataFrame with headers and data
    # Assuming the first row of the table range is the header
    if len(data) > 1:
        df = pd.DataFrame(data[1:], columns=data[0])
    else:
        df = pd.DataFrame(columns=data[0]) # Empty table with headers

    return df

@dataclass
class InputData:
    def __post_init__(self):
        self.set = {}
        self.param = {}
