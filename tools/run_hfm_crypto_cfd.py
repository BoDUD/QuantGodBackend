#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from tools.hfm_crypto_cfd.builder import build_hfm_crypto_cfd_state, read_hfm_crypto_cfd_state
    from tools.hfm_crypto_cfd.contract_spec_export import (
        build_hfm_crypto_contract_spec_export,
        read_hfm_crypto_contract_spec_export,
    )
    from tools.hfm_crypto_cfd.execution_spec import (
        build_hfm_crypto_execution_spec_review,
        read_hfm_crypto_execution_spec_review,
    )
    from tools.hfm_crypto_cfd.evidence_kit import (
        build_hfm_crypto_evidence_kit,
        read_hfm_crypto_evidence_kit,
    )
    from tools.hfm_crypto_cfd.evidence_bootstrap import (
        build_hfm_crypto_evidence_bootstrap,
        read_hfm_crypto_evidence_bootstrap,
    )
    from tools.hfm_crypto_cfd.filled_input_validator import (
        build_hfm_crypto_filled_input_validator,
        read_hfm_crypto_filled_input_validator,
    )
    from tools.hfm_crypto_cfd.mt5_exporter_review import (
        build_hfm_crypto_mt5_exporter_review,
        read_hfm_crypto_mt5_exporter_review,
    )
    from tools.hfm_crypto_cfd.mt5_upgrade_bundle import (
        build_hfm_crypto_mt5_upgrade_bundle,
        read_hfm_crypto_mt5_upgrade_bundle,
    )
    from tools.hfm_crypto_cfd.mt5_upgrade_runner import (
        build_hfm_crypto_mt5_upgrade_runner,
        read_hfm_crypto_mt5_upgrade_runner,
    )
    from tools.hfm_crypto_cfd.mt5_exporter_deploy_plan import (
        build_hfm_crypto_mt5_exporter_deploy_plan,
        read_hfm_crypto_mt5_exporter_deploy_plan,
    )
    from tools.hfm_crypto_cfd.mt5_post_upgrade_verify import (
        build_hfm_crypto_mt5_post_upgrade_verify,
        read_hfm_crypto_mt5_post_upgrade_verify,
    )
    from tools.hfm_crypto_cfd.post_upgrade_controller import (
        build_hfm_crypto_post_upgrade_controller,
        read_hfm_crypto_post_upgrade_controller,
    )
    from tools.hfm_crypto_cfd.simulation_profile import (
        build_hfm_crypto_simulation_profile_review,
        read_hfm_crypto_simulation_profile_review,
    )
    from tools.hfm_crypto_cfd.rates_export import (
        build_hfm_crypto_rates_export_review,
        read_hfm_crypto_rates_export_review,
    )
    from tools.hfm_crypto_cfd.standalone_exporter_bundle import (
        build_hfm_crypto_standalone_exporter_bundle,
        read_hfm_crypto_standalone_exporter_bundle,
    )
    from tools.hfm_crypto_cfd.standalone_exporter_runner import (
        build_hfm_crypto_standalone_exporter_runner,
        read_hfm_crypto_standalone_exporter_runner,
    )
    from tools.hfm_crypto_cfd.schema import (
        contract_spec_export_path,
        filled_contract_spec_path,
        filled_simulation_profile_path,
    )
