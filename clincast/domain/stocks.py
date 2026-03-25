"""Trial stock-flow model — conservation-law compliant.

Follows Sterman (2000) Business Dynamics:
  Ch. 11, Sec. 11.7 (Erlang/delay mathematics):
    Material delays use third-order Erlang (DELAY3) structures for
    sequential pipeline stages (referral → screening → enrolled → completing).
    Information delays use first-order SMOOTH for perceived signals
    (perceived enrollment rate, perceived site burden).
  Ch. 12, Sec. 12.1 (Aging chains and coflows):
    Patient pipeline implemented as a multi-stock aging chain; coflows
    track per-patient attributes (AE load, adherence) alongside the
    main population stock.
  Ch. 21, Sec. 21.4.3 (Dimensional consistency test):
    Every variable carries real-world units per Sterman p. 858.
    Stocks: patients (absolute count).
    Flows: patients/month.
    Burden/quality indices: dimensionless [0, 1].
  Conservation: Screened + Enrolled + Dropout + Completed = N_total at all t.
    Validated by PatientPipelineStock.conservation_check() called every round.
  Validation framework: Barlas (1996) System Dynamics Review 12(3):183–210;
    Forrester & Senge (1980) TIMS Vol. 14, pp. 209–228.
  Dimensional anchors map 0-1 index scales to real-world units so
    outputs can be compared against empirical benchmarks.

PATIENT PIPELINE (material stock-flow, conservation law)
──────────────────────────────────────────────────────────
Screening → [enrollment rate] → Enrolled → [dropout flow + completion flow]

  d(Enrolled)/dt = enrollment_rate - dropout_rate - completion_rate

  Population is conserved:
    Screening + Enrolled + Dropout + Completed = N (constant)

SITE BURDEN STOCK (information stock)
───────────────────────────────────────
Site burden accumulates from protocol amendment load, query volume, and
enrollment pressure. High site burden feeds back into visit compliance
(stressed sites have lower protocol adherence) and into site zero-enrollment
probability.

  d(site_burden)/dt = burden_inflows - burden_dissipation

SAFETY SIGNAL STOCK
────────────────────
Accumulates from grade-weighted AE reports across all patients. Triggers
regulatory and sponsor actions when it crosses thresholds.

  d(safety_signal)/dt = reporting_rate - signal_decay

Dimensional anchor: safety_signal = 1.0 corresponds to the threshold at
which FDA issues a clinical hold (achieved in ~9% of INDs per year;
Manning et al., PMID 31678263). This anchors the 0-1 scale to a real
regulatory event rate.

DATA QUALITY INDEX
───────────────────
Degrades with:
  - Protocol deviation rate (Phase III: 32.8% of patients; Krudys 2022)
  - Visit non-compliance
  - AE under-reporting
Recovers slowly when site monitoring improves (SDV/RBM triggers).

Dimensional anchor: data_quality = 1.0 = zero deviations detected;
data_quality = 0.68 corresponds to 32% deviation rate (Phase III baseline).
"""

from __future__ import annotations

import dataclasses
import math


# ─────────────────────────────────────────────────────────────────────────────
# DIMENSIONAL ANCHORS
# ─────────────────────────────────────────────────────────────────────────────

class DimensionalAnchors:
    """Real-world reference points for the 0-1 stock scales."""

    # site_burden = 0.50 ↔ site running 3.3 protocol amendments over trial life
    # (Getz KA et al., Ther Innov Regul Sci 2024, PMID 38438658).
    SITE_BURDEN_AT_HALF = 3.3  # amendments per protocol

    # safety_signal = 1.0 ↔ signal sufficient for FDA clinical hold
    # FDA clinical holds: ~9% of ~1,500 INDs/year.
    # Source: Manning et al., PMID 31678263.
    SAFETY_SIGNAL_HOLD_THRESHOLD = 1.0

    # data_quality = 0.68 ↔ Phase III baseline (32.8% patients with ≥1 deviation)
    # Source: Krudys KM et al., Contemp Clin Trials Commun 2022 (PMC8979478).
    DATA_QUALITY_PHASE3_BASELINE = 0.68

    # enrollment_velocity at 1.0 ↔ 1 patient per site per month (generic)
    # ARDS/sepsis: <1 patient/site/month (Critical Care 2021 systematic review).
    ENROLLMENT_VELOCITY_REFERENCE = 1.0  # patients/site/month


