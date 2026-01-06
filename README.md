## 4. Mathematical Model (MILP Formulation)

This section details the exact Mixed-Integer Linear Programming model implemented in `models/pyomo_model.py`.

### 4.1. Sets and Indices

| Symbol | Description |
| :--- | :--- |
| $\mathcal{L}$ | Lines: production lines, indexed by $l$. |
| $\mathcal{S}$ | Styles: garment styles (SKUs), indexed by $s$ and $s'$. |
| $\mathcal{T}$ | Periods: discrete planning periods, indexed by $t$, with $\mathcal{T} = \{1, \dots, T\}$. |
| $\mathcal{BP}$ | Break-points of the learning curve, indexed by $p$. |
| $\mathcal{SS}$ | Similar styles: pairs $(s, s')$ that are sufficiently alike to share experience. |
| $\mathcal{SP}$ | Dissimilar styles: style pairs requiring a changeover, i.e., $\mathcal{SP} = \{ (s,s') \in \mathcal{S}^2 \mid s \neq s' \}$. |

### 4.2. Parameters

**Demand & Material:**
*   $D_{s,t}$: Demand for style $s$ due at period $t$.
*   $F_{s,t}$: Fabric of style $s$ received at $t$.
*   $I_s^{0,\text{fabric}}$ / $I_s^{0,\text{product}}$: Initial inventories.
*   $B_s^0$: Initial Backlog.
*   $T_s^{\text{fab}}$: Fabric processing lead time.
*   $T_s^{\text{prod}}$: Product finishing lead time.

**Line Configuration:**
*   $Y_{l,s}^0$: Initial setup state.
*   $Y_{l,s}^{\text{allow}}$: 1 if style $s$ is allowed on line $l$.
*   $N_l$: Headcount (operators) on line $l$.
*   $H_{l,t}$: Working hours available on line $l$ at $t$.
*   $SAM_s$: Standard allowed minutes per unit.

**Learning & Costs:**
*   $X_p, F_p$: Break-points for Learning Curve.
*   $Exp_l^0$: Initial experience.
*   $L_{l,s}^{\text{exp}}$: Base experience after changeover.
*   $C^{\text{setup}}$: Setup cost.
*   $P_s^{\text{late}}$: Late penalty cost.
*   $R^{\text{exp}}$: Experience reward.
*   $\delta_t$: Discount factor $(1+\alpha)^{-t}$.

### 4.3. Decision Variables

*   **Continuous:**
    *   $P_{l,s,t}$: Units produced.
    *   $Ship_{s,t}$: Units shipped.
    *   $I_{s,t}^{\text{fab,B/E}}$, $I_{s,t}^{\text{prod,B/E}}$: Inventories (Beg/End).
    *   $B_{s,t}$: Backlog.
    *   $Exp_{l,t}$: Cumulative experience.
    *   $Eff_{l,t}$: Efficiency ratio.
*   **Binary:**
    *   $Y_{l,s,t}$: 1 if line $l$ runs style $s$.
    *   $Z_{l,s',s,t}$: 1 if switch from $s'$ to $s$.
    *   $Change_{l,t}$: 1 if changeover occurs.
    *   $U_{l,t}$: 1 if line operates efficiently enough to learn.

### 4.4. Objective Function

Minimize Total Discounted Cost:

$$
\text{Min } \mathcal{Z} = C^{\text{setup}} \sum_{l \in \mathcal{L}} \sum_{(s',s) \in \mathcal{SP}} \sum_{t \in \mathcal{T}} Z_{l,s',s,t} \delta_t + \sum_{s \in \mathcal{S}} \sum_{t \in \mathcal{T}} P_s^{\text{late}} B_{s,t} \delta_t - R^{\text{exp}} \sum_{l \in \mathcal{L}} \sum_{t \in \mathcal{T}} Exp_{l,t} \delta_t
$$

### 4.5. Constraints

#### 1. Fabric flow and usage

**(C1a)** Fabric Inventory (Beginning):
$$
I_{s,t}^{\text{fab,B}} = \begin{cases} I_s^{0,\text{fabric}}, & t=1 \\ I_{s,t-1}^{\text{fab,E}}, & t > 1 \end{cases} + F_{s, t-T_s^{\text{fab}}}
$$

**(C1b)** Fabric Inventory (End):
$$ I_{s,t}^{\text{fab,E}} = I_{s,t}^{\text{fab,B}} - \sum_{l \in \mathcal{L}} P_{l,s,t} $$

**(C1c)** Material Availability:
$$ \sum_{l \in \mathcal{L}} P_{l,s,t} \le I_{s,t}^{\text{fab,B}} $$

#### 2. Finished-goods flow and shipment

**(C2a)** Product Inventory (Beginning):
$$
I_{s,t}^{\text{prod,B}} = \begin{cases} I_s^{0,\text{product}}, & t=1 \\ I_{s,t-1}^{\text{prod,E}}, & t > 1 \end{cases} + \sum_{l \in \mathcal{L}} P_{l,s, t-T_s^{\text{prod}}}
$$

**(C2b)** Product Inventory (End):
$$ I_{s,t}^{\text{prod,E}} = I_{s,t}^{\text{prod,B}} - Ship_{s,t} $$

**(C2c)** Shipment Limit:
$$ Ship_{s,t} \le I_{s,t}^{\text{prod,B}} $$

#### 3. Backlog recursion

**(C3)** Backlog Balance:
$$ B_{s,t} = B_{s,t-1} + D_{s,t} - Ship_{s,t} $$

#### 4. Line-style assignment and feasibility

**(C4a)** Single Assignment:
$$ \sum_{s \in \mathcal{S}} Y_{l,s,t} = 1, \quad \forall l, t $$

**(C4b)** Capability:
$$ Y_{l,s,t} \le Y_{l,s}^{\text{allow}}, \quad \forall l, s, t $$

**(C4c)** Production Linking (Big-M):
$$ P_{l,s,t} \le M Y_{l,s,t}, \quad \forall l, s, t $$

#### 5. Change-over identification

**(C5a-b)** Detect Switch ($Z=1$ if $Y_{t-1} + Y_t - 1 > 0$):
$$ Z_{l,s',s,t} \ge Y_{l,s',t-1} + Y_{l,s,t} - 1 $$

**(C5c-d)** Upper Bounds:
$$ Z_{l,s',s,t} \le Y_{l,s,t}, \quad Z_{l,s',s,t} \le Y_{l,s',t-1} $$

#### 6. Utilisation trigger

Determine $U_{l,t}$ based on output vs threshold (Big-M formulation):

**(C6a)** Lower bound ($U=1$ if output high):
$$ \sum_{s \in \mathcal{S}} SAM_s P_{l,s,t} - 0.5 H_{l,t} 60 N_l Eff_{l,t} + M(1 - U_{l,t}) \ge 0 $$

**(C6b)** Upper bound ($U=0$ if output low):
$$ \sum_{s \in \mathcal{S}} SAM_s P_{l,s,t} - 0.5 H_{l,t} 60 N_l Eff_{l,t} - \varepsilon \le M U_{l,t} $$

#### 7. "Change" flag and experience recursion

**(C7a)** Aggregate Change:
$$ Change_{l,t} = \sum_{(s',s) \in \mathcal{SP} \setminus \mathcal{SS}} Z_{l,s',s,t} $$

**(C7b-g)** Experience Logic (Big-M constraints):
If **Change occurs** ($Change_{l,t}=1$), reset to base experience:
$$ Exp_{l,t} \ge \sum_{(s',s)} L_{l,s}^{\text{exp}} Z_{l,s',s,t} - M(1 - Change_{l,t}) $$
$$ Exp_{l,t} \le \sum_{(s',s)} L_{l,s}^{\text{exp}} Z_{l,s',s,t} + M(1 - Change_{l,t}) $$

If **No Change** ($Change_{l,t}=0$), accumulate experience:
$$ Exp_{l,t} \ge Exp_{l,t-1} + U_{l,t-1} - M Change_{l,t} $$
$$ Exp_{l,t} \le Exp_{l,t-1} + U_{l,t-1} + M Change_{l,t} $$

#### 8. Learning curve relation

**(C8)** Piecewise Linear (SOS2 formulation):
$$ Eff_{l,t} = f(Exp_{l,t}), \quad \text{interpolated through } (X_p, F_p)_{p \in \mathcal{BP}} $$

#### 9. Capacity with variable efficiency

**(C9)** Production Capacity:
$$ SAM_s P_{l,s,t} \le H_{l,t} 60 N_l Eff_{l,t}, \quad \forall l, s, t $$

---

## 5. Metaheuristic Algorithm Model

For large-scale problems, we use a **Simulation-based Metaheuristic** approach.

### 5.1. Representation
$$ X = \{ x_{l,t} \mid l \in \mathcal{L}, t \in \mathcal{T} \} $$
Where $x_{l,t}$ is the style ID assigned to line $l$ on day $t$.

### 5.2. Simulation Logic
The `ALNS_operator` calculates the objective function by simulating the timeline:
1.  **Material Check:** $P_{l,s,t} = \min(\text{Capacity}, \text{FabricAvailable})$.
2.  **Repair:** If fabric is missing, attempt to switch style to avoid idle time.
3.  **Efficiency:** Look up $Eff$ from $Exp$ table. Update $Exp$ based on continuity ($x_{l,t} == x_{l,t-1}$).

### 5.3. Search Strategy
*   **Tabu Search:** Avoids cycling by keeping a list of recently visited moves.
*   **ALNS Operators:**
    *   *Setup Reduction:* Merge short segments.
    *   *Late Reduction:* Prioritize high-backlog styles.
*   **Strategic Oscillation:** Temporarily allows infeasible solutions to escape local optima, then aggressively repairs them.

---

## 6. Output

The system generates an Excel report (`Production_Plan_Report.xlsx`) visualizing:
*   **Style:** Color-coded Gantt chart.
*   **Qty:** Daily production.
*   **Eff/Exp:** Efficiency and Experience progression.
```
