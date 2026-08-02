# Core Physical and Deterministic-Procurement Steel MILP

## 1. Purpose and inheritance rule

This document defines the shared physical formulation once. The deterministic
DA, stochastic, CVaR and later mFRR formulations inherit this physical system.
Their chapter sections should cite this formulation and introduce only their
additional market or uncertainty notation.

The formulation represents the governed C0/C1 procurement boundary. It is not
a complete Tata Steel IJmuiden digital twin, full-site annual backtest or
ETS-ready emissions model.

## 2. Configurations and system boundary

The configuration parameter selects one of two topologies:

- `C0`: KGF1, KGF2, sinter, PEFA, BF6, BF7, BOF and the represented downstream
  route are active.
- `C1`: KGF1, sinter, PEFA, BF6 and BOF are retained; KGF2 and BF7 are inactive;
  the NG-DRP and EAF route is added; the represented downstream route remains.

The represented boundary contains material conversion, material stores,
production deadlines, BFG/COG/BOFG allocation, named natural gas, aggregate
steam service, represented internal generation and net grid import. Product
revenue, electricity export, ETS cost, stochasticity, CVaR and mFRR are not
part of the core formulation.

## 3. Sets, indices and mappings

| Symbol | Type | Definition | Unit |
|---|---|---|---|
| \(c\in\mathcal C\) | Configuration index | Configuration, with \(\mathcal C=\{C0,C1\}\) | none |
| \(r\in\mathcal R^{RH}\) | Rolling-replan index | Replan number in the executed rolling sequence | none |
| \(t\in\mathcal T_r\) | Time index | Hourly interval inside the planning horizon of replan \(r\) | h index |
| \(\mathcal E_r\subset\mathcal T_r\) | Executed-time set | First block of replan \(r\); only these decisions are retained | h index |
| \(d\in\mathcal D_r\) | Deadline index | Cumulative production deadline expressed as elapsed hours in replan \(r\) | h |
| \(i\in\mathcal I_c\) | Process index | Process unit active or retained in configuration \(c\) | none |
| \(m\in\mathcal M_c\) | Material index | Represented material carrier, such as coke, sinter, hot metal, DRI, liquid steel, slab or final product | none |
| \(b\in\mathcal B_c\) | Store index | Represented material buffer or store | none |
| \(w\in\mathcal W\) | WAG index | Waste-gas carrier, \(\mathcal W=\{BFG,COG,BOFG\}\) | none |
| \(k\in\mathcal K_c\) | Energy-consumer index | Process, boiler or generator eligible to consume WAG or NG | none |
| \(j\in\mathcal J_c\) | Generator index | Represented internal generator interface | none |
| \(\rho\in\mathcal P_c\) | Route index | Origin-preserving downstream material route | none |
| \(\mathcal P_m^{in},\mathcal P_m^{out}\) | Route subsets | Routes entering and leaving the junction for material \(m\) | none |
| \(\mathcal P^{final}\subseteq\mathcal P_c\) | Route subset | Routes whose outputs count toward final product | none |
| \(f\in\mathcal F_c^{ext}\) | External-flow index | Purchased electricity, fuel or material priced in the represented boundary | none |
| \(\delta(t)\) | Mapping | Maps hour \(t\) to its daily commitment block | day index |
| \(m(b)\) | Mapping | Maps store \(b\) to the material carried by that store | none |
| \(i(k)\) | Mapping | Maps energy consumer \(k\) to the process activity that drives its heat demand | process index |

The configuration index is normally fixed for one optimisation run. It is
shown explicitly here to make the C0/C1 dependence of sets and parameters
clear; executable variables do not need an additional \(c\) index when one
configuration is solved at a time.

## 4. Parameters

### 4.1 Time, production and numerical parameters

