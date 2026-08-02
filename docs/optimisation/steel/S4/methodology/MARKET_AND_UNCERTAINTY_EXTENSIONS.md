# Deterministic DA, Stochastic, CVaR and mFRR Extensions

## 1. Purpose and inheritance rule

This document defines only the terms added after the core physical model. All
sets, parameters, variables and constraints in `CORE_PHYSICAL_MILP.md` are
inherited unless an extension explicitly replaces them.

The deterministic DA subsection describes the validated Phase-6A contract.
The stochastic, CVaR and mFRR subsections are formulation templates for later
gates and are not yet executable steel-model claims.

## 2. Objective inheritance

The single boxed lexicographic objective is defined only in
`CORE_PHYSICAL_MILP.md`. The current sequential solver stages implement that
one ordered objective. This extension document does not introduce a second
objective: deterministic DA replaces the electricity-price input in its
economic component, stochastic DA takes probability-weighted components, CVaR
adds a risk term to the economic component, and mFRR later replaces procurement
cost with net market cost.

The formulation must not be rewritten as an arbitrary big-\(M\) weighted sum.
That would introduce an unsupported exchange rate between tonnes of production
deviation and euros.

## 3. Deterministic day-ahead extension

### 3.1 Additional notation

| Symbol | Type/domain | Definition | Unit |
|---|---|---|---|
| \(\widehat\pi_{r,t}^{DA}\) | Parameter | Day-ahead point-price forecast available at the submission time of replan \(r\) for delivery hour \(t\) | EUR/MWh\(_e\) |
| \(\pi_t^{real}\) | Ex-post parameter | Realised day-ahead price for delivery hour \(t\); unavailable to the executable optimisation | EUR/MWh\(_e\) |
| \(B_{r,t}^{DA}\) | \(\mathbb R_{\ge0}\) | Submitted price-taking electricity purchase quantity | MWh\(_e\) in interval \(t\) |
| \(Q_{r,t}^{clear}\) | \(\mathbb R_{\ge0}\) | Cleared electricity purchase quantity | MWh\(_e\) in interval \(t\) |
| \(Q_{r,t}^{set}\) | Reporting variable | Settled day-ahead electricity quantity | MWh\(_e\) in interval \(t\) |
| \(C_r^{DA,set}\) | Reporting expression | Realised day-ahead settlement cost over executed hours | EUR |
| \(C_r^{other\ ext}\) | Expression | Cost of non-electric external procurement inherited from the core model | EUR |

The power variable \(P_t^{grid}\) from the core is measured in MW. Its energy
quantity over interval \(t\) is \(\Delta t_tP_t^{grid}\) MWh.

### 3.2 Information constraint

For every forecast value used at replan \(r\), its information timestamp must
be no later than the bid-submission time. Realised \(\pi_t^{real}\) is excluded
from \(\mathcal F\) and from the executable objective.

### 3.3 Price-taking quantity bid

The submitted deterministic purchase quantity is:

\[
B_{r,t}^{DA}=\Delta t_tP_t^{grid}
\qquad \forall t\in\mathcal E_r.
\]

The Phase-6A full-acceptance abstraction imposes:

\[
Q_{r,t}^{clear}=B_{r,t}^{DA},
\qquad
Q_{r,t}^{set}=Q_{r,t}^{clear}.
\]

There is no bid-price decision, rejected quantity, imbalance quantity or
export quantity in this deterministic contract.

### 3.4 Objective and settlement

In the procurement-cost component of the inherited lexicographic objective,
the flat electricity price is replaced by \(\widehat\pi_{r,t}^{DA}\):

\[
C_r^{proc}
=
\sum_{t\in\mathcal T_r}
\widehat\pi_{r,t}^{DA}\Delta t_tP_t^{grid}
+C_r^{other\ ext}.
\]

Here \(C_r^{other\ ext}\) is the cost of the non-electric external flows
defined in the core model and is measured in EUR.

Realised settlement is calculated after execution:

\[
C_r^{DA,set}
=
\sum_{t\in\mathcal E_r}
\pi_t^{real}Q_{r,t}^{set}.
\]

The price-insensitive comparator uses the governed flat EUR 80/MWh schedule.
The perfect-foresight oracle replaces the point forecast with realised prices
only in a separately labelled ex-post counterfactual. It is never submitted.

## 4. Stochastic day-ahead extension

### 4.1 What is inherited

The stochastic model inherits the process topology, material conversions,
stores, route constraints, production deadlines, WAG balances, steam balance,
electricity balance, external-procurement definitions and physical reporting
boundary from the core formulation.

Those equations are not rewritten in the thesis. Instead, the chapter should
state that every recourse equation is imposed for each scenario and time node,
with shared decisions linked by non-anticipativity.

### 4.2 Additional sets, mappings and parameters

