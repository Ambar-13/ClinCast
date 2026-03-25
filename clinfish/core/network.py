"""Patient social network topology.

Patients do not form scale-free networks like corporations. The empirical
topology of patient communities has three distinct structural layers:

  Family / caregiver units
    Dense cliques of 2-6 people (patient + primary caregiver + immediate
    family). High within-clique edge density (~0.8). Strong influence
    weight: Golin et al. (2006) J Gen Intern Med found family support
    explained 23% of adherence variance in HIV+ populations.

  Disease community / peer support
    Moderately dense subgraphs of 10-50 patients with shared diagnosis.
    Formed through patient forums (PatientsLikeMe, DailyStrength) and
    in-person support groups. Stochastic block model with p_in ≈ 0.15,
    p_out ≈ 0.01 fits online health community network data from
    Frost & Massagli (2008) J Med Internet Res.

  Clinical site cohort
    Patients at the same site share a weak structural connection through
    staff behaviour and site culture. p_in ≈ 0.05 within site. This
    captures the site random effect observed in multi-centre ICCs
    (median ICC ≈ 0.05 in clinical trial adherence outcomes;
    Donner & Klar, 2000, Design and Analysis of Cluster Randomization Trials).

  Patient advocates / high-degree hubs
    2-5% of patients in disease communities are high-engagement advocates
    (high forum activity, peer support volunteers). These get additional
    edges to span community boundaries, creating the small-world property
    observed empirically in online health networks (diameter ≈ 4-6 for
    PatientsLikeMe; data from Wicks et al., 2010).

The resulting network is a stochastic block model with hub augmentation.
This is more realistic than a Barabasi-Albert graph for patient populations
because the clustering comes from social context (family, diagnosis, site)
rather than preferential attachment.

DeGroot belief propagation on this topology:
  Each round, every enrolled patient's belief is updated as a weighted average
  of their own belief and their neighbors' beliefs.

    b_i(t+1) = α_i · b_i(t) + (1 - α_i) · mean_{j ∈ N(i)} b_j(t)

  α_i is the patient's stubbornness parameter. Higher health literacy →
  lower α (more open to information). Higher prior trial experience → higher α
  (more anchored to own assessment).

  This is the DeGroot (1974) model, with the Friedkin-Johnsen (1990)
  extension where self-weight α_i is heterogeneous across agents.

  Stubbornness calibration:
    Central estimate w_ii = 0.5, distributed as Beta(α, β) with κ = α+β = 4,
    corresponding to Beta(2, 2) symmetric. Source: Johnson KL & Carnegie NB,
    Int J Environ Res Public Health 2022, PMC8709162 — genetic algorithm
    estimation of DeGroot parameters from 5 snowball-sampled health behavior
    networks (n=40, PrEP willingness and HIV self-efficacy).

  Convergence behavior:
    Health behaviors are complex contagions (Centola 2010, Science 329:1194)
    requiring redundant exposure from clustered ties, not single-contact spread.
    The clustered SBM topology here (high p_family, moderate p_community) is
    consistent with complex contagion requirements. Convergence rate governed
    by second-largest eigenvalue modulus of T (Olshevsky & Tsitsiklis, 2011).
    DeGroot global consensus requires strongly connected, aperiodic T.

  Empirical note on dynamics:
    ~15% of real social network users follow DeGroot-style weighted averaging;
    ~65% follow Voter model dynamics (Das, Gollapudi & Munagala, WWW 2014).
    This model uses DeGroot as the computationally tractable approximation.
    Negative influence (repulsion from distant opinions) is empirically
    significant (Peralta et al., JASSS 2025) but not modelled here [ASSUMED].
"""

from __future__ import annotations

import numpy as np
import networkx as nx