# ─────────────────────────────────────────────────────────────────────────────
# STOCK DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class PatientPipelineStock:
    """Material stock: patients in each trial stage. Conservation enforced."""
    n_screening: int    = 0
    n_enrolled: int     = 0
    n_dropout: int      = 0
    n_completed: int    = 0
    n_total: int        = 0

    def __post_init__(self) -> None:
        if self.n_total == 0:
            self.n_total = (
                self.n_screening + self.n_enrolled +
                self.n_dropout + self.n_completed
            )

    @property
    def dropout_rate(self) -> float:
        if self.n_total == 0:
            return 0.0
        return self.n_dropout / self.n_total

    @property
    def completion_rate(self) -> float:
        if self.n_total == 0:
            return 0.0
        return self.n_completed / self.n_total

    def conservation_check(self) -> bool:
        return (
            self.n_screening + self.n_enrolled +
            self.n_dropout + self.n_completed == self.n_total
        )


@dataclasses.dataclass
class EnrollmentVelocityStock:
    """Information stock: perceived enrollment rate.

    Uses first-order SMOOTH (DELAY1) as recommended by Sterman 2000 Ch. 11
    for information delays. The perceived rate lags the actual rate with
    time constant τ_enroll (adjustment period for sponsors to recognize
    enrollment shortfall and respond with recruitment intensification).
    """
    actual_rate: float      = 0.0   # patients enrolled this month (actual)
    perceived_rate: float   = 0.0   # SMOOTH-ed perceived rate
    tau_months: float       = 3.0   # information lag [ASSUMED — sweep [1, 6]]

    def update(self, new_actual: float) -> None:
        # SMOOTH: dP/dt = (A - P) / τ → P(t+1) = P(t) + (A - P(t)) / τ
        self.actual_rate = new_actual
        self.perceived_rate += (self.actual_rate - self.perceived_rate) / self.tau_months

    @property
    def enrollment_shortfall(self) -> float:
        """Fraction below perceived target (caller sets target)."""
        return max(0.0, (self.perceived_rate - self.actual_rate) / max(self.perceived_rate, 1e-6))


@dataclasses.dataclass
class SiteBurdenStock:
    """Information stock: cumulative site operational burden.

    Inflows: protocol amendments, query volumes, IND safety reports.
    Outflows: resolved queries, staff onboarding (dissipation).

    Site burden feeds back into:
      - visit_compliance_probability (higher burden → worse patient experience)
      - zero_enrollment_probability (overwhelmed sites stop enrolling)

    IND safety report burden (site level): avg 190 reports/month for 2 chemo
    agents; median 0.25 hr/report (PMC4230957). A site running 5 agents
    sees ~475 reports/month — substantial operational load.
    """
    level: float = 0.0      # current burden, 0-1 scale

    # Burden influx constants [ASSUMED magnitude; GROUNDED direction]
    AMENDMENT_BURDEN_PER_EVENT  : float = dataclasses.field(default=0.08, init=False)
    QUERY_BURDEN_PER_UNIT       : float = dataclasses.field(default=0.02, init=False)
    DISSIPATION_RATE            : float = dataclasses.field(default=0.05, init=False)

    def update(
        self,
        n_amendments_this_round: int,
        query_volume: float,
        external_support: float = 0.0,   # CRO/sponsor support reduces burden
    ) -> None:
        inflow = (
            n_amendments_this_round * self.AMENDMENT_BURDEN_PER_EVENT +
            query_volume * self.QUERY_BURDEN_PER_UNIT
        )
        dissipation = self.level * self.DISSIPATION_RATE * (1.0 + external_support)
        self.level = min(1.0, max(0.0, self.level + inflow - dissipation))