| Symbol | Definition | Unit |
|---|---|---|
| \(\Delta t_t\) | Duration of interval \(t\); normally one hour and timestamp-aware at DST boundaries | h |
| \(H_r\) | Number of intervals in the planning horizon of replan \(r\) | h |
| \(B_r\) | Number of intervals in the executed block \(\mathcal E_r\) | h |
| \(Q^{ann}\) | Annual final-product target used to define the production trajectory | t final product/y |
| \(q^{blk}\) | Central final-product quota per normal execution block | t final product/block |
| \(Q_{r,d}^{min}\) | Minimum cumulative final-product output required by deadline \(d\) in replan \(r\) | t final product |
| \(X_r\) | Cumulative final-product output executed before replan \(r\) | t final product |
| \(q_r^{next}\) | Carry-corrected target for the next executed block | t final product |
| \(\tau^{cost}\) | Allowed absolute tolerance when preserving the procurement-cost optimum | EUR |
| \(\tau^{prog}\) | Allowed absolute tolerance when preserving the production-progress optimum | t final product |

### 4.2 Process and material parameters

| Symbol | Definition | Unit |
|---|---|---|
| \(\underline x_i\) | Minimum hourly activity rate when unit \(i\) is committed | activity unit of \(i\)/h |
| \(\overline x_i\) | Maximum hourly activity rate of unit \(i\) | activity unit of \(i\)/h |
| \(a_{i,m}^{in}\) | Quantity of material \(m\) consumed per unit of activity of process \(i\) | t material/activity unit |
| \(a_{i,m}^{out}\) | Quantity of material \(m\) produced per unit of activity of process \(i\) | t material/activity unit |
| \(A_b^{max}\) | Capacity of material store \(b\) | t material |
| \(A_b^{0}\) | Inventory of store \(b\) at the start of a rolling solve | t material |
| \(\underline A_b^{end},\overline A_b^{end}\) | Lower and upper terminal inventory limits for store \(b\) | t material |
| \(\lambda_b\) | Fractional standing loss of store \(b\) per hour | fraction/h |
| \(U_{\rho,d}^{max}\) | Cumulative upper bound for material route \(\rho\) by deadline \(d\) | t material |

An activity unit is stated for every process in the parameter register. For
example, KGF activity is measured in tonnes of dry coal input, BF activity in
tonnes of represented sinter input, and HSM activity in tonnes of slab input.

### 4.3 Energy parameters

| Symbol | Definition | Unit |
|---|---|---|
| \(e_i\) | Electricity demand per unit of process activity | MWh\(_e\)/activity unit |
| \(h_{i,k}\) | Fuel-heat demand of energy consumer \(k\) per unit of its process activity | MWh\(_{LHV}\)/activity unit |
| \(\beta_{i,w}\) | WAG energy generated as carrier \(w\) per unit of process activity | MWh\(_{LHV}\)/activity unit |
| \(S_c^{dem}\) | Fixed represented steam demand in configuration \(c\) | t steam/h |
| \(\kappa^{steam}\) | Fuel heat required per tonne of represented steam supply | MWh\(_{LHV}\)/t steam |
| \(P_c^{base}\) | Constant represented electricity-background demand | MW\(_e\), numerically MWh\(_e\)/h |
| \(N_c^{base}\) | Constant represented, non-WAG-displaceable NG service | MW\(_{LHV}\), numerically MWh\(_{LHV}\)/h |
| \(\eta_j^{el}\) | Electrical conversion efficiency of represented generator \(j\) | MWh\(_e\)/MWh\(_{LHV}\) |
| \(\overline P_j^{gen}\) | Electrical output upper bound of generator \(j\) | MW\(_e\) |
| \(\overline V_j\) | Volumetric gas-input upper bound of generator interface \(j\) | Nm\(^3\)/h |

### 4.4 Economic parameters

| Symbol | Definition | Unit |
|---|---|---|
| \(\pi_{f,t}\) | Price of external flow \(f\) in hour \(t\) | EUR per physical unit \(U_f\) |
| \(U_f\) | Physical quantity unit associated with external flow \(f\), such as MWh\(_e\), MWh\(_{LHV}\) or t material | flow-specific |
| \(\omega_u,\omega_A,\omega_F\) | Normalising weights in the non-economic physical tie-break | inverse unit of the associated term |

The numerical values and sources of all reported parameters are maintained in
`PARAMETER_SOURCE_REGISTER.md`.

## 5. Decision variables and domains

