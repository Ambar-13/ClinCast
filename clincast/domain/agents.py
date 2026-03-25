"""Patient archetypes and institutional actor definitions.

POPULATION SYNTHESIS
─────────────────────
Patient covariates are drawn at enrollment and held fixed (demographics,
health literacy, site access). Behavioral parameters (stubbornness,
side-effect sensitivity) are archetype-level constants informed by the
clinical literature below.

ARCHETYPE EMPIRICAL BASIS
───────────────────────────
Health literacy distribution:
  Nationwide (US): 12% below basic, 22% basic, 53% intermediate, 14% proficient.
  Source: National Assessment of Adult Literacy, NCES 2003 (Kutner et al.).
  Used to calibrate health_literacy_shift per therapeutic area — oncology trials
  tend to recruit more educated patients; CNS trials recruit broader populations.

Age-dropout interaction:
  Older age is a statistically significant predictor of dropout in AD trials.
  A4 Study (preclinical AD, n=4,486): OR = 1.06 per year (95% CI 1.03–1.09).
  Source: Donohue MC et al., Alzheimer's & Dementia 2020.

Family support → adherence:
  Family functioning explains variance in adherence: overall r = 0.18
  (95% CI 0.15–0.20; n = 8,531 participants, k = 52 studies).
  Family conflict: r = −0.18 (95% CI −0.21 to −0.15).
  Source: Molloy GJ et al., Health Psychology Review, meta-analysis, 2018
  (PMC7967873).

Geographic access:
  70% of patients live >1 hour from a study site.
  Source: Milken Institute, "Obstacles and Opportunities in Clinical
  Trial Participation," 2022.
  Cancer trial centers are in areas with +10.1% more white residents
  than the national average (95% CI +6.8–+13.7%).
  Source: Loree JM et al., JAMA Oncology 2019.

INSTITUTIONAL ACTOR BASIS
───────────────────────────
Protocol amendments:
  76% of trials (n=950 protocols, 2,188 amendments) require ≥1 substantial
  amendment; 3.3 amendments per protocol on average.
  Implementation: 260 days to ethics approval; sites run multiple protocol
  versions for an average of 215 days.
  Source: Getz KA et al., Therapeutic Innovation & Regulatory Science,
  May 2024 (PMID 38438658).

Site zero-enrollment:
  ~10–11% of sites activated for a trial enroll zero patients.
  Source: Tufts CSDD 2012 survey (16,000 sites).

Protocol deviations:
  Phase III: 118.5 deviations per protocol; 32.8% of patients have ≥1.
  Oncology: 108.8 per protocol; 46.6% of patients.
  Source: Krudys KM et al., Contemp Clin Trials Commun, 2022 (PMC8979478).
"""

from __future__ import annotations

import dataclasses
from enum import IntEnum

import numpy as np


# ─────────────────────────────────────────────────────────────────────────────
# PATIENT ARCHETYPES
# ─────────────────────────────────────────────────────────────────────────────

class ArchetypeID(IntEnum):
    TREATMENT_NAIVE_HIGH_ANXIETY  = 0
    EXPERIENCED_ADVOCATE          = 1
    CAREGIVER_DEPENDENT_ELDERLY   = 2
    LOW_ACCESS_RURAL              = 3
    MOTIVATED_YOUNG_ADULT         = 4


