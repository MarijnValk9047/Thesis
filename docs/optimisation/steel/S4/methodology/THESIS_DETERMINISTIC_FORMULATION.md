# Deterministic MILP formulation for the thesis methodology

This section is the concise thesis-level formulation of the deterministic
rolling-horizon model. It uses one symbol for one meaning and follows the
conventional order: sets and indices, parameters, decision variables,
objective function, and constraints.

The formulation is a methodological abstraction rather than a line-by-line
transcription of the executable Pyomo model. The reported objective is
represented procurement-cost minimisation. The executable model also uses
subordinate production-progress and physical tie-breaking solves to obtain
stable rolling schedules; these do not change the reported economic meaning
of the objective.

## 1. Sets, indices and mappings

| Symbol | Interpretation | Unit |
|---|---|---|
| (c\in\mathcal C) | Steel-production configuration, with \(\mathcal C=\{C0,C1\}\) | - |
| (r\in\mathcal R^{RH}) | Zero-based rolling-horizon replan, (r=0,1,\ldots\) | - |
| (t\in\mathcal T_r) | Time step in the planning horizon of replan \(r\) | - |
| \(\mathcal E_r\subseteq\mathcal T_r\) | Time steps retained and executed after replan \(r\) | - |
| (i\in\mathcal I_c) | Process unit represented in configuration \(c\) | - |
| (b\in\mathcal B_c) | Represented material store or buffer | - |
| \(\rho\in\mathcal P_c\) | Origin-preserving material route | - |
| (w\in\mathcal W) | WAG carrier, with \(\mathcal W=\{BFG,COG,BOFG\}\) | - |
| (k\in\mathcal K_c) | Represented fuel or heat consumer | - |
| \(\mathcal K_c^{NG}\subseteq\mathcal K_c\) | Consumers eligible to use purchased natural gas | - |
| (m\in\mathcal M_c^{ext}) | Externally purchased material represented in configuration \(c\) | - |
| \(\delta(t)\) | Mapping from time step \(t\) to its daily commitment block | - |
| \(i(k)\) | Mapping from energy consumer \(k\) to the process activity that drives its heat demand | - |

One configuration is solved at a time. The configuration index selects the
applicable sets and parameters but does not need to appear on every decision
variable.

### Notation choices

- (r) is used only for the rolling replan; the Greek letter \(\rho\) is used
  for a material route.
- (m) is used only for an externally purchased material; inventories are
  indexed by store (b).
- (w) is the WAG-carrier index; WAG quantities use the capital letter (G).
- (u) is the binary commitment variable. The complete decision vector is
  denoted by \(\mathbf v_r\), so the same symbol is not used twice.
- The feasible set is denoted by \(\Omega_r\), avoiding confusion with the
  route-flow variable (F_{\rho,t}).

## 2. Parameters

| Parameter | Explanation | Unit |
|---|---|---|
| \(\Delta t_t\) | Duration of time step \(t\) | h |
| \(H_r\) | Final time-step position in the planning horizon of replan \(r\) | time-step index |
| \(x_i^{min},x_i^{max}\) | Minimum and maximum process activity rates | activity unit of \(i\)/h |
| \(\lambda_b\) | Fractional standing loss of store \(b\) | fraction/h |
| \(A_b^0\) | Inventory at the start of a rolling solve | t material |
| \(A_b^{max}\) | Capacity of material store \(b\) | t material |
| \(\underline A_b^{end},\overline A_b^{end}\) | Lower and upper terminal inventory limits | t material |
| \(X_r\) | Cumulative final-product output executed before replan \(r\) | t final product |
| \(q^{blk}\) | Required final-product quota per normal execution block | t final product/block |
| \(\beta_{i,w}\) | WAG carrier \(w\) generated per unit of process activity | MWh\(_{LHV}\)/activity unit |
| \(h_{i(k),k}\) | Fuel-heat demand of consumer \(k\) per unit of its driving process activity | MWh\(_{LHV}\)/activity unit |
| \(\kappa^{steam}\) | Fuel heat required per tonne of represented steam supply | MWh\(_{LHV}\)/t steam |
| \(S_c^{dem}\) | Fixed represented steam demand in configuration \(c\) | t steam/h |
| \(P_c^{base}\) | Constant represented electricity-background demand | MW\(_e\) |
| \(e_i\) | Electricity demand per unit of process activity | MWh\(_e\)/activity unit |
| \(\pi_t^{el}\) | Grid-electricity purchase price | EUR/MWh\(_e\) |
| \(\pi_t^{NG}\) | Natural-gas purchase price | EUR/MWh\(_{LHV}\) |
| \(N_c^{base}\) | Constant represented, non-WAG-displaceable NG service | MW\(_{LHV}\), equivalent to MWh\(_{LHV}\)/h |
| \(\pi_{m,t}^{mat}\) | Purchase price of external material \(m\); the time index may represent a constant price series | EUR/t material |