except ModuleNotFoundError:  # pragma: no cover
    from hfm_crypto_cfd.builder import build_hfm_crypto_cfd_state, read_hfm_crypto_cfd_state
    from hfm_crypto_cfd.contract_spec_export import (
        build_hfm_crypto_contract_spec_export,
        read_hfm_crypto_contract_spec_export,
    )
    from hfm_crypto_cfd.execution_spec import (
        build_hfm_crypto_execution_spec_review,
        read_hfm_crypto_execution_spec_review,
    )
    from hfm_crypto_cfd.evidence_kit import (
        build_hfm_crypto_evidence_kit,
        read_hfm_crypto_evidence_kit,
    )
    from hfm_crypto_cfd.evidence_bootstrap import (
        build_hfm_crypto_evidence_bootstrap,
        read_hfm_crypto_evidence_bootstrap,
    )
    from hfm_crypto_cfd.filled_input_validator import (
        build_hfm_crypto_filled_input_validator,
        read_hfm_crypto_filled_input_validator,
    )
    from hfm_crypto_cfd.mt5_exporter_review import (
        build_hfm_crypto_mt5_exporter_review,
        read_hfm_crypto_mt5_exporter_review,
    )
    from hfm_crypto_cfd.mt5_upgrade_bundle import (
        build_hfm_crypto_mt5_upgrade_bundle,
        read_hfm_crypto_mt5_upgrade_bundle,
    )
    from hfm_crypto_cfd.mt5_upgrade_runner import (
        build_hfm_crypto_mt5_upgrade_runner,
        read_hfm_crypto_mt5_upgrade_runner,
    )
    from hfm_crypto_cfd.mt5_exporter_deploy_plan import (
        build_hfm_crypto_mt5_exporter_deploy_plan,
        read_hfm_crypto_mt5_exporter_deploy_plan,
    )
    from hfm_crypto_cfd.mt5_post_upgrade_verify import (
        build_hfm_crypto_mt5_post_upgrade_verify,
        read_hfm_crypto_mt5_post_upgrade_verify,
    )
    from hfm_crypto_cfd.post_upgrade_controller import (
        build_hfm_crypto_post_upgrade_controller,
        read_hfm_crypto_post_upgrade_controller,
    )
    from hfm_crypto_cfd.simulation_profile import (
        build_hfm_crypto_simulation_profile_review,
        read_hfm_crypto_simulation_profile_review,
    )
    from hfm_crypto_cfd.rates_export import (
        build_hfm_crypto_rates_export_review,
        read_hfm_crypto_rates_export_review,
    )
    from hfm_crypto_cfd.standalone_exporter_bundle import (
        build_hfm_crypto_standalone_exporter_bundle,
        read_hfm_crypto_standalone_exporter_bundle,
    )
    from hfm_crypto_cfd.standalone_exporter_runner import (
        build_hfm_crypto_standalone_exporter_runner,
        read_hfm_crypto_standalone_exporter_runner,
    )
    from hfm_crypto_cfd.schema import (
        contract_spec_export_path,
        filled_contract_spec_path,
        filled_simulation_profile_path,
    )


def emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="QuantGod HFM Crypto CFD shadow lane")
    parser.add_argument("--runtime-dir", default=os.environ.get("QG_RUNTIME_DIR", str(root / "runtime")))
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--write", action="store_true")
    build.add_argument("--moss-backtest-json", default=os.environ.get("QG_MOSS_BACKTEST_JSON", ""))
    build.add_argument("--simulation-profile-json", default=os.environ.get("QG_HFM_CRYPTO_SIMULATION_PROFILE_JSON", ""))
    build.add_argument("--contract-spec-json", default=os.environ.get("QG_HFM_CRYPTO_CONTRACT_SPEC_JSON", ""))
    build.add_argument("--extra-bases-root", action="append", default=[])
    spec = sub.add_parser("execution-spec")
    spec.add_argument("--write", action="store_true")
    spec.add_argument("--contract-spec-json", default=os.environ.get("QG_HFM_CRYPTO_CONTRACT_SPEC_JSON", ""))
    export = sub.add_parser("contract-spec-export")
    export.add_argument("--write", action="store_true")
    export.add_argument("--symbol-registry-json", default=os.environ.get("QG_HFM_CRYPTO_SYMBOL_REGISTRY_JSON", ""))
    export.add_argument("--live-mt5", action="store_true")
    export.add_argument("--terminal-path", default=os.environ.get("QG_MT5_TERMINAL_PATH", ""))
    sim = sub.add_parser("simulation-profile")
    sim.add_argument("--write", action="store_true")
    sim.add_argument("--simulation-profile-json", default=os.environ.get("QG_HFM_CRYPTO_SIMULATION_PROFILE_JSON", os.environ.get("QG_MOSS_BACKTEST_JSON", "")))
    rates = sub.add_parser("rates-export")
    rates.add_argument("--write", action="store_true")
    rates.add_argument("--write-profile", action="store_true")
    rates.add_argument("--rates-manifest-json", default=os.environ.get("QG_HFM_CRYPTO_RATES_MANIFEST_JSON", ""))
    kit = sub.add_parser("evidence-kit")
    kit.add_argument("--write", action="store_true")
    bootstrap = sub.add_parser("evidence-bootstrap")
    bootstrap.add_argument("--write", action="store_true")
    bootstrap.add_argument("--overwrite-drafts", action="store_true")
    exporter_review = sub.add_parser("mt5-exporter-review")
    exporter_review.add_argument("--write", action="store_true")
    upgrade_bundle = sub.add_parser("mt5-upgrade-bundle")
    upgrade_bundle.add_argument("--write", action="store_true")
    upgrade_runner = sub.add_parser("mt5-upgrade-runner")
    upgrade_runner.add_argument("--write", action="store_true")
    upgrade_runner.add_argument("--install", action="store_true")
    upgrade_runner.add_argument("--compile", action="store_true")
    upgrade_runner.add_argument("--restart-terminal", action="store_true")
    upgrade_runner.add_argument("--screen-name", default=os.environ.get("QG_MT5_SECONDARY_SCREEN", "quantgod-mt5-live16"))
    upgrade_runner.add_argument("--startup-config", default=os.environ.get("QG_MT5_SECONDARY_STARTUP_CONFIG", ""))
    deploy_plan = sub.add_parser("mt5-exporter-deploy-plan")
    deploy_plan.add_argument("--write", action="store_true")
    standalone_exporter = sub.add_parser("standalone-exporter-bundle")
    standalone_exporter.add_argument("--write", action="store_true")
    standalone_runner = sub.add_parser("standalone-exporter-runner")
    standalone_runner.add_argument("--write", action="store_true")
    standalone_runner.add_argument("--install", action="store_true")
    standalone_runner.add_argument("--compile", action="store_true")
    standalone_runner.add_argument("--run-terminal", action="store_true")
    post_upgrade = sub.add_parser("mt5-post-upgrade-verify")
    post_upgrade.add_argument("--write", action="store_true")
    post_upgrade_controller = sub.add_parser("post-upgrade-controller")
    post_upgrade_controller.add_argument("--write", action="store_true")
    filled_input_validator = sub.add_parser("filled-input-validator")
    filled_input_validator.add_argument("--write", action="store_true")
    sub.add_parser("status")
    sub.add_parser("contract-spec-export-status")
    sub.add_parser("execution-spec-status")
    sub.add_parser("simulation-profile-status")
    sub.add_parser("rates-export-status")
    sub.add_parser("evidence-kit-status")
    sub.add_parser("evidence-bootstrap-status")
    sub.add_parser("mt5-exporter-review-status")
    sub.add_parser("mt5-upgrade-bundle-status")
    sub.add_parser("mt5-upgrade-runner-status")
    sub.add_parser("mt5-exporter-deploy-plan-status")
    sub.add_parser("standalone-exporter-bundle-status")
    sub.add_parser("standalone-exporter-runner-status")
    sub.add_parser("mt5-post-upgrade-verify-status")
    sub.add_parser("post-upgrade-controller-status")
    sub.add_parser("filled-input-validator-status")
    args = parser.parse_args(argv)
    runtime_dir = Path(args.runtime_dir)
    if args.command == "build":
        return emit(build_hfm_crypto_cfd_state(
            runtime_dir,
            moss_backtest_json=args.moss_backtest_json,
            simulation_profile_json=args.simulation_profile_json,
            contract_spec_json=args.contract_spec_json,
            extra_bases_roots=args.extra_bases_root,
            write=args.write,
        ))
    if args.command == "execution-spec":
        contract_spec_json = args.contract_spec_json
        if not contract_spec_json:
            filled_path = filled_contract_spec_path(runtime_dir)
            if filled_path.exists():
                contract_spec_json = str(filled_path)
        if not contract_spec_json:
            export_path = contract_spec_export_path(runtime_dir)
            if export_path.exists():
                contract_spec_json = str(export_path)
        return emit(build_hfm_crypto_execution_spec_review(
            runtime_dir,
            contract_spec_json=contract_spec_json,
            write=args.write,
        ))
    if args.command == "contract-spec-export":
        return emit(build_hfm_crypto_contract_spec_export(
            runtime_dir,
            symbol_registry_json=args.symbol_registry_json,
            live_mt5=args.live_mt5,
            terminal_path=args.terminal_path,
            write=args.write,
        ))
    if args.command == "simulation-profile":
        simulation_profile_json = args.simulation_profile_json
        if not simulation_profile_json:
            filled_path = filled_simulation_profile_path(runtime_dir)
            if filled_path.exists():
                simulation_profile_json = str(filled_path)
        return emit(build_hfm_crypto_simulation_profile_review(
            runtime_dir,
            simulation_profile_json=simulation_profile_json,
            write=args.write,
        ))
    if args.command == "rates-export":
        return emit(build_hfm_crypto_rates_export_review(
            runtime_dir,
            rates_manifest_json=args.rates_manifest_json,
            write=args.write,
            write_profile=args.write_profile,
        ))
    if args.command == "evidence-kit":
        return emit(build_hfm_crypto_evidence_kit(runtime_dir, write=args.write))
    if args.command == "evidence-bootstrap":
        return emit(build_hfm_crypto_evidence_bootstrap(
            runtime_dir,
            write=args.write,
            overwrite_drafts=args.overwrite_drafts,
        ))
    if args.command == "mt5-exporter-review":
        return emit(build_hfm_crypto_mt5_exporter_review(runtime_dir, write=args.write))
    if args.command == "mt5-upgrade-bundle":
        return emit(build_hfm_crypto_mt5_upgrade_bundle(runtime_dir, write=args.write))
    if args.command == "mt5-upgrade-runner":
        return emit(build_hfm_crypto_mt5_upgrade_runner(
            runtime_dir,
            install=args.install,
            compile_source=args.compile,
            restart_terminal=args.restart_terminal,
            screen_name=args.screen_name,
            startup_config=args.startup_config,
            write=args.write,
        ))
    if args.command == "mt5-exporter-deploy-plan":
        return emit(build_hfm_crypto_mt5_exporter_deploy_plan(runtime_dir, write=args.write))
    if args.command == "standalone-exporter-bundle":
        return emit(build_hfm_crypto_standalone_exporter_bundle(runtime_dir, write=args.write))
    if args.command == "standalone-exporter-runner":
        return emit(build_hfm_crypto_standalone_exporter_runner(
            runtime_dir,
            install=args.install,
            compile_sources=args.compile,
            run_terminal=args.run_terminal,
            write=args.write,
        ))
    if args.command == "mt5-post-upgrade-verify":
        return emit(build_hfm_crypto_mt5_post_upgrade_verify(runtime_dir, write=args.write))
    if args.command == "post-upgrade-controller":
        return emit(build_hfm_crypto_post_upgrade_controller(runtime_dir, write=args.write))
    if args.command == "filled-input-validator":
        return emit(build_hfm_crypto_filled_input_validator(runtime_dir, write=args.write))
    if args.command == "status":
        return emit(read_hfm_crypto_cfd_state(runtime_dir))
    if args.command == "contract-spec-export-status":
        return emit(read_hfm_crypto_contract_spec_export(runtime_dir))
    if args.command == "execution-spec-status":
        return emit(read_hfm_crypto_execution_spec_review(runtime_dir))
    if args.command == "simulation-profile-status":
        return emit(read_hfm_crypto_simulation_profile_review(runtime_dir))
    if args.command == "rates-export-status":
        return emit(read_hfm_crypto_rates_export_review(runtime_dir))
    if args.command == "evidence-kit-status":
        return emit(read_hfm_crypto_evidence_kit(runtime_dir))
    if args.command == "evidence-bootstrap-status":
        return emit(read_hfm_crypto_evidence_bootstrap(runtime_dir))
    if args.command == "mt5-exporter-review-status":
        return emit(read_hfm_crypto_mt5_exporter_review(runtime_dir))
    if args.command == "mt5-upgrade-bundle-status":
        return emit(read_hfm_crypto_mt5_upgrade_bundle(runtime_dir))
    if args.command == "mt5-upgrade-runner-status":
        return emit(read_hfm_crypto_mt5_upgrade_runner(runtime_dir))
    if args.command == "mt5-exporter-deploy-plan-status":
        return emit(read_hfm_crypto_mt5_exporter_deploy_plan(runtime_dir))
    if args.command == "standalone-exporter-bundle-status":
        return emit(read_hfm_crypto_standalone_exporter_bundle(runtime_dir))
    if args.command == "standalone-exporter-runner-status":
        return emit(read_hfm_crypto_standalone_exporter_runner(runtime_dir))
    if args.command == "mt5-post-upgrade-verify-status":
        return emit(read_hfm_crypto_mt5_post_upgrade_verify(runtime_dir))
    if args.command == "post-upgrade-controller-status":
        return emit(read_hfm_crypto_post_upgrade_controller(runtime_dir))
    if args.command == "filled-input-validator-status":
        return emit(read_hfm_crypto_filled_input_validator(runtime_dir))
    return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
