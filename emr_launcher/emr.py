"""Helpers for interacting with AWS EMR.

These functions provide only minimal behavior and are primarily placeholders
for the full implementation. They demonstrate how the service might invoke the
existing configuration tooling and submit a job flow to AWS.
"""
from __future__ import annotations

import subprocess
from typing import Dict, Optional

import boto3


def _run(cmd: list[str]) -> None:
    """Run *cmd* and raise if it fails."""
    subprocess.run(cmd, check=True)


def launch_job(
    job: str,
    env: str,
    experiment: Optional[str],
    overrides: Dict[str, str],
    runtime: Dict[str, str],
    force_run: bool,
) -> None:
    """Render configs and submit an EMR job.

    Parameters mirror the JSON payload described in :mod:`emr_launcher.service`.
    """
    build_cmd = ["make", "build", f"env={env}"]
    if experiment:
        build_cmd.append(f"exp={experiment}")
    _run(build_cmd)

    # Generate runtime configs
    gen_cmd = ["make", "generate-runtime-config", f"env={env}"]
    if experiment:
        gen_cmd.append(f"exp={experiment}")
    if runtime.get("run_date"):
        gen_cmd.append(f"run_date={runtime['run_date']}")
    if force_run:
        gen_cmd.append("forceRun=true")
    _run(gen_cmd)

    # Actual EMR submission is omitted. This demonstrates how the AWS SDK
    # might be used.
    emr = boto3.client("emr")
    emr.run_job_flow(Name=job, Steps=[])  # type: ignore[arg-type]


def clone_cluster(cluster_id: str, overrides: Dict[str, str]) -> str:
    """Clone an existing EMR cluster.

    Returns the identifier of the new cluster.
    """
    emr = boto3.client("emr")
    # Fetch existing configuration. The real implementation would examine
    # cluster state, steps, and bootstrap actions.
    cluster = emr.describe_cluster(ClusterId=cluster_id)["Cluster"]

    # Apply overrides and launch a new cluster. This is highly simplified and
    # intended only as documentation for the expected behavior.
    response = emr.run_job_flow(Name=cluster["Name"], Steps=[])
    return response.get("JobFlowId", "")