The unit convention is lower-heating-value energy for natural gas and WAG,
and electrical energy for electricity. This distinction is retained in all
prices, flows and conversion parameters.

## 3. Decision variables

| Variable | Interpretation | Domain | Unit |
|---|---|---|---|
| \(x_{i,t}\) | Activity rate of process unit \(i\) | \(\mathbb R_{\ge0}\) | activity unit of \(i\)/h |
| \(u_{i,\delta(t)}\) | Daily operating state where commitment is explicitly modelled | \(\{0,1\}\) | binary |
| \(A_{b,t}\) | End-of-hour inventory in store \(b\) | \(\mathbb R_{\ge0}\) | t material |
| \(F_{\rho,t}\) | Material flow through origin-preserving route \(\rho\) | \(\mathbb R_{\ge0}\) | t material/h |
| \(Y_t^{FP}\) | Total represented final-product output rate | \(\mathbb R_{\ge0}\) | t final product/h |
| \(G_{w,t}^{prod}\) | Production rate of WAG carrier \(w\) | \(\mathbb R_{\ge0}\) | MWh\(_{LHV}\)/h |
| \(G_{w,k,t}^{use}\) | WAG carrier \(w\) allocated to eligible consumer \(k\) | \(\mathbb R_{\ge0}\) | MWh\(_{LHV}\)/h |
| \(G_{w,t}^{flare}\) | Explicitly flared or surplus WAG carrier \(w\) | \(\mathbb R_{\ge0}\) | MWh\(_{LHV}\)/h |
| \(N_{k,t}\) | Purchased natural gas delivered to eligible consumer \(k\) | \(\mathbb R_{\ge0}\) | MWh\(_{LHV}\)/h |
| \(S_t^{sup}\) | Represented steam supplied | \(\mathbb R_{\ge0}\) | t steam/h |
| \(S_t^{spill}\) | Explicit surplus steam | \(\mathbb R_{\ge0}\) | t steam/h |
| \(P_t^{grid}\) | Net grid-electricity import | \(\mathbb R_{\ge0}\) | MW\(_e\) |
| \(P_t^{gen}\) | Aggregate represented internal electricity generation | \(\mathbb R_{\ge0}\) | MW\(_e\) |
| \(Q_{m,t}^{ext}\) | Purchased delivery rate of external material \(m\) | \(\mathbb R_{\ge0}\) | t material/h |

Continuous installations are not allowed to switch on and off freely each
hour. Source-classified continuous assets remain available, with
\(u_{i,\delta(t)}=1\), and their activity stays endogenous within the stated
minimum and maximum bounds. Binary variables are used only where daily
commitment or semi-continuous operation is explicitly represented. Variables
are omitted or fixed to zero for routes and assets that do not exist in the
selected configuration.

The aggregate material inflow \(\Phi_{b,t}^{in}\) and outflow
\(\Phi_{b,t}^{out}\), both in t material/h, are expressions constructed from
the process activities and route flows. They are not additional independent
decision variables.

## 4. Objective function

For replan (r), let \(\mathbf v_r\) denote the complete collection of
decision variables in Section 3 and let \(\Omega_r\) denote the feasible set
defined by the physical, production and operational constraints. The
thesis-level deterministic objective is:

\[
\boxed{
\underset{\mathbf v_r\in\Omega_r}{\operatorname{minimise}}
\quad
C_r^{proc}(\mathbf v_r)
=
\sum_{t\in\mathcal T_r}\Delta t_t
\left[
\pi_t^{el}P_t^{grid}
+
\pi_t^{NG}
\left(
N_c^{base}
+
\sum_{k\in\mathcal K_c^{NG}}N_{k,t}
\right)
+
\sum_{m\in\mathcal M_c^{ext}}
\pi_{m,t}^{mat}Q_{m,t}^{ext}
\right].
}
\]

The objective value (C_r^{proc}\) is measured in EUR over the planning
horizon. Multiplication by \(\Delta t_t\) converts electricity and fuel rates
from MWh/h into MWh purchased during the time step and converts material rates
from t/h into tonnes purchased during the time step. Every external purchase
is linked exactly once to its physical flow.

