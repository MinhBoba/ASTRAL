# Production Scheduling with Learning Curves (Make-Color Model)

## 1. Project Overview

**Make-Color** represents an advanced optimization solution for the Apparel Production Scheduling Problem. It manages the assignment of sewing lines to garment styles, balancing:

*   **Dynamic Learning Curves:** Efficiency rises with experience.
*   **Material Constraints:** Production depends on fabric arrival.
*   **Delivery Deadlines:** Penalties for late deliveries.
*   **Setup Costs:** Costs for switching styles.

The system uses two approaches:
1.  **Exact Method (MILP):** Pyomo-based Mixed-Integer Linear Programming.
2.  **Metaheuristic:** Tabu Search combined with ALNS.

---

## 2. Directory Structure

```text
minhboba-astral/
├── main.py                  # Entry Point (Data loading, Solver execution)
├── metaheuristic/           # Optimization Logic
│   ├── __init__.py
│   ├── ALNS_operator.py     # Simulation Evaluator
│   ├── neighbor_generator.py# Move Operators
│   ├── oscillation_strategy.py
│   └── tabu_search.py       # Main Loop
├── models/                  # Pyomo MILP Model
│   ├── init.py
│   └── pyomo_model.py
├── utils/                   # Utilities
│   ├── data_loader.py       # Excel Reader
│   ├── excel_exporter.py    # Report Generator
│   └── file_handler.py
└── Small.xlsx               # Input Data

---

## 3. Mathematical Model (MILP)

This section details the formulation used in `models/pyomo_model.py`.

### 3.1. Sets and Indices

*   $l \in \mathcal{L}$: Production lines.
*   $s \in \mathcal{S}$: Garment styles.
*   $t \in \mathcal{T}$: Periods $\{1, \dots, T\}$.
*   $p \in \mathcal{BP}$: Break-points of learning curve.
*   $\mathcal{SP}$: Pairs of dissimilar styles (require setup).

### 3.2. Parameters

*   $D_{s,t}$: Demand.
*   $F_{s,t}$: Fabric receipts.
*   $H_{l,t}$: Working hours.
*   $SAM_s$: Standard allowed minutes.
*   $C^{\text{setup}}$: Setup cost.
*   $P_s^{\text{late}}$: Late penalty.
*   $R^{\text{exp}}$: Experience reward.
*   $\delta_t$: Discount factor.

### 3.3. Decision Variables

*   **Binary:** $Y_{l,s,t}$ (Assignment), $Z_{l,s',s,t}$ (Switch), $Change_{l,t}$ (Reset), $U_{l,t}$ (Utilization).
*   **Continuous:** $P_{l,s,t}$ (Production), $Exp_{l,t}$ (Experience), $Eff_{l,t}$ (Efficiency), $B_{s,t}$ (Backlog).

### 3.4. Objective Function

Minimize Total Discounted Cost $\mathcal{Z}$:

$$
\mathcal{Z} = C^{\text{setup}} \sum_{l, s', s, t} Z_{l,s',s,t} \delta_t + \sum_{s, t} P_s^{\text{late}} B_{s,t} \delta_t - R^{\text{exp}} \sum_{l, t} Exp_{l,t} \delta_t
$$

---

### 3.5. Constraints

#### 1. Fabric Flow and Usage

**Fabric Inventory (Beginning):**

$$
I_{s,t}^{\text{fab,B}} = I_{s,t-1}^{\text{fab,E}} + F_{s, t-T_s^{\text{fab}}}
$$

*(Note: For $t=1$, use initial inventory)*

**Fabric Inventory (End):**

$$
I_{s,t}^{\text{fab,E}} = I_{s,t}^{\text{fab,B}} - \sum_{l \in \mathcal{L}} P_{l,s,t}
$$

**Material Availability:**

$$
\sum_{l \in \mathcal{L}} P_{l,s,t} \le I_{s,t}^{\text{fab,B}}
$$

#### 2. Finished-Goods Flow

**Product Inventory:**

$$
I_{s,t}^{\text{prod,E}} = I_{s,t}^{\text{prod,B}} - Ship_{s,t}
$$

**Shipment Limit:**

$$
Ship_{s,t} \le I_{s,t}^{\text{prod,B}}
$$

#### 3. Backlog Recursion

**Backlog Balance:**

$$
B_{s,t} = B_{s,t-1} + D_{s,t} - Ship_{s,t}
$$

#### 4. Line-Style Assignment

**Single Assignment:**

$$
\sum_{s \in \mathcal{S}} Y_{l,s,t} = 1
$$

**Capability & Production Link:**

$$
Y_{l,s,t} \le Y_{l,s}^{\text{allow}}
$$

$$
P_{l,s,t} \le M \cdot Y_{l,s,t}
$$

#### 5. Change-Over Logic

**Detect Switch ($Z=1$):**

$$
Z_{l,s',s,t} \ge Y_{l,s',t-1} + Y_{l,s,t} - 1
$$

**Aggregate Change:**

$$
Change_{l,t} = \sum_{(s',s) \in \mathcal{SP}} Z_{l,s',s,t}
$$

#### 6. Utilization Trigger (Experience Gain)

Line gains experience ($U=1$) only if production output meets threshold:

**Lower Bound:**

$$
\sum_{s} SAM_s P_{l,s,t} - 0.5 H_{l,t} 60 N_l Eff_{l,t} + M(1 - U_{l,t}) \ge 0
$$

**Upper Bound:**

$$
\sum_{s} SAM_s P_{l,s,t} - 0.5 H_{l,t} 60 N_l Eff_{l,t} - \varepsilon \le M U_{l,t}
$$

#### 7. Experience Dynamics (If-Then Logic)

**Scenario A: Change Occurs ($Change=1$) $\rightarrow$ Reset Experience**

$$
Exp_{l,t} \ge \sum L_{l,s}^{\text{exp}} Z_{l,s',s,t} - M(1 - Change_{l,t})
$$

$$
Exp_{l,t} \le \sum L_{l,s}^{\text{exp}} Z_{l,s',s,t} + M(1 - Change_{l,t})
$$

**Scenario B: No Change ($Change=0$) $\rightarrow$ Accumulate Experience**

$$
Exp_{l,t} \ge Exp_{l,t-1} + U_{l,t-1} - M \cdot Change_{l,t}
$$

$$
Exp_{l,t} \le Exp_{l,t-1} + U_{l,t-1} + M \cdot Change_{l,t}
$$

#### 8. Learning Curve & Capacity

**Piecewise Linear Efficiency (SOS2):**

$$
Eff_{l,t} = f(Exp_{l,t})
$$

**Production Capacity:**

$$
SAM_s \cdot P_{l,s,t} \le H_{l,t} \cdot 60 \cdot N_l \cdot Eff_{l,t}
$$
```