def build_patient_network(
    n_patients: int,
    n_sites: int,
    site_ids: np.ndarray,
    n_advocates: int | None = None,
    p_family: float = 0.8,
    p_community: float = 0.15,
    p_site: float = 0.05,
    seed: int = 0,
) -> nx.Graph:
    """Build a stochastic block model patient influence network.

    Blocks correspond to disease communities (one per site, with cross-site
    spillover for rare diseases). Family cliques are embedded within blocks.
    Hub advocates span multiple communities.

    Args:
        n_patients:    Total patient count.
        n_sites:       Number of clinical sites (= number of primary blocks).
        site_ids:      Array of shape (n_patients,) mapping patient → site.
        n_advocates:   Number of high-degree advocate nodes. Defaults to
                       max(2, int(0.03 * n_patients)) — roughly 3%, consistent
                       with active participation rates in online health forums
                       (Fox & Duggan, Pew Research 2013: ~3% post actively).
        p_family:      Within-family clique edge probability.
        p_community:   Within-disease-community edge probability.
        p_site:        Within-site (but cross-community) edge probability.
        seed:          RNG seed.
    """
    rng = np.random.default_rng(seed)

    if n_advocates is None:
        n_advocates = max(2, int(0.03 * n_patients))

    G = nx.Graph()
    G.add_nodes_from(range(n_patients))

    # Attach site metadata
    for i in range(n_patients):
        G.nodes[i]["site"] = int(site_ids[i])

    # ── Family cliques ────────────────────────────────────────────────────────
    # Assign each patient to a family unit (size 2-5, Poisson with mean 3).
    # Patients in the same family clique have dense edges.
    family_id = np.full(n_patients, -1, dtype=np.int32)
    unassigned = list(range(n_patients))
    rng.shuffle(unassigned)
    fid = 0
    i = 0
    while i < len(unassigned):
        size = min(int(rng.poisson(3)) + 1, len(unassigned) - i)
        size = max(size, 1)
        members = unassigned[i:i + size]
        for m in members:
            family_id[m] = fid
        # Add edges within family clique with probability p_family
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                if rng.random() < p_family:
                    G.add_edge(members[a], members[b], weight=1.5, layer="family")
        fid += 1
        i += size

    G.graph["family_id"] = family_id

    # ── Disease community edges (within-site) ─────────────────────────────────
    site_groups: dict[int, list[int]] = {}
    for patient_idx in range(n_patients):
        s = int(site_ids[patient_idx])
        site_groups.setdefault(s, []).append(patient_idx)

    for site, members in site_groups.items():
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                if rng.random() < p_community:
                    if not G.has_edge(members[a], members[b]):
                        G.add_edge(members[a], members[b], weight=1.0,
                                   layer="community")

    # ── Site cohort edges (cross-community within site) ───────────────────────
    # Weaker edges representing shared site culture / staff interaction
    for site, members in site_groups.items():
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                if not G.has_edge(members[a], members[b]):
                    if rng.random() < p_site:
                        G.add_edge(members[a], members[b], weight=0.5,
                                   layer="site")

    # ── Advocate hubs ─────────────────────────────────────────────────────────
    # Select advocates preferentially from high-degree existing nodes (they're
    # already well-connected — consistent with observed forum moderator profiles).
    degrees = np.array([G.degree(i) for i in range(n_patients)], dtype=float)
    if degrees.sum() > 0:
        probs = degrees / degrees.sum()
    else:
        probs = np.ones(n_patients) / n_patients

    advocate_ids = rng.choice(n_patients, size=n_advocates, replace=False, p=probs)

    for adv in advocate_ids:
        G.nodes[adv]["advocate"] = True
        # Connect to random patients across all sites (cross-community bridging).
        # Cap n_extra at n_patients - 1 to support very small trial populations.
        n_extra = min(n_patients - 1, int(rng.integers(5, 15)))
        if n_extra > 0:
            targets = rng.choice(n_patients, size=n_extra, replace=False)
            for t in targets:
                if t != adv and not G.has_edge(adv, t):
                    G.add_edge(adv, t, weight=1.2, layer="advocate")

    return G


def compute_degroot_weights(
    G: nx.Graph,
    stubbornness: np.ndarray,
) -> np.ndarray:
    """Compute the DeGroot influence weight matrix T.

    T[i, j] = (1 - α_i) * w_ij / sum_k(w_ik)   for j ≠ i
    T[i, i] = α_i

    where α_i = stubbornness[i] and w_ij is the edge weight.

    Returns a sparse-friendly (n, n) float32 array. For large populations
    (>2000), callers should convert to scipy.sparse for efficiency.

    DeGroot (1974): beliefs converge if T has a unique stationary distribution,
    which holds when the network is strongly connected or has a spanning tree.
    """
    n = G.number_of_nodes()
    T = np.zeros((n, n), dtype=np.float32)

    for i in range(n):
        neighbors = list(G.neighbors(i))
        if not neighbors:
            T[i, i] = 1.0
            continue

        weights = np.array([
            G[i][j].get("weight", 1.0) for j in neighbors
        ], dtype=np.float32)
        total_w = weights.sum()
        alpha_i = float(stubbornness[i])

        T[i, i] = alpha_i
        for j, nb in enumerate(neighbors):
            T[i, nb] = (1.0 - alpha_i) * weights[j] / total_w

    return T


def propagate_beliefs(
    beliefs: np.ndarray,
    T: np.ndarray,
    enrolled_mask: np.ndarray,
) -> np.ndarray:
    """Apply one round of DeGroot belief propagation.

    Only enrolled patients update their beliefs — screening and dropout
    patients are excluded from the network interaction this round.

    Returns updated belief array (same shape as input).
    """
    new_beliefs = beliefs.copy()
    active = np.where(enrolled_mask)[0]

    if len(active) == 0:
        return new_beliefs

    # Sub-matrix of T for active patients only.
    # Rows must be renormalized: the original T rows sum to 1 over ALL patients,
    # but here we only include enrolled patients. The weight that would have gone
    # to unenrolled neighbors is redistributed back to the diagonal (self-weight),
    # equivalent to those neighbors being unavailable for influence this round.
    T_active = T[np.ix_(active, active)]
    row_sums = T_active.sum(axis=1, keepdims=True)
    row_sums = np.where(row_sums > 0, row_sums, 1.0)
    T_active = T_active / row_sums
    b_active = beliefs[active]
    new_beliefs[active] = T_active @ b_active

    return np.clip(new_beliefs, 0.0, 1.0).astype(np.float32)


def network_statistics(G: nx.Graph) -> dict[str, float]:
    """Quick structural summary for reporting."""
    degrees = [d for _, d in G.degree()]
    return {
        "n_nodes": G.number_of_nodes(),
        "n_edges": G.number_of_edges(),
        "mean_degree": float(np.mean(degrees)) if degrees else 0.0,
        "max_degree": float(max(degrees)) if degrees else 0.0,
        "n_components": nx.number_connected_components(G),
        "n_advocates": sum(
            1 for _, data in G.nodes(data=True) if data.get("advocate", False)
        ),
    }
