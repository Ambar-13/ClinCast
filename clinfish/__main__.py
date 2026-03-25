"""ClinFish command-line interface.

Usage:
    clinfish simulate --ta cns --patients 400 --sites 20 --rounds 18
    clinfish simulate --ta oncology --patients 500 --sites 25 --rounds 24 --seed 42
    clinfish calibrate --ta cns --lhs 300
    clinfish list-scenarios
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from clinfish.core.engine import SimConfig, run_simulation
from clinfish.scenarios import SCENARIO_REGISTRY, get_scenario


def cmd_simulate(args: argparse.Namespace) -> None:
    if args.preset:
        config = get_scenario(args.ta)
        # Override individual fields if explicitly provided.
        if args.patients is not None:
            config.n_patients = args.patients
            config.pop_config.n_patients = args.patients
        if args.sites is not None:
            config.n_sites = args.sites
            config.pop_config.n_sites = args.sites
        if args.rounds is not None:
            config.n_rounds = args.rounds
        if args.seed is not None:
            config.seed = args.seed
    else:
        if args.patients is None or args.sites is None or args.rounds is None:
            print("error: --patients, --sites, and --rounds are required without --preset", file=sys.stderr)
            sys.exit(1)
        config = SimConfig(
            therapeutic_area=args.ta,
            n_patients=args.patients,
            n_sites=args.sites,
            n_rounds=args.rounds,
            seed=args.seed or 0,
            monitoring_active=not args.no_monitoring,
        )

    t0 = time.perf_counter()
    result = run_simulation(config)
    elapsed = time.perf_counter() - t0

    if args.json:
        print(result.to_json())
    else:
        _print_summary(result, elapsed)


def _print_summary(result, elapsed: float) -> None:
    p = result.rounds[-1] if result.rounds else None
    rounds = result.round_snapshots

    print(f"\nClinFish — {result.therapeutic_area.upper()} Trial Simulation")
    print("─" * 60)
    print(f"  Patients:          {result.n_patients}")
    print(f"  Sites:             {result.n_sites}")
    print(f"  Duration:          {result.n_rounds} months")
    print(f"  Runtime:           {elapsed*1000:.1f}ms")
    print()

    final = rounds[-1] if rounds else None
    last_active = next((r for r in reversed(rounds) if r.n_enrolled > 0), final)

    if final:
        print("  Outcomes:")
        print(f"    Enrolled:        {final.n_enrolled}")
        print(f"    Dropout:         {final.n_dropout}  ({100*final.n_dropout/result.n_patients:.1f}%)")
        print(f"    Completed:       {final.n_completed}  ({100*final.n_completed/result.n_patients:.1f}%)")
        print()
    if last_active:
        print("  Behavioral indices (last active round):")
        print(f"    Adherence:       {last_active.mean_adherence:.3f}")
        print(f"    Mean belief:     {last_active.mean_belief:.3f}")
        print(f"    Visit compliance:{last_active.visit_compliance_rate:.3f}")
        print(f"    Safety signal:   {last_active.safety_signal:.3f}")
        print(f"    Data quality:    {last_active.data_quality:.3f}")
        print(f"    Site burden:     {last_active.site_burden:.3f}")
    print()

    assumed = result.assumed_count()
    print(f"  Epistemic tags:  {assumed} ASSUMED output(s)")
    print()

    # Warn on triggered safety signals.
    max_safety = max((r.safety_signal for r in rounds), default=0.0)
    if max_safety >= 0.80:
        print(f"  ⚠ Regulatory action threshold reached (peak signal: {max_safety:.2f})")
    if max_safety >= 1.0:
        print("  ⚠ Clinical hold threshold reached")


def cmd_calibrate(args: argparse.Namespace) -> None:
    from clinfish.core.calibration.smm import run_smm, latin_hypercube_sample
    from clinfish.core.calibration.moments import get_moments
    from clinfish.core.engine import SimConfig, run_simulation

    target = get_moments(args.ta)
    print(f"Calibrating {args.ta} model against {len(target.values)} moments...")
    print(f"  LHS samples: {args.lhs}")

    # Parameter bounds: [protocol_burden, protocol_visit_burden, seed]
    bounds = [(0.2, 0.9), (0.2, 0.9)]

    def simulator(params):
        config = SimConfig(
            therapeutic_area=args.ta,
            n_patients=300,
            n_sites=15,
            n_rounds=24,
            protocol_burden=params[0],
            protocol_visit_burden=params[1],
            seed=42,
        )
        return run_simulation(config)

    def moment_extractor(trial_outputs):
        rounds = trial_outputs.round_snapshots
        n = trial_outputs.n_patients
        if not rounds:
            return [0.0] * len(target.values)

        r6  = next((r for r in rounds if r.time_months >= 6),  rounds[-1])
        r18 = next((r for r in rounds if r.time_months >= 18), rounds[-1])
        last_active = next((r for r in reversed(rounds) if r.n_enrolled > 0), rounds[-1])

        dropout_6  = r6.n_dropout  / max(n, 1)
        dropout_18 = r18.n_dropout / max(n, 1)
        adherence  = last_active.mean_adherence
        # Fill remaining moments with available proxies.
        visit_c    = last_active.visit_compliance_rate
        dq         = last_active.data_quality
        ae_rep     = last_active.ae_reporting_mean

        return [dropout_6, dropout_18, adherence, visit_c, dq, ae_rep]

    result = run_smm(
        simulator=simulator,
        moment_extractor=moment_extractor,
        target=target,
        bounds=bounds,
        n_lhs=args.lhs,
    )
    print(f"\nCalibration result:")
    print(f"  Best parameters:  {result['best_params']}")
    print(f"  SMM objective:    {result['best_distance']:.4f}")
    print(f"  Runtime:          {result['elapsed_seconds']:.1f}s")


def cmd_list_scenarios(_args: argparse.Namespace) -> None:
    print("Available scenarios:")
    for name in SCENARIO_REGISTRY:
        config = get_scenario(name)
        print(f"  {name:<18} {config.n_patients} patients, {config.n_sites} sites, {config.n_rounds} months")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="clinfish",
        description="ClinFish: clinical trial behavioral simulation engine",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # simulate subcommand
    sim_p = sub.add_parser("simulate", help="Run a trial simulation")
    sim_p.add_argument("--ta", required=True, metavar="AREA",
                       help="Therapeutic area (cns, oncology, cardiovascular, metabolic, alzheimers, rare)")
    sim_p.add_argument("--patients", type=int, default=None)
    sim_p.add_argument("--sites",    type=int, default=None)
    sim_p.add_argument("--rounds",   type=int, default=None)
    sim_p.add_argument("--seed",     type=int, default=None)
    sim_p.add_argument("--preset",   action="store_true", default=True,
                       help="Use TA-specific preset defaults (default: True)")
    sim_p.add_argument("--no-monitoring", action="store_true",
                       help="Disable RBM/SDV monitoring")
    sim_p.add_argument("--json",     action="store_true",
                       help="Output full JSON result")
    sim_p.set_defaults(func=cmd_simulate)

    # calibrate subcommand
    cal_p = sub.add_parser("calibrate", help="Run SMM calibration")
    cal_p.add_argument("--ta",  required=True, metavar="AREA")
    cal_p.add_argument("--lhs", type=int, default=300, help="LHS sample count")
    cal_p.set_defaults(func=cmd_calibrate)

    # list-scenarios subcommand
    ls_p = sub.add_parser("list-scenarios", help="List available TA presets")
    ls_p.set_defaults(func=cmd_list_scenarios)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