| Symbol | Domain | Definition | Unit |
|---|---|---|---|
| \(x_{i,t}\) | \(\mathbb R_{\ge0}\) | Activity rate of process \(i\) in hour \(t\) | activity unit of \(i\)/h |
| \(u_{i,\delta(t)}\) | \(\{0,1\}\) where commitment is modelled | Daily committed state of process \(i\); fixed to one for governed continuous classes and zero for structurally inactive assets | binary |
| \(A_{b,t}\) | \(\mathbb R_{\ge0}\) | End-of-hour inventory of store \(b\) | t material |
| \(F_{\rho,t}\) | \(\mathbb R_{\ge0}\) | Material flow through downstream route \(\rho\) | t material/h |
| \(Y_t^{FP}\) | \(\mathbb R_{\ge0}\) | Total represented final-product output | t final product/h |
| \(G_{w,t}^{prod}\) | \(\mathbb R_{\ge0}\) | Energy generated as WAG carrier \(w\) | MWh\(_{LHV}\)/h |
| \(G_{w,k,t}^{use}\) | \(\mathbb R_{\ge0}\) | WAG carrier \(w\) allocated to eligible consumer \(k\) | MWh\(_{LHV}\)/h |
| \(G_{w,t}^{flare}\) | \(\mathbb R_{\ge0}\) | Explicitly flared or surplus WAG carrier \(w\) | MWh\(_{LHV}\)/h |
| \(N_{k,t}\) | \(\mathbb R_{\ge0}\) | Named natural gas delivered to eligible consumer \(k\) | MWh\(_{LHV}\)/h |
| \(S_t^{sup}\) | \(\mathbb R_{\ge0}\) | Represented steam supplied | t steam/h |
| \(S_t^{spill}\) | \(\mathbb R_{\ge0}\) | Explicit surplus steam | t steam/h |
| \(S_t^{unserved}\) | \(\mathbb R_{\ge0}\) | Unserved represented steam demand | t steam/h |
| \(P_t^{proc}\) | \(\mathbb R_{\ge0}\) | Gross represented process and background electricity demand | MW\(_e\) |
| \(P_{j,t}^{gen}\) | \(\mathbb R_{\ge0}\) | Electricity generated by represented generator interface \(j\) | MW\(_e\) |
| \(P_t^{gen}\) | \(\mathbb R_{\ge0}\) | Represented internal electricity generation | MW\(_e\) |
| \(P_t^{grid}\) | \(\mathbb R_{\ge0}\) | Net grid electricity import | MW\(_e\) |
| \(Q_{f,t}^{ext}\) | \(\mathbb R_{\ge0}\) | Purchased quantity of external flow \(f\) | \(U_f\)/h |
| \(\sigma_r^+\) | \(\mathbb R_{\ge0}\) | Production above the carry-corrected next-block target | t final product |
| \(\sigma_r^-\) | \(\mathbb R_{\ge0}\) | Production below the carry-corrected next-block target | t final product |

Variables are only created where the selected configuration and topology make
them meaningful. A zero value for an inactive route is therefore a topology
decision, not evidence that a physical installation can operate at zero load.

## 6. Constraints

### 6.1 Activity and commitment

For every process with an explicit commitment state:

\[
\underline x_i u_{i,\delta(t)}
\le x_{i,t}
\le \overline x_i u_{i,\delta(t)}
\qquad \forall i\in\mathcal I_c,\ t\in\mathcal T_r.
\]

For a source-classified continuous process, \(u_{i,\delta(t)}=1\) and the
throughput remains endogenous within its bounded range. For a structurally
inactive process, \(u_{i,\delta(t)}=0\).

### 6.2 Material-store conservation

For store \(b\) carrying material \(m(b)\):

\[
A_{b,t}
=
(1-\lambda_b\Delta t_t)A_{b,t-1}
+\Delta t_t\sum_{i\in\mathcal I_c}a_{i,m(b)}^{out}x_{i,t}
-\Delta t_t\sum_{i\in\mathcal I_c}a_{i,m(b)}^{in}x_{i,t}.
\]

The boundary and capacity conditions are:

\[
A_{b,0}=A_b^0,
\qquad
0\le A_{b,t}\le A_b^{max},
\qquad
\underline A_b^{end}\le A_{b,H_r}\le\overline A_b^{end}.
\]