| Symbol | Type | Definition | Unit |
|---|---|---|---|
| \(\omega\in\Omega\) | Scenario index | Joint multi-hour price or market scenario | none |
| \(p_\omega\) | Parameter | Probability of scenario \(\omega\) | fraction |
| \(n\in\mathcal N\) | Scenario-tree node index | Information state shared by scenarios up to a given decision time | none |
| \(n(t,\omega)\) | Mapping | Scenario-tree node reached by scenario \(\omega\) at time \(t\) | none |
| \(\pi_{t,\omega}^{DA}\) | Parameter | Day-ahead price in scenario \(\omega\) for delivery interval \(t\) | EUR/MWh\(_e\) |
| \(\mathcal H_n\subseteq\Omega\) | Scenario subset | Scenarios sharing the same information history at node \(n\) | none |

Scenario probabilities must satisfy:

\[
p_\omega\ge0,
\qquad
\sum_{\omega\in\Omega}p_\omega=1.
\]

### 4.3 Scenario-indexed variables

Every decision that can adapt after uncertainty is revealed receives a
scenario index. Examples are:

| Symbol | Domain | Definition | Unit |
|---|---|---|---|
| \(x_{i,t,\omega}\) | \(\mathbb R_{\ge0}\) | Scenario-dependent process activity | activity unit of \(i\)/h |
| \(A_{b,t,\omega}\) | \(\mathbb R_{\ge0}\) | Scenario-dependent store inventory | t material |
| \(P_{t,\omega}^{grid}\) | \(\mathbb R_{\ge0}\) | Scenario-dependent net grid import | MW\(_e\) |
| \(G_{w,k,t,\omega}^{use}\) | \(\mathbb R_{\ge0}\) | Scenario-dependent WAG allocation | MWh\(_{LHV}\)/h |
| \(N_{k,t,\omega}\) | \(\mathbb R_{\ge0}\) | Scenario-dependent named NG allocation | MWh\(_{LHV}\)/h |
| \(B_{n,t}^{DA}\) | \(\mathbb R_{\ge0}\) | DA bid quantity decided at information node \(n\) | MWh\(_e\) |
| \(v_{t,\omega}\) | Domain inherited from the represented decision | Generic placeholder for any scenario-indexed decision used in the non-anticipativity equation | Unit inherited from that decision |

Variables decided before scenarios diverge must be represented by a shared
node variable or constrained to be equal.

### 4.4 Non-anticipativity

