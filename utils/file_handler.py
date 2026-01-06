import pickle
import json
import os
import datetime

# Thử import Pyomo, nếu không có thì vẫn chạy được Metaheuristic
try:
    import pyomo.environ as pyo
    from pyomo.environ import value
    HAS_PYOMO = True
except ImportError:
    HAS_PYOMO = False

# --- GENERAL HANDLERS (JSON & PICKLE) ---

def json_converter(o):
    """Helper để convert các kiểu dữ liệu datetime/numpy khi lưu JSON."""
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.isoformat()
    if hasattr(o, 'item'): # Numpy scalar
        return o.item()
    return str(o)

def save_metaheuristic_result(result, filename="result.pkl", folder='result', format='pickle'):
    """
    Lưu kết quả chạy thuật toán.
    format: 'pickle' (nhị phân, giữ nguyên object) hoặc 'json' (text, dễ đọc).
    """
    os.makedirs(folder, exist_ok=True)
    file_path = os.path.join(folder, filename)
    
    if format == 'pickle':
        with open(file_path, "wb") as f:
            pickle.dump(result, f)
    
    elif format == 'json':
        # Đổi đuôi file nếu cần
        if not filename.endswith('.json'): 
            file_path = file_path.replace('.pkl', '.json')
            
        with open(file_path, "w", encoding='utf-8') as f:
            # skipkeys=True để bỏ qua các key là tuple (JSON chỉ cho key là string)
            # Tuy nhiên tuple key (Line, Date) rất quan trọng, ta nên convert key thành string
            json_ready_result = _convert_keys_to_string(result)
            json.dump(json_ready_result, f, indent=4, default=json_converter, ensure_ascii=False)
            
    print(f"Đã lưu kết quả vào: {file_path}")

def load_metaheuristic_result(filename="result.pkl", folder='result'):
    file_path = os.path.join(folder, filename)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File {file_path} không tồn tại.")
        
    with open(file_path, "rb") as f:
        return pickle.load(f)

def _convert_keys_to_string(data):
    """Đệ quy chuyển đổi dictionary key từ tuple/int sang string để lưu JSON."""
    if isinstance(data, dict):
        new_dict = {}
        for k, v in data.items():
            new_key = str(k)
            new_dict[new_key] = _convert_keys_to_string(v)
        return new_dict
    elif isinstance(data, list):
        return [_convert_keys_to_string(i) for i in data]
    else:
        return data

# --- PYOMO HANDLERS ---

def save_model_solution(model, filename="solution.pkl", folder='result'):
    if not HAS_PYOMO:
        print("Cảnh báo: Không tìm thấy thư viện Pyomo. Không thể lưu model.")
        return

    os.makedirs(folder, exist_ok=True)
    file_path = os.path.join(folder, filename)
    
    data = {var.name: {idx: value(var[idx]) for idx in var} for var in model.component_objects(pyo.Var)}
    
    with open(file_path, "wb") as f:
        pickle.dump(data, f)
    print(f"Pyomo solution saved to {file_path}")

def load_model_solution(model, filename="solution.pkl", folder='result'):
    if not HAS_PYOMO: return
    
    file_path = os.path.join(folder, filename)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File {file_path} not found.")

    with open(file_path, "rb") as f:
        data = pickle.load(f)
        
    for var in model.component_objects(pyo.Var):
        if var.name in data:
            for idx in var:
                if idx in data[var.name]:
                    var[idx].set_value(data[var.name][idx])
    print(f"Loaded solution from {file_path}")

# Alias
save_solution_to_pickle = save_model_solution