The terminal condition prevents a rolling solve from obtaining apparently
cheap production by emptying a store that the next solve must replenish.

### 6.3 Origin-preserving route conservation

For every represented material junction, inflows from BOF, EAF and imported
slab are retained by route until the required downstream reconciliation point.
For a generic junction material \(m\):

\[
\sum_{\rho\in\mathcal P_m^{in}}F_{\rho,t}
=
\sum_{\rho\in\mathcal P_m^{out}}F_{\rho,t}.
\]

For a route with a cumulative supply cap:

\[
\sum_{t<d}\Delta t_t F_{\rho,t}
\le U_{\rho,d}^{max}
\qquad \forall d\in\mathcal D_r.
\]

This form is used for site, BOF and EAF scrap limits and for imported-slab
limits. Route caps are not hourly delivery schedules.

### 6.4 Final-product construction and production deadlines

Final product is the sum of the represented downstream product routes:

\[
Y_t^{FP}=\sum_{\rho\in\mathcal P^{final}}F_{\rho,t}.
\]

Every cumulative deadline requires:

\[
\sum_{t<d}\Delta t_tY_t^{FP}
\ge Q_{r,d}^{min}
\qquad \forall d\in\mathcal D_r.
\]

The final planning-horizon deadline equals the configured horizon quota.

### 6.5 Rolling production-progress identity

The carry-corrected target in the next executed block is:

\[
q_r^{next}
=
\max\left(0,(r+1)q^{blk}-X_r\right).
\]

The next-block deviation variables satisfy:

\[
\sum_{t\in\mathcal E_r}\Delta t_tY_t^{FP}-q_r^{next}
=\sigma_r^+-\sigma_r^-.
\]

Both \(\sigma_r^+\) and \(\sigma_r^-\) are non-negative and measured in
tonnes of final product. They are not unmet-demand penalty costs.

### 6.6 WAG production and carrier balances

For each WAG carrier:

\[
G_{w,t}^{prod}
=
\sum_{i\in\mathcal I_c}\beta_{i,w}x_{i,t},
\]

and

\[
G_{w,t}^{prod}
=
\sum_{k\in\mathcal K_c}G_{w,k,t}^{use}
+G_{w,t}^{flare}.
\]

An allocation variable exists only if carrier \(w\) is eligible for consumer
\(k\). BFG, COG and BOFG remain separate carriers. No hourly WAG store,
mixed-gas carrier or Wobbe-quality constraint is present.

### 6.7 Consumer heat and WAG-first policy

For each represented heat consumer \(k\):

\[
\sum_{w\in\mathcal W}G_{w,k,t}^{use}+N_{k,t}
=h_{i(k),k}x_{i(k),t}.
\]

Natural gas is available only for explicitly eligible consumers. The
lexicographic physical tie-break gives eligible WAG priority over avoidable NG
where both satisfy the same represented heat demand. It does not infer a
plant-wide WAG/NG mixture.

### 6.8 Aggregated steam service

The represented steam supply is coupled to boiler fuel heat:

\[
\kappa^{steam}S_t^{sup}
=
\sum_{w\in\mathcal W}G_{w,steam,t}^{use}+N_{steam,t}.
\]

The instantaneous steam balance is:

\[
S_t^{sup}+S_t^{unserved}
=S_c^{dem}+S_t^{spill}.
\]

The accepted solution requires \(S_t^{unserved}=0\). There is no steam-store
state variable in the core model.

### 6.9 Internal generation and electricity balance

For a represented generator \(j\) with an accepted electrical conversion:

\[
P_{j,t}^{gen}
=
\eta_j^{el}
\left(\sum_{w\in\mathcal W}G_{w,j,t}^{use}+N_{j,t}\right),
\]

\[
0\le P_{j,t}^{gen}\le\overline P_j^{gen}.
\]

Total represented internal generation is:

\[
P_t^{gen}=\sum_{j\in\mathcal J_c}P_{j,t}^{gen}.
\]

The gross represented electricity demand is:

\[
P_t^{proc}
=P_c^{base}+\sum_{i\in\mathcal I_c}e_ix_{i,t}.
\]