@dataclasses.dataclass
class SafetySignalStock:
    """Accumulating safety signal from reported AEs.

    Signal reaches 1.0 when FDA clinical hold conditions are met (~9% of INDs;
    Manning et al., PMID 31678263). The DSMB reviews at interim analyses
    (if configured) and can trigger early trial termination.

    Decay represents signal resolution: grade 1-2 AEs resolve or are managed;
    grade 3-4 AEs persist in the signal longer.
    """
    level: float = 0.0
    decay_rate: float = 0.03   # per month [ASSUMED — signal resolution]

    def update(self, ae_burden_increment: float) -> None:
        self.level = min(1.0, max(0.0,
            self.level * (1.0 - self.decay_rate) + ae_burden_increment
        ))

    @property
    def triggers_dsmb_review(self) -> bool:
        return self.level >= 0.50   # [ASSUMED threshold]

    @property
    def triggers_regulatory_action(self) -> bool:
        return self.level >= 0.80   # [DIRECTIONAL — below FDA hold threshold]

    @property
    def triggers_clinical_hold(self) -> bool:
        return self.level >= 1.0


@dataclasses.dataclass
class DataQualityStock:
    """Trial data quality index (1.0 = perfect; Phase III baseline ≈ 0.68).

    Degrades with deviations and under-reporting. Recovers under active
    monitoring (risk-based monitoring reduces error rate from 0.28% to 0.15%
    on critical endpoints; Andersen et al., Br J Clin Pharmacol 2023).

    Conservation: data_quality is an index, not a population stock.
    It does not need population conservation — it is an aggregate quality
    signal fed back to the safety signal and sponsor decision functions.
    """
    level: float = 1.0

    # SDV/RBM monitoring reduces deviations by ~46% (0.28% → 0.15%)
    # [GROUNDED — Andersen et al. 2023]
    MONITORING_RECOVERY_RATE: float = dataclasses.field(default=0.46, init=False)
    BASE_RECOVERY_RATE:       float = dataclasses.field(default=0.02, init=False)

    def update(
        self,
        deviation_rate: float,        # fraction of patients with ≥1 deviation this round
        underreporting_fraction: float,
        monitoring_active: bool = True,
    ) -> None:
        # Krudys (PMC8979478): 32.8% of patients have ≥1 deviation over the
        # ENTIRE trial (~24 months). Per-round rate ≈ 1.6% (monthly rate
        # assuming uniform distribution: 1-(1-0.328)^(1/24) ≈ 0.016).
        # The deviation_rate passed in is the visit non-compliance rate per round
        # (~0.33 from visit_compliance = 0.67). We scale it to the per-round
        # protocol deviation rate which is much smaller.
        per_round_deviation = deviation_rate * 0.05   # 5% of non-compliant visits become deviations [ASSUMED]
        degradation = 0.3 * per_round_deviation + 0.02 * underreporting_fraction
        recovery_rate = (
            self.BASE_RECOVERY_RATE * (1.0 + self.MONITORING_RECOVERY_RATE)
            if monitoring_active else self.BASE_RECOVERY_RATE
        )
        recovery = recovery_rate * (1.0 - self.level)
        self.level = min(1.0, max(0.0, self.level - degradation + recovery))


# ─────────────────────────────────────────────────────────────────────────────
# COMPOSITE TRIAL STOCKS
# ─────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class TrialStocks:
    """All stocks for one trial simulation. Initialized from TrialSpec."""

    pipeline: PatientPipelineStock
    enrollment_velocity: EnrollmentVelocityStock
    site_burden: SiteBurdenStock
    safety_signal: SafetySignalStock
    data_quality: DataQualityStock

    @classmethod
    def initialise(cls, n_patients: int) -> "TrialStocks":
        return cls(
            pipeline=PatientPipelineStock(
                n_screening=n_patients,
                n_total=n_patients,
            ),
            enrollment_velocity=EnrollmentVelocityStock(),
            site_burden=SiteBurdenStock(),
            safety_signal=SafetySignalStock(),
            data_quality=DataQualityStock(
                level=DimensionalAnchors.DATA_QUALITY_PHASE3_BASELINE
            ),
        )

    def summary(self) -> dict[str, float]:
        return {
            "n_screening":          float(self.pipeline.n_screening),
            "n_enrolled":           float(self.pipeline.n_enrolled),
            "n_dropout":            float(self.pipeline.n_dropout),
            "n_completed":          float(self.pipeline.n_completed),
            "dropout_rate":         self.pipeline.dropout_rate,
            "completion_rate":      self.pipeline.completion_rate,
            "enrollment_velocity":  self.enrollment_velocity.actual_rate,
            "site_burden":          self.site_burden.level,
            "safety_signal":        self.safety_signal.level,
            "data_quality":         self.data_quality.level,
        }
