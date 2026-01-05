import pickle
import os
import pyomo.environ as pyo
from pyomo.environ import value

# ==========================================
# PART 1: PYOMO MODEL HANDLERS
# ==========================================

def save_model_solution(model, filename="solution.pkl", folder='result', replace=False):
    """
    Save variable values from a Pyomo Model after a solve.
    """
    if not os.path.exists(folder):
        os.makedirs(folder)

    file_path = os.path.join(folder, filename)
    
    if not replace and os.path.exists(file_path):
        raise FileExistsError(f"The file {file_path} already exists. Cannot overwrite.")
        
    # Extract data from model variables
    data = {var.name: {idx: value(var[idx]) for idx in var} for var in model.component_objects(pyo.Var)}
    
    with open(file_path, "wb") as f:
        pickle.dump(data, f)
    print(f"Pyomo model solution saved to {file_path}")

def load_model_solution(model, filename="solution.pkl", folder='result'):
    """
    Load variable values into a Pyomo Model (warm-start).
    """
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


# ==========================================
# PART 2: GENERAL / METAHEURISTIC HANDLERS
# ==========================================

def save_metaheuristic_result(result, filename="metaheuristic.pkl", folder='result', replace=False):
    """
    Save generic results (dict, list, object) to a pickle file.
    """
    if not os.path.exists(folder):
        os.makedirs(folder)

    file_path = os.path.join(folder, filename)
    
    if not replace and os.path.exists(file_path):
        raise FileExistsError(f"The file {file_path} already exists. Cannot overwrite.")
        
    with open(file_path, "wb") as f:
        pickle.dump(result, f)
    print(f"Result saved to {file_path}")

def load_metaheuristic_result(filename="metaheuristic.pkl", folder='result'):
    """
    Load generic results from a pickle file.
    """
    file_path = os.path.join(folder, filename)
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File {file_path} not found.")
        
    with open(file_path, "rb") as f:
        return pickle.load(f)