@dataclasses.dataclass(frozen=True)
class PatientArchetype:
    """Fixed behavioral profile for a patient archetype.

    These are central tendency values. Per-patient draws add noise around these
    via the covariate distributions in vectorized.py.
    """
    name: str
    archetype_id: ArchetypeID

    # DeGroot stubbornness α ∈ (0, 1). Higher = more anchored to own prior.
    # Centola (2010) Science 329:1194: health behavior adoption in online
    # networks showed convergence in ~5–8 rounds at α ≈ 0.7.
    stubbornness: float

    # Weibull λ multiplier relative to the TA baseline. A multiplier of 1.5
    # means this archetype drops out 1.5× faster than the TA baseline.
    # Derived from: experienced advocates have better retention (lower hazard);
    # high-anxiety patients have higher early dropout.
    dropout_hazard_multiplier: float

    # Baseline daily adherence probability before protocol burden adjustments.
    # Calibrated to MEMS cross-study mean of 74.9% (range 53.4–92.9%).
    # Source: Medication Event Monitoring System systematic review
    # (Bova et al., 2005; Vrijens & Urquhart, 2005).
    baseline_adherence: float

    # AE sensitivity: how much cumulative AE load increases dropout hazard.
    # Scale: 0 (insensitive) to 1 (one unit of AE load doubles hazard).
    ae_sensitivity: float

    # Fraction of grade 1-2 AEs actually reported by this archetype.
    # High-literacy patients report more. Clinicians document median 3 events
    # vs. patients' 11 (Basch E et al., PMC8502480, 2021). We use patient-
    # reported fractions here since we're modelling patient self-report behaviour.
    ae_reporting_fraction: float

    # Site visit compliance probability per scheduled visit.
    # FDA guidance: <80% visit attendance constitutes a major protocol deviation.
    visit_compliance_base: float

    # Proportion of this archetype in default population mix (must sum to 1).
    default_proportion: float

    # Big Five Conscientiousness trait score (0-1, normalized from standard scoring).
    # Meta-analysis: Roberts MW et al. Psychological Bulletin 2009 — r=0.19 adherence correlation.
    # [GROUNDED direction; archetype-level values DIRECTIONAL]
    conscientiousness: float = 0.5   # default middle

    # IPQ-R Personal Control subscale (0-1).
    # Hagger MS & Orbell S, Health Psychology Review 2003, meta-analysis n=45 studies:
    # Personal control predicts coping and treatment adherence (mean r=0.21).
    # [GROUNDED direction; archetype values DIRECTIONAL]
    personal_control: float = 0.5    # default middle


ARCHETYPES: dict[ArchetypeID, PatientArchetype] = {

    ArchetypeID.TREATMENT_NAIVE_HIGH_ANXIETY: PatientArchetype(
        name="treatment_naive_high_anxiety",
        archetype_id=ArchetypeID.TREATMENT_NAIVE_HIGH_ANXIETY,
        # Higher anxiety → less anchored early, then increasingly stubborn.
        # A4 Study: STAI anxiety score OR = 1.07 per unit for dropout.
        stubbornness=0.55,
        # High early dropout hazard: lack of familiarity with trial procedures.
        dropout_hazard_multiplier=1.4,
        # MEMS lower bound cohort.
        baseline_adherence=0.68,
        # Highly sensitive: AE confirms fears.
        ae_sensitivity=0.75,
        # Limited ability to distinguish expected vs. unexpected AEs.
        ae_reporting_fraction=0.45,
        # Anxious about missing visits but also anxious about coming in.
        visit_compliance_base=0.82,
        default_proportion=0.20,
        conscientiousness=0.55,
        personal_control=0.35,
    ),

    ArchetypeID.EXPERIENCED_ADVOCATE: PatientArchetype(
        name="experienced_advocate",
        archetype_id=ArchetypeID.EXPERIENCED_ADVOCATE,
        # High health literacy → lower stubbornness (more open to evidence).
        # Also a network hub (handled in patient_network.py advocate selection).
        stubbornness=0.45,
        # Best retention: experienced with trial logistics, motivated advocates.
        dropout_hazard_multiplier=0.55,
        # High adherence — MEMS upper bound.
        baseline_adherence=0.88,
        # Low sensitivity: understands AE profile, distinguishes expected effects.
        ae_sensitivity=0.25,
        # High reporting: health literate, motivated to contribute data quality.
        ae_reporting_fraction=0.85,
        # High visit compliance: logistics solved from prior experience.
        visit_compliance_base=0.93,
        default_proportion=0.15,
        conscientiousness=0.80,
        personal_control=0.75,
    ),

    ArchetypeID.CAREGIVER_DEPENDENT_ELDERLY: PatientArchetype(
        name="caregiver_dependent_elderly",
        archetype_id=ArchetypeID.CAREGIVER_DEPENDENT_ELDERLY,
        # Beliefs highly influenced by caregiver (family support r = 0.18,
        # Molloy et al. 2018). Caregiver becomes the de-facto network node.
        stubbornness=0.70,
        # AD Phase 3 mean dropout 21.2% ± 10.8% at 1.4 years; older age
        # OR = 1.06 per year.
        dropout_hazard_multiplier=1.2,
        # Adherence depends heavily on caregiver organisation.
        baseline_adherence=0.72,
        # High sensitivity: functional decline amplifies AE concerns.
        ae_sensitivity=0.65,
        # Low self-reporting; AEs reported by caregiver (less complete).
        ae_reporting_fraction=0.50,
        # Variable: caregiver availability determines visit attendance.
        visit_compliance_base=0.78,
        default_proportion=0.20,
        conscientiousness=0.60,
        personal_control=0.40,
    ),

    ArchetypeID.LOW_ACCESS_RURAL: PatientArchetype(
        name="low_access_rural",
        archetype_id=ArchetypeID.LOW_ACCESS_RURAL,
        # Moderate stubbornness; isolated from peer influence networks.
        stubbornness=0.65,
        # Primary dropout driver: site access burden (70% live >1hr from site;
        # Milken Institute, 2022). Visit non-compliance accumulates dropout risk.
        dropout_hazard_multiplier=1.35,
        # Adherence moderate — less pharmacy access for refills.
        baseline_adherence=0.70,
        # Moderate AE sensitivity.
        ae_sensitivity=0.50,
        # Low reporting: logistical barriers to contacting site staff.
        ae_reporting_fraction=0.40,
        # Visit compliance is the main vulnerability for this archetype.
        visit_compliance_base=0.68,
        default_proportion=0.25,
        conscientiousness=0.50,
        personal_control=0.45,
    ),

    ArchetypeID.MOTIVATED_YOUNG_ADULT: PatientArchetype(
        name="motivated_young_adult",
        archetype_id=ArchetypeID.MOTIVATED_YOUNG_ADULT,
        # Younger, educated cohort. Connected to online health communities.
        # Open to updating beliefs from peer network.
        stubbornness=0.40,
        # Lowest dropout hazard: manageable life circumstances, high motivation.
        dropout_hazard_multiplier=0.70,
        # MEMS upper end.
        baseline_adherence=0.85,
        # Informed: can contextualise AEs. Less likely to over-react.
        ae_sensitivity=0.30,
        # High literacy, active self-tracking (health apps, wearables).
        ae_reporting_fraction=0.80,
        # Young adults manage scheduling well; digital reminders adopted.
        visit_compliance_base=0.91,
        default_proportion=0.20,
        conscientiousness=0.75,
        personal_control=0.72,
    ),
}

