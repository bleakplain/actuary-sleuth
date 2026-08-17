#!/usr/bin/env python3
"""运行冻结的法规触发与动态条款在线小样；默认只做离线预检。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlparse

from lib.compliance.trigger_online_measurement import (
    APPROVED_ONLINE_PLAN_SHA256,
    OnlineProbePlan,
    PreparedOnlineProbe,
    RatePairProbePlan,
    RatePairStage,
    load_online_probe_plan,
    load_rate_pair_probe_plan,
    prepare_online_probe,
    select_rate_pair_stage,
)
from lib.compliance.trigger_online_runner import (
    RatePairRunContext,
    run_online_probe,
    validate_rate_dynamic_prerequisite,
)
from lib.config import get_audit_llm_config, get_kb_version_dir
from lib.llm.call_budget import CallBudgetController, CallBudgetLimits
from lib.llm.zhipu import ZhipuClient


_WORKTREE_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PLAN = (
    _WORKTREE_ROOT
    / ".Codex"
    / "specs"
    / "037-regulation-trigger-facts"
    / "trigger-online-plan-v2.json"
)
_DEFAULT_MANIFEST = (
    Path(__file__).resolve().parent
    / "tests"
    / "fixtures"
    / "compliance_audit"
    / "v1"
    / "manifest.json"
)
_WATCHDOG_CHILD_ENV = "ACTUARY_ONLINE_WATCHDOG_CHILD"
_WATCHDOG_NONCE_ENV = "ACTUARY_ONLINE_WATCHDOG_NONCE"
_WATCHDOG_PLAN_SHA_ENV = "ACTUARY_ONLINE_WATCHDOG_PLAN_SHA"
_WATCHDOG_OVERLAY_SHA_ENV = "ACTUARY_ONLINE_WATCHDOG_OVERLAY_SHA"
_WATCHDOG_STAGE_ENV = "ACTUARY_ONLINE_WATCHDOG_STAGE"
_ONLINE_MAX_SECONDS = 285.0
_ONLINE_OUTER_WATCHDOG_SECONDS = 300
_ONLINE_MAX_TOTAL_TOKENS = 250_000
_ONLINE_MAX_PHYSICAL_CALLS = 10


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    kb_dir = Path(get_kb_version_dir())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=_DEFAULT_PLAN)
    parser.add_argument(
        "--pair-plan",
        type=Path,
        help="显式指定已批准的阶段overlay；在线模式不提供默认值。",
    )
    parser.add_argument(
        "--stage",
        choices=("rate_dynamic_c", "rate_full_a"),
        help="仅运行冻结费率可调pair中的一个独立阶段。",
    )
    parser.add_argument(
        "--prerequisite-json",
        type=Path,
        help="rate_full_a阶段必需的已完成rate_dynamic_c报告。",
    )
    parser.add_argument(
        "--single-unit",
        action="store_true",
        help="显式选择已批准的real-001费率调整第2条动态C单条overlay。",
    )
    parser.add_argument(
        "--obligation-dual",
        action="store_true",
        help="显式选择已批准的费率调整第2、3条逐项义务动态C overlay。",
    )
    parser.add_argument(
        "--obligation-single",
        action="store_true",
        help="显式选择已批准的费率调整第2条逐项义务动态C overlay。",
    )
    parser.add_argument("--manifest", type=Path, default=_DEFAULT_MANIFEST)
    parser.add_argument("--products-dir", type=Path, default=kb_dir.parent / "products")
    parser.add_argument("--kb-dir", type=Path, default=kb_dir)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument(
        "--online",
        action="store_true",
        help="显式允许向冻结计划中的智谱模型发送已授权产品内容。",
    )
    parser.add_argument("--online-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--watchdog-nonce", default="", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def _is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _validate_output_path(output_path: Path, products_dir: Path, kb_dir: Path) -> Path:
    resolved = output_path.expanduser().resolve()
    if resolved.suffix.lower() != ".json":
        raise ValueError("输出文件必须使用 .json 后缀")
    if _is_within(resolved, products_dir.expanduser().resolve()):
        raise ValueError("输出文件不得写入产品条款目录")
    if _is_within(resolved, kb_dir.expanduser().resolve()):
        raise ValueError("输出文件不得写入知识库目录")
    return resolved


def _load_prerequisite_report(
    path: Path,
    output_path: Path,
) -> tuple[Mapping[str, object], str, bytes]:
    resolved = path.expanduser().resolve()
    if resolved == output_path:
        raise ValueError("A阶段输出不得覆盖C阶段前置报告")
    content = resolved.read_bytes()
    try:
        raw = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("C阶段前置报告不是有效JSON") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("C阶段前置报告必须是JSON对象")
    return raw, hashlib.sha256(content).hexdigest(), content


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _dry_run_payload(
    prepared: PreparedOnlineProbe,
    pair_plan: RatePairProbePlan | None = None,
    stage: RatePairStage | None = None,
) -> Mapping[str, object]:
    payload: dict[str, object] = {
        "schema_version": "2.0.0",
        "measurement_kind": "online_probe_preflight",
        "llm_called": False,
        "external_content_sent": False,
        "plan": dict(prepared.summary()),
    }
    if pair_plan is not None and stage is not None:
        limits = pair_plan.pair_theoretical_limits
        payload["pair"] = {
            "pair_plan_sha256": pair_plan.sha256,
            "evidence_protocol_version": pair_plan.evidence_protocol_version,
            "stage": stage,
            "selected_group_id": pair_plan.group_id_for(stage),
            "required_unit_ids": list(pair_plan.required_unit_ids),
            "budget_scope": pair_plan.budget_scope,
            "pair_theoretical_limits": {
                "max_seconds": limits.max_seconds,
                "outer_watchdog_seconds": limits.outer_watchdog_seconds,
                "max_total_tokens": limits.max_total_tokens,
                "max_physical_calls": limits.max_physical_calls,
            },
        }
    return payload


def _watchdog_command(args: argparse.Namespace, nonce: str) -> list[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--plan",
        str(args.plan.resolve()),
        "--manifest",
        str(args.manifest.resolve()),
        "--products-dir",
        str(args.products_dir.resolve()),
        "--kb-dir",
        str(args.kb_dir.resolve()),
        "--output-json",
        str(args.output_json.resolve()),
        "--online",
        "--online-child",
        "--watchdog-nonce",
        nonce,
    ]
    stage = getattr(args, "stage", None)
    pair_plan = getattr(args, "pair_plan", None)
    prerequisite = getattr(args, "prerequisite_json", None)
    if stage:
        command.extend(("--stage", str(stage)))
    if pair_plan is not None:
        command.extend(("--pair-plan", str(Path(pair_plan).resolve())))
    if prerequisite is not None:
        command.extend((
            "--prerequisite-json",
            str(Path(prerequisite).resolve()),
        ))
    if getattr(args, "single_unit", False):
        command.append("--single-unit")
    if getattr(args, "obligation_dual", False):
        command.append("--obligation-dual")
    if getattr(args, "obligation_single", False):
        command.append("--obligation-single")
    return command


def _validate_online_plan(plan: OnlineProbePlan) -> None:
    if plan.sha256 != APPROVED_ONLINE_PLAN_SHA256:
        raise ValueError("在线模式只允许使用已审核并获授权的冻结计划")
    if (
        plan.provider != "zhipu"
        or plan.model != "glm-4-flash-250414"
        or plan.limits.max_seconds != _ONLINE_MAX_SECONDS
        or plan.limits.outer_watchdog_seconds != _ONLINE_OUTER_WATCHDOG_SECONDS
        or plan.limits.max_total_tokens != _ONLINE_MAX_TOTAL_TOKENS
        or plan.limits.max_physical_calls != _ONLINE_MAX_PHYSICAL_CALLS
    ):
        raise ValueError("在线计划的模型或硬预算已偏离获授权版本")


def _validate_zhipu_endpoint(base_url: str) -> None:
    endpoint = urlparse(base_url)
    if endpoint.scheme != "https" or endpoint.hostname != "open.bigmodel.cn":
        raise ValueError("在线模式只能向智谱官方HTTPS端点发送已授权内容")


def _terminate_on_alarm(_signum: int, _frame: object) -> None:
    os._exit(124)


def _mark_watchdog_timeout(
    output_path: Path,
    plan_sha256: str,
    overlay_sha256: str,
    stage: str,
    model: str,
) -> None:
    try:
        raw = json.loads(output_path.read_text(encoding="utf-8"))
        payload = dict(raw) if isinstance(raw, Mapping) else {}
    except (OSError, ValueError):
        payload = {}
    payload.update({
        "schema_version": payload.get("schema_version", "2.0.0"),
        "measurement_kind": payload.get(
            "measurement_kind",
            "online_full_vs_trigger_dynamic_probe",
        ),
        "status": "incomplete",
        "stopped_reason": "outer_watchdog_exceeded",
        "external_scope_expanded": False,
    })
    if "plan" not in payload:
        payload["plan"] = {"plan_sha256": plan_sha256, "model": model}
    if "pair" not in payload:
        payload["pair"] = {
            "pair_plan_sha256": overlay_sha256,
            "stage": stage,
        }
    _write_json(output_path, payload)


def _run_with_watchdog(
    args: argparse.Namespace,
    output_path: Path,
    *,
    timeout_seconds: float,
    plan_sha256: str,
    overlay_sha256: str,
    stage: str,
    model: str,
) -> int:
    _write_json(output_path, {
        "schema_version": "2.0.0",
        "measurement_kind": "online_full_vs_trigger_dynamic_probe",
        "status": "starting",
        "stopped_reason": "",
        "external_scope_expanded": False,
        "plan": {"plan_sha256": plan_sha256, "model": model},
        "pair": {
            "pair_plan_sha256": overlay_sha256,
            "stage": stage,
        },
    })
    nonce = secrets.token_urlsafe(24)
    environment = dict(os.environ)
    environment[_WATCHDOG_CHILD_ENV] = "1"
    environment[_WATCHDOG_NONCE_ENV] = nonce
    environment[_WATCHDOG_PLAN_SHA_ENV] = plan_sha256
    environment[_WATCHDOG_OVERLAY_SHA_ENV] = overlay_sha256
    environment[_WATCHDOG_STAGE_ENV] = stage
    process = subprocess.Popen(_watchdog_command(args, nonce), env=environment)
    try:
        exit_code = process.wait(timeout=min(
            timeout_seconds,
            float(_ONLINE_OUTER_WATCHDOG_SECONDS),
        ))
        if exit_code != 0:
            _mark_abnormal_child_exit(
                output_path,
                plan_sha256,
                overlay_sha256,
                stage,
                model,
                exit_code,
            )
        return exit_code
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        _mark_watchdog_timeout(
            output_path,
            plan_sha256,
            overlay_sha256,
            stage,
            model,
        )
        return 124
    except BaseException:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise


def _mark_abnormal_child_exit(
    output_path: Path,
    plan_sha256: str,
    overlay_sha256: str,
    stage: str,
    model: str,
    exit_code: int,
) -> None:
    try:
        raw = json.loads(output_path.read_text(encoding="utf-8"))
        payload = dict(raw) if isinstance(raw, Mapping) else {}
    except (OSError, ValueError):
        payload = {}
    if payload.get("status") not in {"completed", "incomplete"}:
        payload.update({
            "schema_version": payload.get("schema_version", "2.0.0"),
            "measurement_kind": payload.get(
                "measurement_kind",
                "online_full_vs_trigger_dynamic_probe",
            ),
            "status": "incomplete",
            "stopped_reason": f"child_process_exited_{exit_code}",
            "external_scope_expanded": False,
        })
        if "plan" not in payload:
            payload["plan"] = {"plan_sha256": plan_sha256, "model": model}
        if "pair" not in payload:
            payload["pair"] = {
                "pair_plan_sha256": overlay_sha256,
                "stage": stage,
            }
        _write_json(output_path, payload)


def main(argv: Sequence[str] | None = None) -> int:
    started = time.monotonic()
    args = _parse_args(argv)
    output_path = _validate_output_path(
        args.output_json,
        args.products_dir,
        args.kb_dir,
    )
    plan = load_online_probe_plan(args.plan)
    if args.stage is not None and args.pair_plan is None:
        raise ValueError("选择在线计划阶段时必须显式指定 --pair-plan")
    pair_plan = (
        load_rate_pair_probe_plan(args.pair_plan)
        if args.stage is not None and args.pair_plan is not None else None
    )
    single_unit = bool(getattr(args, "single_unit", False))
    obligation_dual = bool(getattr(args, "obligation_dual", False))
    obligation_single = bool(getattr(args, "obligation_single", False))
    if (single_unit or obligation_dual or obligation_single) and pair_plan is None:
        raise ValueError("动态子集标志必须同时指定对应overlay和动态C阶段")
    if sum((single_unit, obligation_dual, obligation_single)) > 1:
        raise ValueError("动态子集选择标志不得同时使用")
    if (
        pair_plan is not None
        and args.stage is not None
        and args.stage not in pair_plan.allowed_stages
    ):
        raise ValueError("所选阶段不在冻结overlay允许范围内")
    if pair_plan is not None and pair_plan.single_dynamic_only != single_unit:
        raise ValueError("单条overlay必须且只能通过--single-unit显式选择")
    if pair_plan is not None and pair_plan.obligation_dual_only != obligation_dual:
        raise ValueError(
            "双法规逐项义务overlay必须且只能通过--obligation-dual显式选择"
        )
    if (
        pair_plan is not None
        and pair_plan.obligation_single_only != obligation_single
    ):
        raise ValueError(
            "单法规逐项义务overlay必须且只能通过--obligation-single显式选择"
        )
    if (
        pair_plan is not None
        and (pair_plan.single_dynamic_only or pair_plan.obligation_experiment)
        and args.prerequisite_json is not None
    ):
        raise ValueError("动态子集C不得接受任何前置报告")
    if args.online:
        _validate_online_plan(plan)
        if pair_plan is None:
            raise ValueError("两阶段在线测试必须显式指定 --stage")
        if args.stage == "rate_dynamic_c" and args.prerequisite_json is not None:
            raise ValueError("C阶段不得接受前置报告")
        if args.stage == "rate_full_a" and args.prerequisite_json is None:
            raise ValueError("A阶段必须提供已通过的C阶段前置报告")
    if args.online and not args.online_child:
        if pair_plan is None or args.stage is None:
            raise RuntimeError("在线overlay上下文未初始化")
        return _run_with_watchdog(
            args,
            output_path,
            timeout_seconds=float(_ONLINE_OUTER_WATCHDOG_SECONDS),
            plan_sha256=plan.sha256,
            overlay_sha256=pair_plan.sha256,
            stage=args.stage,
            model=plan.model,
        )
    if args.online_child:
        expected_nonce = os.environ.get(_WATCHDOG_NONCE_ENV, "")
        expected_plan_sha = os.environ.get(_WATCHDOG_PLAN_SHA_ENV, "")
        expected_overlay_sha = os.environ.get(_WATCHDOG_OVERLAY_SHA_ENV, "")
        expected_stage = os.environ.get(_WATCHDOG_STAGE_ENV, "")
        if (
            os.environ.get(_WATCHDOG_CHILD_ENV) != "1"
            or not expected_nonce
            or not secrets.compare_digest(args.watchdog_nonce, expected_nonce)
            or expected_plan_sha != plan.sha256
            or pair_plan is None
            or expected_overlay_sha != pair_plan.sha256
            or expected_stage != args.stage
        ):
            raise ValueError("online-child 只能由本次受控 watchdog 父进程启动")
        signal.signal(signal.SIGALRM, _terminate_on_alarm)
        signal.alarm(_ONLINE_OUTER_WATCHDOG_SECONDS)
    deadline = started + min(plan.limits.max_seconds, _ONLINE_MAX_SECONDS)
    prepared_all = prepare_online_probe(
        args.plan,
        args.manifest,
        args.products_dir,
        args.kb_dir,
        loaded_plan=plan,
    )
    if prepared_all.plan.sha256 != plan.sha256:
        raise RuntimeError("在线准备使用的计划与已审核计划不一致")
    stage = args.stage
    prepared = (
        select_rate_pair_stage(prepared_all, pair_plan, stage)
        if pair_plan is not None and stage is not None
        else prepared_all
    )
    if not args.online:
        _write_json(
            output_path,
            _dry_run_payload(prepared, pair_plan, stage),
        )
        return 0

    config = get_audit_llm_config()
    if config.provider != plan.provider or plan.provider != "zhipu":
        raise ValueError(
            f"在线计划要求 provider={plan.provider}，当前为 {config.provider}"
        )
    if not isinstance(config.api_key, str) or not config.api_key.strip():
        raise ValueError("未配置 LLM_AUDIT_API_KEY/ZHIPU_API_KEY，禁止在线调用")
    _validate_zhipu_endpoint(config.base_url)
    if pair_plan is None or stage is None:
        raise RuntimeError("在线pair上下文未初始化")
    if urlparse(config.base_url).hostname != pair_plan.allowed_endpoint_host:
        raise ValueError("当前LLM端点与两阶段冻结计划不一致")
    pair_context: RatePairRunContext
    if stage == "rate_full_a":
        if args.prerequisite_json is None:
            raise RuntimeError("A阶段前置报告未初始化")
        (
            prerequisite,
            prerequisite_sha256,
            prerequisite_report_bytes,
        ) = _load_prerequisite_report(
            args.prerequisite_json,
            output_path,
        )
        prepared_dynamic = select_rate_pair_stage(
            prepared_all,
            pair_plan,
            "rate_dynamic_c",
        )
        prerequisite_gate = validate_rate_dynamic_prerequisite(
            prerequisite,
            pair_plan,
            prepared_dynamic,
            config.base_url,
        )
        if not prerequisite_gate.passed:
            rejected_context = RatePairRunContext(
                pair_plan=pair_plan,
                stage=stage,
                prerequisite_report_sha256=prerequisite_sha256,
                prerequisite_gate=prerequisite_gate,
            )
            _write_json(output_path, {
                "schema_version": "2.0.0",
                "measurement_kind": "online_rate_adjustment_paired_stage",
                "status": "incomplete",
                "stopped_reason": "prerequisite_evidence_gate_failed",
                "external_scope_expanded": False,
                "llm_called": False,
                "external_content_sent": False,
                "plan": {
                    **prepared.summary(),
                    "provider_endpoint": config.base_url,
                },
                "pair": rejected_context.to_dict(None),
                "results": [],
            })
            return 2
        pair_context = RatePairRunContext(
            pair_plan=pair_plan,
            stage=stage,
            prerequisite_report_sha256=prerequisite_sha256,
            prerequisite_gate=prerequisite_gate,
            prerequisite_report_bytes=prerequisite_report_bytes,
            prerequisite_prepared_dynamic=prepared_dynamic,
        )
    else:
        pair_context = RatePairRunContext(
            pair_plan=pair_plan,
            stage=stage,
        )
    if time.monotonic() >= deadline:
        raise RuntimeError("离线准备已耗尽在线探测总时限，未发送任何模型请求")
    execution_limits = prepared.plan.limits
    budget = CallBudgetController(CallBudgetLimits(
        deadline=deadline,
        max_total_tokens=execution_limits.max_total_tokens,
        max_physical_calls=execution_limits.max_physical_calls,
    ))
    client = ZhipuClient(
        api_key=config.api_key,
        model=plan.model,
        base_url=config.base_url,
        timeout=int(config.timeout),
        call_budget=budget,
    )
    try:
        report = run_online_probe(
            prepared,
            client,
            budget,
            output_path,
            pair_context=pair_context,
        )
    finally:
        client.close()
    return 0 if report.status == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
