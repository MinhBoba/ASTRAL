I understand. The rendering issues usually happen because GitHub's Markdown parser requires very specific spacing around LaTeX blocks (`$$`). Also, I will expand the content to be a **complete, 1-to-1 representation** of the problem statement, assumptions, and mathematical model you provided in the images, along with the project documentation.

Here is the **complete, fixed, and extensive README.md**. You can copy this code block directly.

***

```markdown
# Production Scheduling with Learning Curves (Make-Color Model)

## 1. Project Overview

**Make-Color**, a contract apparel manufacturer, must orchestrate the daily assignment of multiple *sewing lines* to a diverse portfolio of *garment styles*. Each style has time-phased demand and relies on incoming fabric that itself follows a fixed preprocessing lead time.

Changing a line from one style to another incurs a **setup cost** and resets (partially) the accumulated sewing experience that drives line efficiency. The company seeks to minimize the **discounted total cost** consisting of:

1.  Fixed line–style **change-over costs**.
2.  **Late-delivery penalties** for unmet demand.
3.  The negative cost (i.e., reward) of **experience accumulation**.

This must be achieved while honoring material availability, line capacity, operator working hours, and learning-curve dynamics.

---

## 2. Directory Structure

```text
minhboba-astral/
├── main.py                  # Entry Point: Loads data, runs solver, exports results
├── metaheuristic/           # Algorithm Logic (Tabu Search + ALNS)
│   ├── __init__.py
│   ├── ALNS_operator.py     # Simulation Evaluator (Greedy decoding)
│   ├── neighbor_generator.py# Move Operators (Swap, Block, Smart Moves)
│   ├── oscillation_strategy.py # Logic to handle infeasible regions
│   └── tabu_search.py       # Main Optimization Loop
├── models/                  # Exact Optimization Logic
│   ├── init.py
│   └── pyomo_model.py       # Pyomo (MILP) Implementation
├── utils/                   # Utilities
│   ├── data_loader.py       # Excel Reader & Data Cleaning
│   ├── excel_exporter.py    # Gantt Chart Reporting
│   └── file_handler.py      # I/O Helper
└── Small.xlsx               # Input Data File
```

---

## 3. Installation & Usage

### Prerequisites
*   **Python 3.8+**
*   **Libraries:** `pandas`, `numpy`, `openpyxl`, `xlsxwriter`.
*   *(Optional)* For the Exact Model: `pyomo` and a MILP solver (CPLEX, Gurobi, or CBC).

### Installation
```bash
pip install pandas numpy openpyxl xlsxwriter pyomo
```

### Running the Project
1.  Place your data file (e.g., `Small.xlsx`) in the root directory.
2.  Run the main script:
    ```bash
    python main.py
    ```
3.  Check the `result/` folder for the Gantt chart report (`Production_Plan_Report.xlsx`).

---

## 4. Problem Description & Assumptions

Over a finite planning horizon of $|\mathcal{T}|$ discrete periods, we must decide for every line $l \in \mathcal{L}$, style $s \in \mathcal{S}$, and period $t \in \mathcal{T}$:
1.  The *binary line-style assignment* $Y_{l,s,t}$.
2.  The *quantity* $P_{l,s,t}$ sewn.
3.  The *shipment quantity* $Ship_{s,t}$ released to the customer.
4.  Auxiliary variables tracking change-overs, backlog, inventories, experience, and efficiency.

### Assumptions
*   **A1. Deterministic Data:** Demand, fabric receipts, SAM values, and working hours are known and constant.
*   **A2. Single Style per Line:** Each sewing line processes at most one style per period.
*   **A3. Instantaneous Change-over:** Switches consume no productive time but incur cost and reset experience.
*   **A4. Experience Carry-Over:** Cumulative experience propagates period-to-period; similar styles (in set $\mathcal{SS}$) share experience, dissimilar ones ($\mathcal{SP} \setminus \mathcal{SS}$) do not.
*   **A5. Discounted Cash Flows:** Costs are discounted by $(1+\alpha)^{-t}$.
*   **A6. Unlimited Storage:** Inventories accumulate without holding costs (only opportunity cost via discounting).

---

## 5. Mathematical Model Formulation

### 5.1. Sets and Indices

| Symbol | Description |
| :--- | :--- |
| $\mathcal{L}$ | Production lines, indexed by $l$. |
| $\mathcal{S}$ | Garment styles (SKUs), indexed by $s$ and $s'$. |
| $\mathcal{T}$ | Discrete planning periods, indexed by $t$, $\mathcal{T} = \{1, \dots, T\}$. |
| $\mathcal{BP}$ | Break-points of the learning curve, indexed by $p$. |
| $\mathcal{SS}$ | **Similar styles:** Pairs $(s, s')$ that share experience. |
| $\mathcal{SP}$ | **Dissimilar styles:** Pairs requiring a changeover reset. $\mathcal{SP} = \{ (s,s') \in \mathcal{S}^2 \mid s \neq s' \}$. |

### 5.2. Parameters

**Demand & Supply:**
*   $D_{s,t}$: Demand for style $s$ due at period $t$.
*   $F_{s,t}$: Fabric of style $s$ received at $t$.
*   $I_s^{0,\text{fabric}}$ / $I_s^{0,\text{product}}$: Initial inventories.
*   $B_s^0$: Initial Backlog.
*   $T_s^{\text{fab}}$ / $T_s^{\text{prod}}$: Lead times for fabric and product finishing.

**Line & Cost:**
*   $Y_{l,s}^0$: 1 if line $l$ is initially set up for $s$.
*   $Y_{l,s}^{\text{allow}}$: 1 if style $s$ is allowed on line $l$.
*   $N_l$: Headcount (operators) on line $l$.
*   $H_{l,t}$: Working hours available on line $l$ at $t$.
*   $SAM_s$: Standard allowed minutes per unit.
*   $C^{\text{setup}}$: Setup cost.
*   $P_s^{\text{late}}$: Late penalty per unit.
*   $R^{\text{exp}}$: Experience reward per unit.
*   $\alpha$: Discount rate.

**Learning:**
*   $X_p, F_p$: Break-points for Learning Curve.
*   $Exp_l^0$: Initial experience.
*   $L_{l,s}^{\text{exp}}$: Base experience after changeover.

### 5.3. Decision Variables

*   **Continuous:**
    *   $P_{l,s,t}$: Units produced.
    *   $Ship_{s,t}$: Units shipped.
    *   $I_{s,t}^{\text{fab,B/E}}$: Fabric Inventory (Beginning/End).
    *   $I_{s,t}^{\text{prod,B/E}}$: Product Inventory (Beginning/End).
    *   $B_{s,t}$: Backlog.
    *   $Exp_{l,t}$: Cumulative experience.
    *   $Eff_{l,t}$: Efficiency ratio.
*   **Binary:**
    *   $Y_{l,s,t}$: 1 if line $l$ runs style $s$.
    *   $Z_{l,s',s,t}$: 1 if switch from $s'$ to $s$.
    *   $Change_{l,t}$: 1 if changeover occurs.
    *   $U_{l,t}$: 1 if line operates efficiently enough to learn.

### 5.4. Objective Function

Minimize Total Discounted Cost $\mathcal{Z}$:

$$
\text{Min } \mathcal{Z} = C^{\text{setup}} \sum_{l \in \mathcal{L}} \sum_{(s',s) \in \mathcal{SP}} \sum_{t \in \mathcal{T}} Z_{l,s',s,t} \delta_t + \sum_{s \in \mathcal{S}} \sum_{t \in \mathcal{T}} P_s^{\text{late}} B_{s,t} \delta_t - R^{\text{exp}} \sum_{l \in \mathcal{L}} \sum_{t \in \mathcal{T}} Exp_{l,t} \delta_t
$$

Where $\delta_t = (1+\alpha)^{-t}$.

### 5.5. Constraints

#### 1. Fabric Flow and Usage

**(C1a)** Fabric Inventory (Beginning):
$$
I_{s,t}^{\text{fab,B}} = \begin{cases} I_s^{0,\text{fabric}}, & t=1 \\ I_{s,t-1}^{\text{fab,E}}, & t > 1 \end{cases} + \begin{cases} F_{s, t-T_s^{\text{fab}}}, & t > T_s^{\text{fab}} \\ 0, & \text{otherwise} \end{cases}
$$

**(C1b)** Fabric Inventory (End):
$$
I_{s,t}^{\text{fab,E}} = I_{s,t}^{\text{fab,B}} - \sum_{l \in \mathcal{L}} P_{l,s,t}
$$

**(C1c)** Material Availability:
$$
\sum_{l \in \mathcal{L}} P_{l,s,t} \le I_{s,t}^{\text{fab,B}}
$$

#### 2. Finished-Goods Flow and Shipment

**(C2a)** Product Inventory (Beginning):
$$
I_{s,t}^{\text{prod,B}} = \begin{cases} I_s^{0,\text{product}}, & t=1 \\ I_{s,t-1}^{\text{prod,E}}, & t > 1 \end{cases} + \begin{cases} \sum_{l \in \mathcal{L}} P_{l,s, t-T_s^{\text{prod}}}, & t > T_s^{\text{prod}} \\ 0, & \text{otherwise} \end{cases}
$$

**(C2b)** Product Inventory (End):
$$
I_{s,t}^{\text{prod,E}} = I_{s,t}^{\text{prod,B}} - Ship_{s,t}
$$

**(C2c)** Shipment Limit:
$$
Ship_{s,t} \le I_{s,t}^{\text{prod,B}}
$$

#### 3. Backlog Recursion

**(C3)** Backlog Balance:
$$
B_{s,t} = \begin{cases} B_s^0 + D_{s,t} - Ship_{s,t}, & t=1 \\ B_{s,t-1} + D_{s,t} - Ship_{s,t}, & t > 1 \end{cases}
$$

#### 4. Line-Style Assignment

**(C4a)** Single Assignment:
$$
\sum_{s \in \mathcal{S}} Y_{l,s,t} = 1, \quad \forall l, t
$$

**(C4b)** Capability:
$$
Y_{l,s,t} \le Y_{l,s}^{\text{allow}}, \quad \forall l, s, t
$$

**(C4c)** Production Linking (Big-M):
$$
P_{l,s,t} \le M Y_{l,s,t}, \quad \forall l, s, t
$$

#### 5. Change-Over Identification

**(C5a)** Initial Period ($t=1$):
$$
Z_{l,s',s,1} \ge Y_{l,s'}^0 + Y_{l,s,1} - 1
$$

**(C5b)** Subsequent Periods ($t>1$):
$$
Z_{l,s',s,t} \ge Y_{l,s',t-1} + Y_{l,s,t} - 1
$$

**(C5c-d)** Upper Bounds:
$$
Z_{l,s',s,t} \le Y_{l,s,t} \quad \text{and} \quad Z_{l,s',s,t} \le Y_{l,s',t-1}
$$

#### 6. Utilization Trigger

Logic: Line gains experience ($U=1$) only if production output is sufficiently high relative to potential capacity.

**(C6a)** Lower Bound Constraint:
$$
\sum_{s \in \mathcal{S}} SAM_s P_{l,s,t} - 0.5 H_{l,t} 60 N_l Eff_{l,t} + M(1 - U_{l,t}) \ge 0
$$

**(C6b)** Upper Bound Constraint:
$$
\sum_{s \in \mathcal{S}} SAM_s P_{l,s,t} - 0.5 H_{l,t} 60 N_l Eff_{l,t} - \varepsilon \le M U_{l,t}
$$

#### 7. Change Flag and Experience Recursion

**(C7a)** Aggregate Change Flag:
$$
Change_{l,t} = \sum_{(s',s) \in \mathcal{SP} \setminus \mathcal{SS}} Z_{l,s',s,t}
$$

**(C7b-g)** Experience Dynamics (via Big-M):

*   **If Change Occurs ($Change=1$):** Reset experience.
    $$ Exp_{l,t} \in \left[ \sum L_{l,s}^{\text{exp}} Z_{l,s',s,t} \right] \pm M(1 - Change_{l,t}) $$

*   **If No Change ($Change=0$):** Accumulate experience.
    $$ Exp_{l,t} \in \left[ Exp_{l,t-1} + U_{l,t-1} \right] \pm M Change_{l,t} $$

#### 8. Learning Curve Relation

**(C8)** Efficiency Mapping (SOS2):
$$
Eff_{l,t} = f(Exp_{l,t}), \quad f(\cdot) \text{ is piecewise linear through } (X_p, F_p)
$$

#### 9. Capacity Constraint

**(C9)** Production Capacity:
$$
SAM_s P_{l,s,t} \le H_{l,t} 60 N_l Eff_{l,t}, \quad \forall l, s, t
$$

---

## 6. Metaheuristic Algorithm Model

For large datasets, the **Tabu Search + ALNS** (Adaptive Large Neighborhood Search) framework is used.

### 6.1. Simulation-Based Evaluation
Instead of solving equations directly, the metaheuristic evaluates a solution $X$ (matrix of Line-Style assignments) by **simulating** the timeline day-by-day:
1.  **Material Check:** Production is capped by $\min(Capacity, FabricInventory)$.
2.  **Repair Logic:** If assigned style lacks fabric, the `ALNS_operator` attempts to switch to a valid style to prevent idle capacity.
3.  **Efficiency Update:** Dynamic lookup of Efficiency based on accumulated Experience steps.

### 6.2. Search Strategy
*   **Tabu List:** Prevents cycling by banning recent moves.
*   **ALNS Operators:**
    *   *Setup Reduction:* Merges short production blocks to minimize $C^{\text{setup}}$.
    *   *Late Reduction:* Force-inserts high-backlog styles to minimize $P^{\text{late}}$.
    *   *Balancing:* Swaps assignments to balance line loads.
*   **Strategic Oscillation:**
    *   Allows the search to temporarily enter **Infeasible** regions (violating capability constraints) to escape local optima.
    *   Applies an **Aggressive Repair** heuristic to restore feasibility.
```