# Confirm proportions sum to 1 (enforced at import time, not at runtime).
_prop_sum = sum(a.default_proportion for a in ARCHETYPES.values())
assert abs(_prop_sum - 1.0) < 1e-6, f"Archetype proportions sum to {_prop_sum}, expected 1.0"


# ─────────────────────────────────────────────────────────────────────────────
# INSTITUTIONAL ACTORS
# ─────────────────────────────────────────────────────────────────────────────

class InstitutionType(IntEnum):
    PHARMA_SPONSOR   = 0
    CRO              = 1
    CLINICAL_SITE    = 2
    REGULATOR        = 3
    PATIENT_ADVOCACY = 4


@dataclasses.dataclass(frozen=True)
class InstitutionalActor:
    """Behavioural profile for one class of institutional actor."""
    name: str
    institution_type: InstitutionType

    # Belief stubbornness (institutional isomorphism).
    # DiMaggio & Powell (1983): coercive, mimetic, normative pressures create
    # institutional convergence. Regulators are most stubborn (mandate-driven);
    # sites are most flexible (revenue-dependent on sponsor relationships).
    stubbornness: float

    # Probability per round that this actor initiates a protocol amendment.
    # Tufts 2024: 76% of trials have ≥1 amendment; 3.3/protocol over avg
    # 3–4 year trial. ~3.3/(48 months) ≈ 0.07 per month per trial.
    amendment_initiation_rate: float

    # Probability that a site activates within 90 days of selection
    # (NCI target). Observed median at cancer centers: 167 days (AACI 2018).
    site_activation_probability: float

    # Fraction of safety signals above threshold that triggers a response
    # (regulatory review, protocol modification, CRO audit).
    safety_response_threshold: float