For any decision variable \(v\) that must be taken at node \(n\), and for all
scenarios \(\omega,\omega'\in\mathcal H_n\):

\[
v_{t,\omega}=v_{t,\omega'}.
\]

This prevents future realised prices or states from changing an earlier bid or
physical decision. It is the principal structural difference from simply
running the deterministic model once per scenario.

### 4.5 Scenario-wise feasibility

Every physical core equation is imposed for each \(\omega\in\Omega\). For
example, the electricity balance becomes:

\[
P_{t,\omega}^{grid}+P_{t,\omega}^{gen}
=P_{t,\omega}^{proc}
\qquad \forall t,\omega.
\]

The same indexing rule applies to material stores, production deadlines, WAG,
steam and terminal conditions. Any exception must be justified by its
information timing.

### 4.6 Expected-cost objective

Let \(D_\omega^{prod}\), \(C_\omega^{proc}\) and \(J_\omega^{phys}\) be the
scenario-specific versions of the three core objective components, with the
same units as in the deterministic model. The direct stochastic continuation
of the current hierarchy is:

\[
\underset{\mathbf z\in\mathcal F^{stoch}}{\operatorname{lexmin}}
\left(
\sum_{\omega\in\Omega}p_\omega D_\omega^{prod},
\sum_{\omega\in\Omega}p_\omega C_\omega^{proc},
\sum_{\omega\in\Omega}p_\omega J_\omega^{phys}
\right).
\]

Here \(\mathcal F^{stoch}\) is the scenario-wise physical feasible set plus
non-anticipativity. Before implementation, the stochastic gate must decide
whether production deadlines are required in every scenario, which is the
recommended feasibility-preserving default, or whether any explicitly
penalised shortfall is authorised.

## 5. CVaR extension

### 5.1 Additional parameters and variables

| Symbol | Type/domain | Definition | Unit |
|---|---|---|---|
| \(\alpha\) | Parameter in \((0,1)\) | CVaR confidence level | fraction |
| \(\lambda^{risk}\) | Non-negative parameter | Weight assigned to CVaR in the economic objective | dimensionless if expected cost and CVaR are both EUR |
| \(\eta\) | \(\mathbb R\) | Value-at-Risk threshold selected by the model | EUR |
| \(\xi_\omega\) | \(\mathbb R_{\ge0}\) | Cost exceedance above \(\eta\) in scenario \(\omega\) | EUR |

### 5.2 CVaR expression

For scenario procurement or net cost \(C_\omega\) in EUR:

\[
\xi_\omega\ge C_\omega-\eta,
\qquad
\xi_\omega\ge0,
\]

\[
\operatorname{CVaR}_\alpha(C)
=
\eta+
\frac{1}{1-\alpha}
\sum_{\omega\in\Omega}p_\omega\xi_\omega.
\]

CVaR modifies only the economic component of the inherited lexicographic
objective:

\[
C^{risk}
=
\sum_{\omega\in\Omega}p_\omega C_\omega
+\lambda^{risk}\operatorname{CVaR}_\alpha(C).
\]

Values of \(\alpha\) and \(\lambda^{risk}\) must be selected using validation,
not final-test performance.

## 6. Future mFRR extension

This section is a design template. It does not authorise mFRR execution.

### 6.1 Additional sets and parameters

| Symbol | Definition | Unit |
|---|---|---|
| \(a\in\mathcal A^{res}=\{up,down\}\) | Reserve-direction index | none |
| \(\pi_{t}^{cap,a}\) | mFRR capacity price for direction \(a\) | EUR/MW/h |
| \(\pi_{t,\omega}^{act,a}\) | Activation-energy price in scenario \(\omega\) | EUR/MWh |
| \(\zeta_{t,\omega}^{a}\) | Activated fraction of accepted reserve capacity | fraction |
| \(\pi^{imb}_{t,\omega}\) | Imbalance price | EUR/MWh |
| \(\pi^{ndel}\) | Non-delivery penalty rate | EUR/MWh not delivered |
| \(\overline H_{t}^{a}\) | Physically available reserve headroom before a bid in direction \(a\) | MW |
| \(P_t^{DA,base}\) | Cleared day-ahead grid-import baseline before reserve activation | MW\(_e\) |

### 6.2 Additional decision variables

| Symbol | Domain | Definition | Unit |
|---|---|---|---|
| \(R_t^{a}\) | \(\mathbb R_{\ge0}\) | Offered and accepted reserve capacity in direction \(a\) | MW |
| \(p_{t,\omega}^{act,a}\) | \(\mathbb R_{\ge0}\) | Delivered activation power in direction \(a\) | MW |
| \(e_{t,\omega}^{act,a}\) | \(\mathbb R_{\ge0}\) | Delivered activation energy in direction \(a\) | MWh |
| \(e_{t,\omega}^{short,a}\) | \(\mathbb R_{\ge0}\) | Activated reserve energy not delivered in direction \(a\) | MWh |
| \(e_{t,\omega}^{imb}\) | \(\mathbb R\) or split non-negative pair | Residual imbalance energy | MWh |

### 6.3 Basic reserve and activation relations

Offered capacity must fit inside the physical flexibility envelope:

\[
0\le R_t^a\le\overline H_t^a.
\]

Required activated power is \(\zeta_{t,\omega}^{a}R_t^a\). Delivered and
short activation must reconcile:

\[
p_{t,\omega}^{act,a}
+\frac{e_{t,\omega}^{short,a}}{\Delta t_t}
=\zeta_{t,\omega}^{a}R_t^a,
\]

\[
e_{t,\omega}^{act,a}=\Delta t_t p_{t,\omega}^{act,a}.
\]

Upward mFRR from an electricity consumer normally means lower grid import or
higher internal generation relative to the DA baseline. Downward mFRR means
higher grid import or lower internal generation. The sign convention must be
fixed once in the implementation and used consistently in bids, activation,
settlement and plots.

Reserve deliverability must be coupled to the inherited process, inventory,
WAG, steam, electricity, production and terminal constraints. A capacity bid
is not valid merely because the electrical power bound is available at the bid
hour.

### 6.4 Net-cost terms

For scenario \(\omega\), define:

\[
R_\omega^{cap}
=\sum_{t,a}\Delta t_t\pi_t^{cap,a}R_t^a,
\]

\[
R_\omega^{act}
=\sum_{t,a}\pi_{t,\omega}^{act,a}e_{t,\omega}^{act,a},
\]

\[
C_\omega^{ndel}
=\sum_{t,a}\pi^{ndel}e_{t,\omega}^{short,a},
\]

\[
C_\omega^{imb}
=\sum_t\pi_{t,\omega}^{imb}e_{t,\omega}^{imb},
\]

all measured in EUR. The future scenario net cost is then:

\[
C_\omega^{net}
=C_\omega^{proc}
+C_\omega^{imb}
+C_\omega^{ndel}
-R_\omega^{cap}
-R_\omega^{act}.
\]

This \(C_\omega^{net}\) replaces \(C_\omega^{proc}\) in the economic tier of
the stochastic or CVaR objective. The physical production-progress tier remains
ahead of economic optimisation unless a later explicit methodological decision
changes that hierarchy.

## 7. Thesis wording that avoids repetition

Recommended transition sentence for the stochastic subsection:

> The stochastic model retains the physical sets, variables and constraints
> defined in Section X. Scenario-dependent recourse variables are indexed by
> \(\omega\), while decisions made before uncertainty is revealed satisfy
> non-anticipativity. This section therefore reports only the scenario,
> information and risk extensions to the deterministic formulation.

Recommended transition sentence for the mFRR subsection:

> The reserve formulation extends the stochastic DA model with capacity and
> activation decisions. The underlying steel-process feasibility equations are
> unchanged, but reserve deliverability is constrained by their remaining
> electrical and intertemporal headroom.
