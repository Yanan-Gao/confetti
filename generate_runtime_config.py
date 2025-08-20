import os
import sys
import subprocess
import importlib
import base64
import hashlib
import datetime
from typing import Dict, Optional


def log_info(message: str) -> None:
    """Log an informational message."""
    print(f"[INFO] {message}")


# Ensure the script is executed with Python 3
if sys.version_info.major < 3:
    print("This script requires Python 3.", file=sys.stderr)
    sys.exit(1)


def ensure_dependency(pkg: str, import_name: Optional[str] = None) -> None:
    """Install the given package if the import fails."""
    import_name = import_name or pkg
    try:
        importlib.import_module(import_name)
    except ImportError:
        log_info(f"Installing missing dependency {pkg}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])


ensure_dependency("PyYAML", "yaml")
ensure_dependency("Jinja2", "jinja2")
ensure_dependency("boto3")

import yaml
from jinja2 import Environment, BaseLoader, StrictUndefined
import boto3


class AwsCloudStorage:
    """Minimal wrapper around S3 operations."""

    def __init__(self) -> None:
        self.s3 = boto3.client("s3")

    @staticmethod
    def _parse_uri(uri: str):
        if not uri.startswith("s3://"):
            raise ValueError(f"Invalid S3 URI: {uri}")
        bucket, _, key = uri[5:].partition("/")
        return bucket, key

    def read_key(self, uri: str) -> str:
        bucket, key = self._parse_uri(uri)
        obj = self.s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read().decode("utf-8")

    def upload_string(self, uri: str, data: str) -> None:
        bucket, key = self._parse_uri(uri)
        self.s3.put_object(Bucket=bucket, Key=key, Body=data.encode("utf-8"))


def _inject_audience_jar_path(rendered: str, aws: AwsCloudStorage) -> str:
    """Compute audienceJarPath from branch and version and remove those keys."""
    try:
        data = yaml.safe_load(rendered)
    except Exception as exc:  # pragma: no cover - malformed YAML
        raise ValueError(f"Failed to parse Confetti YAML: {exc}") from exc

    if not isinstance(data, dict):  # pragma: no cover - unexpected structure
        raise ValueError("Confetti YAML must be a mapping")

    if "audienceJarBranch" not in data:
        raise ValueError("audienceJarBranch is required in Confetti config")
    if "audienceJarVersion" not in data:
        raise ValueError("audienceJarVersion is required in Confetti config")

    branch = str(data.pop("audienceJarBranch"))
    version = str(data.pop("audienceJarVersion"))

    version_value = version
    if version.lower() == "latest":
        if branch == "master":
            current_key = (
                "s3://thetradedesk-mlplatform-us-east-1/libs/audience/jars/prod/_CURRENT"
            )
        else:
            current_key = (
                f"s3://thetradedesk-mlplatform-us-east-1/libs/audience/jars/mergerequests/{branch}/_CURRENT"
            )
        lines = aws.read_key(current_key).splitlines()
        if not lines or not lines[0].strip():
            raise ValueError(f"No version found in {current_key}")
        version_value = lines[0].strip()

    if branch == "master":
        jar_path = (
            "s3://thetradedesk-mlplatform-us-east-1/libs/audience/jars/snapshots/master/"
            f"{version_value}/audience.jar"
        )
    else:
        jar_path = (
            "s3://thetradedesk-mlplatform-us-east-1/libs/audience/jars/mergerequests/"
            f"{branch}/{version_value}/audience.jar"
        )

    data["audienceJarPath"] = jar_path
    return yaml.safe_dump(data, sort_keys=True)


def _sha256_b64(data: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data.encode("utf-8")).digest()).decode()


CONFIG_ROOT = "configs"
RUNTIME_ROOT = "runtime-configs"


def parse_cli_args(argv):
    params: Dict[str, str] = {}
    for arg in argv:
        if "=" in arg:
            k, v = arg.split("=", 1)
            params[k] = v
    env = params.get("env")
    if not env:
        print("env parameter is required", file=sys.stderr)
        sys.exit(1)
    exp = params.get("exp")
    group = params.get("group", "audience")
    job = params.get("job")

    # Validate env/exp relationship
    if env == "prod":
        if exp is not None:
            print("exp parameter must not be provided when env=prod", file=sys.stderr)
            sys.exit(1)
    else:
        if not exp:
            print("exp parameter is required for non-prod environments", file=sys.stderr)
            sys.exit(1)

    runtime_args = {
        k: yaml.safe_load(v)
        for k, v in params.items()
        if k not in {"env", "exp", "job", "group"}
    }
    if "run_date" in runtime_args:
        run_date_raw = str(runtime_args["run_date"])
        runtime_args["run_date"] = datetime.datetime.strptime(run_date_raw, "%Y%m%d").date()

    return env, exp, group, job, runtime_args


def render_job(env: str, exp: Optional[str], group: str, job: str, runtime_args: Dict[str, object], aws: AwsCloudStorage) -> None:
    config_env_path = f"{env}/{exp}" if exp else env
    job_dir = os.path.join(CONFIG_ROOT, config_env_path, group, job)
    if not os.path.isdir(job_dir):
        raise ValueError(f"Job directory not found: {job_dir}")

    jenv = Environment(loader=BaseLoader, undefined=StrictUndefined)

    rendered_files: Dict[str, str] = {}
    for filename in os.listdir(job_dir):
        if not filename.endswith(".yml"):
            continue
        path = os.path.join(job_dir, filename)
        with open(path) as f:
            template = jenv.from_string(f.read())
        rendered = template.render(**runtime_args)
        if filename == "identity_config.yml":
            rendered = _inject_audience_jar_path(rendered, aws)
        rendered_files[filename] = rendered

    if "identity_config.yml" not in rendered_files:
        raise ValueError("identity_config.yml is required for hashing")

    hash_input = "".join(rendered_files[f] for f in sorted(rendered_files))
    hash_id = _sha256_b64(hash_input)

    out_env_path = env
    out_dir = os.path.join(RUNTIME_ROOT, out_env_path, group, job, hash_id)
    os.makedirs(out_dir, exist_ok=True)
    s3_prefix = (
        "s3://thetradedesk-mlplatform-us-east-1/configdata/confetti/"
        f"{RUNTIME_ROOT}/{out_env_path}/{group}/{job}/{hash_id}/"
    )

    for filename, content in rendered_files.items():
        out_path = os.path.join(out_dir, filename)
        with open(out_path, "w") as f:
            f.write(content)

    failed_uploads = []
    for filename, content in rendered_files.items():
        try:
            aws.upload_string(s3_prefix + filename, content)
        except Exception as exc:  # pragma: no cover - network errors
            log_info(f"Failed to upload {filename} to S3: {exc}")
            failed_uploads.append(filename)

    if failed_uploads:
        failed_list = ", ".join(failed_uploads)
        raise RuntimeError(f"S3 upload failed for files: {failed_list}")

    log_info(f"Generated runtime configs for {env}/{group}/{job} -> {hash_id}")


def main(argv):
    env, exp, group, job, runtime_args = parse_cli_args(argv)
    aws = AwsCloudStorage()
    env_path = f"{env}/{exp}" if exp else env

    base_dir = os.path.join(CONFIG_ROOT, env_path, group)
    if not os.path.isdir(base_dir):
        raise ValueError(f"No configs found under {base_dir}")

    jobs = [job] if job else [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
    for j in jobs:
        render_job(env, exp, group, j, runtime_args, aws)


if __name__ == "__main__":
    main(sys.argv[1:])