The site electricity balance is:

\[
P_t^{grid}+P_t^{gen}=P_t^{proc}.
\]

Export is absent, so internal generation is additionally bounded by gross
represented demand. IJ01 retains an energy-conserving interface without an
invented electrical efficiency and is not a price-responsive generator in the
core formulation.

### 6.10 External-procurement identities

Every external-flow variable \(Q_{f,t}^{ext}\) is linked to one and only one
physical purchase. Examples are net grid import, named NG, purchased dry coal,
PCI, represented ore, imported DR pellets, purchased scrap and imported slab.
Internal coke, WAG, steam and internal generation are not external purchases.

For example, the represented NG purchase identity is:

\[
Q_{NG,t}^{ext}=N_c^{base}+\sum_{k\in\mathcal K_c}N_{k,t},
\]

where all terms are in MWh\(_{LHV}\)/h. The fixed site service
\(N_c^{base}\) is purchased and priced once but is not allocated to a process
heat balance.

## 7. Lexicographic deterministic objective

The model has one ordered objective. The three expressions below are its
lexicographic components, not independent objectives that can trade against
one another. Let \(\mathbf z\) denote the complete decision-variable vector
and \(\mathcal F\) the feasible set defined by Sections 6.1 through 6.10. The active
objective is:

\[
\boxed{
\underset{\mathbf z\in\mathcal F}{\operatorname{lexmin}}
\left(D_r^{prod},C_r^{proc},J_r^{tie}\right).
}
\]

In words: first minimise deviation from the rolling production trajectory;
among those schedules minimise represented procurement cost; among equally
feasible and equally costly schedules select the physically cleanest solution.

### 7.1 Tier 1: production progress

\[
D_r^{prod}=\sigma_r^++\sigma_r^-
\qquad [\mathrm{t\ final\ product}].
\]

After solving, the model preserves:

\[
D_r^{prod}\le D_r^{prod,*}+\tau^{prog}.
\]

### 7.2 Tier 2: represented procurement cost

\[
C_r^{proc}
=
\sum_{t\in\mathcal T_r}\Delta t_t
\sum_{f\in\mathcal F_c^{ext}}
\pi_{f,t}Q_{f,t}^{ext}
\qquad [\mathrm{EUR}].
\]

After solving, the model preserves:

\[
C_r^{proc}\le C_r^{proc,*}+\tau^{cost}.
\]

### 7.3 Tier 3: physical tie-break

\[
J_r^{tie}
=
\omega_u\sum_{i,t}u_{i,\delta(t)}
+\omega_A\sum_{b,t}A_{b,t}
+\omega_F\sum_{w,t}G_{w,t}^{flare}
+J_r^{controller}.
\]

The weights normalise unlike physical units and are subordinate to the two
preserved optima. \(J_r^{controller}\) is a dimensionless expression that
contains governed, non-economic preferences such as WAG-first allocation. The
tie-break must not be reported
as plant profit, operating expenditure or willingness to pay.

An asterisk, as in \(D_r^{prod,*}\) or \(C_r^{proc,*}\), denotes the optimum
obtained for that component before its preservation constraint is added.

## 8. Rolling execution

For each replan \(r\):

1. load the realised initial inventories \(A_b^0\) and cumulative executed
   production \(X_r\);
2. construct the carry-corrected deadlines and next-block target;
3. solve the three lexicographic tiers;
4. retain only decisions for \(t\in\mathcal E_r\);
5. update stores and cumulative production from executed decisions;
6. advance the information and planning horizon.

Costs and physical totals reported for a rolling run use executed hours only.
Overlapping look-ahead hours are never counted more than once.

## 9. Core reporting boundary

The core reports:

- final-product output and route origin;
- material purchases and inventories;
- carrier-specific WAG generation, allocation and flare;
- named NG and the fixed represented NG service;
- gross electricity, internal generation and net grid import;
- represented steam demand, supply, spill and unserved steam;
- represented procurement cost;
- partial point-of-oxidation direct-emissions accounting.

It does not support a claim of full-site steam closure, complete Scope 1,
Scope 2, ETS liability, product margin or whole-site profit.