The represented purchases comprise net grid electricity, named natural gas,
the fixed represented NG service, and the external material flows activated
for the selected C0 or C1 configuration. Internally generated BFG, COG, BOFG,
steam and electricity receive no direct purchase price. Their economic value
arises indirectly when their use reduces an external purchase.

Production is not rewarded in the objective. Instead, production progress,
material balances, operating limits and utility requirements are imposed by
constraints. The model therefore cannot reduce cost by omitting required
production.

### Why cost is minimised instead of profit maximised

Steel output is imposed as an operational requirement rather than selected as
a sales decision. If output and product revenue are fixed, maximising revenue
minus cost is mathematically equivalent to minimising cost. Moreover, the
model does not represent complete product revenue, labour, maintenance, fixed
operating expenditure, electricity-export revenue, ETS liability or mFRR
revenue. Describing the objective as whole-site profit maximisation would
therefore overstate its economic boundary. The correct term is **represented
external procurement-cost minimisation**.

## 5. Five core constraint families

### 5.1 Process operating limits

\[
x_i^{min}u_{i,\delta(t)}
\le x_{i,t}\le
x_i^{max}u_{i,\delta(t)}
\qquad
\forall i\in\mathcal I_c,\ t\in\mathcal T_r.
\]

This constraint keeps every process within its permitted activity range. A
fixed value of (u=1\) represents a continuous available asset; (u=0\)
represents an inactive asset.

### 5.2 Material inventory conservation

\[
A_{b,t}
=
(1-\lambda_b\Delta t_t)A_{b,t-1}
+
\Delta t_t
\left(
\Phi_{b,t}^{in}-\Phi_{b,t}^{out}
\right)
\qquad
\forall b\in\mathcal B_c,\ t\in\mathcal T_r.
\]

The boundary conditions are

\[
A_{b,0}=A_b^0,
\qquad
0\le A_{b,t}\le A_b^{max},
\qquad
\underline A_b^{end}\le A_{b,H_r}\le\overline A_b^{end}.
\]

The terminal limits prevent the rolling model from reducing current cost by
emptying a store that a later replan must replenish.

### 5.3 Rolling production requirement

\[
X_r
+
\sum_{t\in\mathcal E_r}\Delta t_tY_t^{FP}
\ge
(r+1)q^{blk}.
\]

The cumulative output already executed plus output in the next executed block
must remain on or ahead of the required production trajectory. Any surplus is
carried into the next replan. This hard inequality is the thesis-level
simplification of the executable production-progress tier.

### 5.4 Carrier-specific WAG and fuel balance

\[
G_{w,t}^{prod}
=
\sum_{i\in\mathcal I_c}\beta_{i,w}x_{i,t}
=
\sum_{k\in\mathcal K_c}G_{w,k,t}^{use}
+G_{w,t}^{flare}
\qquad
\forall w\in\mathcal W,\ t\in\mathcal T_r,
\]

and, for each represented heat consumer,

\[
\sum_{w\in\mathcal W}G_{w,k,t}^{use}
+N_{k,t}
=
h_{i(k),k}x_{i(k),t}
\qquad
\forall k\in\mathcal K_c,\ t\in\mathcal T_r.
\]

BFG, COG and BOFG remain separate carriers. An allocation variable exists
only for a source-supported carrier-consumer pair. WAG has no hourly storage:
it must be used or flared in the hour in which it is generated.

### 5.5 Steam and electricity balances

Steam production and demand satisfy

\[
\kappa^{steam}S_t^{sup}
=
\sum_{w\in\mathcal W}G_{w,steam,t}^{use}
+N_{steam,t},
\qquad
S_t^{sup}=S_c^{dem}+S_t^{spill}.
\]

The second equality expresses the accepted-run condition of zero unserved
steam. Steam spill remains explicit and steam storage is outside the core
formulation.

The represented electricity balance is

\[
P_t^{grid}+P_t^{gen}
=
P_c^{base}
+
\sum_{i\in\mathcal I_c}e_ix_{i,t}
\qquad
\forall t\in\mathcal T_r.
\]

Grid import is non-negative. Electricity export is not part of this core
formulation, so internal generation cannot exceed represented demand.

## 6. Implementation boundary

The five constraint families state the central methodological logic. The
executable model additionally contains plant-specific material yields, route
eligibility, cumulative supply limits, generator conversion and capacity
relations, rolling-state handoff equations, and numerical tie-breaking.
Those details should be documented with the relevant plant and network
sections rather than repeated in the core mathematical formulation.