INSTITUTIONAL_ACTORS: dict[InstitutionType, InstitutionalActor] = {

    InstitutionType.PHARMA_SPONSOR: InstitutionalActor(
        name="pharma_sponsor",
        institution_type=InstitutionType.PHARMA_SPONSOR,
        # Moderate stubbornness: protocol investment creates anchoring bias,
        # but revenue pressure creates openness to amendments when enrollment
        # lags. Mimetic isomorphism: sponsors copy competitors' protocol designs.
        stubbornness=0.65,
        # 76% have ≥1 amendment; 3.3/protocol over ~48 months → 0.069/month.
        # Oncology higher: 90% of trials require ≥1 → raised to 0.085/month.
        amendment_initiation_rate=0.069,
        # N/A for sponsor (not a site actor); set to 1.0 as placeholder.
        site_activation_probability=1.0,
        # Sponsors respond to safety signals above Grade 3 accumulation.
        safety_response_threshold=0.65,
    ),

    InstitutionType.CRO: InstitutionalActor(
        name="cro",
        institution_type=InstitutionType.CRO,
        # CROs are highly responsive to sponsor direction (revenue dependence).
        # Low stubbornness — they adapt procedures quickly.
        stubbornness=0.40,
        # CROs do not initiate amendments independently.
        amendment_initiation_rate=0.0,
        # CRO-managed sites activate faster than sponsor-managed.
        site_activation_probability=0.72,
        safety_response_threshold=0.70,
    ),

    InstitutionType.CLINICAL_SITE: InstitutionalActor(
        name="clinical_site",
        institution_type=InstitutionType.CLINICAL_SITE,
        # Sites adapt to sponsor/CRO instructions but have local practice inertia.
        stubbornness=0.55,
        amendment_initiation_rate=0.0,
        # Observed NCI median 167 days; target 90 days. P(activate within 90d)
        # = fraction of sites meeting target → industry data suggests ~30–40%
        # at NCI-designated centers (range 78–313 days, AACI 2018).
        site_activation_probability=0.35,
        safety_response_threshold=0.75,
    ),

    InstitutionType.REGULATOR: InstitutionalActor(
        name="regulator",
        institution_type=InstitutionType.REGULATOR,
        # Regulators operate under mandate: highest stubbornness. Coercive
        # isomorphism in DiMaggio & Powell — rules do not bend to convenience.
        stubbornness=0.88,
        amendment_initiation_rate=0.0,
        site_activation_probability=1.0,
        # Regulatory action triggered by accumulation of significant safety signals.
        # FDA clinical hold: ~9% of ~1,500 INDs/year placed on hold.
        # Source: Manning et al., PMID 31678263.
        safety_response_threshold=0.80,
    ),

    InstitutionType.PATIENT_ADVOCACY: InstitutionalActor(
        name="patient_advocacy",
        institution_type=InstitutionType.PATIENT_ADVOCACY,
        # Advocacy orgs balance patient interest vs. industry relationships.
        # Moderate stubbornness: responsive to patient feedback.
        stubbornness=0.50,
        # Advocacy orgs can request protocol changes (eligibility criteria,
        # burden reduction). Effect: 53% of amendments change eligibility.
        amendment_initiation_rate=0.015,
        site_activation_probability=1.0,
        # Advocacy responds to sustained safety signal accumulation.
        safety_response_threshold=0.55,
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# POPULATION CONFIG
# ─────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class PatientPopulationConfig:
    """Configuration for generating a heterogeneous patient population.

    Therapeutic-area-specific defaults are in clincast/scenarios/.
    """
    n_patients: int
    n_sites: int

    # Initial belief about the trial prior to enrollment.
    # Beta distribution parameters. High α, β → beliefs clustered near 0.5.
    # Lower β → higher initial trust (e.g., oncology patients desperate for
    # options have high initial willingness).
    belief_prior_alpha: float = 3.0
    belief_prior_beta: float = 3.0

    # Archetype proportion vector. Length must match len(ARCHETYPES).
    # Default = equal to PatientArchetype.default_proportion values.
    archetype_proportions: np.ndarray = dataclasses.field(
        default_factory=lambda: np.array([
            ARCHETYPES[a].default_proportion for a in ArchetypeID
        ])
    )

    # Positive shift applied to all patients' health literacy draws.
    # 0.0 = general population; +0.1 = slightly educated trial population.
    health_literacy_shift: float = 0.05

    # Mean age for the trial population.
    mean_age: float = 52.0

    def __post_init__(self) -> None:
        if abs(self.archetype_proportions.sum() - 1.0) > 1e-6:
            raise ValueError("archetype_proportions must sum to 1.0")
        if len(self.archetype_proportions) != len(ArchetypeID):
            raise ValueError(
                f"archetype_proportions must have {len(ArchetypeID)} entries"
            )
