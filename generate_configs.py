import os
import sys
import subprocess
import importlib
from enum import Enum
import re

# Ensure the script is executed with Python 3
if sys.version_info.major < 3:
    sys.stderr.write("This script requires Python 3.\n")
    sys.exit(1)


def ensure_dependency(pkg, import_name=None):
    """Install the given package if the import fails."""
    import_name = import_name or pkg
    try:
        importlib.import_module(import_name)
    except ImportError:
        print(f"Installing missing dependency {pkg}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])


ensure_dependency("PyYAML", "yaml")
ensure_dependency("Jinja2", "jinja2")

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined, exceptions


class TemplateDumper(yaml.SafeDumper):
    """YAML dumper that preserves Jinja placeholders."""


def _str_presenter(dumper, data):
    """Quote strings containing Jinja syntax with double quotes."""
    style = '"' if "{{" in data or "}}" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


TemplateDumper.add_representer(str, _str_presenter)


class RunDatePlaceholder:
    """Object that renders Jinja placeholders for run_date."""

    def __str__(self):
        return "{{ run_date }}"

    def strftime(self, fmt):
        # Preserve the formatting expression for run time resolution
        return f"{{{{ run_date.strftime('{fmt}') }}}}"


class Env(str, Enum):
    """Valid deployment environments."""

    PROD = "prod"
    EXPERIMENT = "experiment"
    TEST = "test"


TEMPLATE_ROOT = "config-templates"
OVERRIDE_ROOT = "config-overrides"
OUTPUT_ROOT = "configs"

# Each job group contains templates for individual jobs. Each job has two
# template files: ``identity_config.yml.j2`` and ``outputs.yml.j2``. These
# render directly to ``identity_config.yml`` and ``outputs.yml`` under
# ``configs`` with plain key/value pairs.

jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATE_ROOT),
    undefined=StrictUndefined,
)
jinja_env.globals.update(
    # Use a placeholder so date is resolved at run time
    run_date=RunDatePlaceholder(),
    run_date_format="%Y-%m-%d",
    version_date_format="%Y%m%d",
    full_version_date_format="%Y%m%d000000",
)


def find_templates():
    templates = {}
    for root, _, files in os.walk(TEMPLATE_ROOT):
        for f in files:
            if f.endswith(".j2"):
                rel = os.path.relpath(os.path.join(root, f), TEMPLATE_ROOT)
                # ensure Jinja2-compatible separators
                rel = rel.replace(os.sep, "/")
                templates[rel] = jinja_env.get_template(rel)
    return templates


def find_env_roots():
    """Return all environment paths (e.g. ``prod`` or ``experiment/exp1``)."""
    envs = []
    for env in os.listdir(OVERRIDE_ROOT):
        env_dir = os.path.join(OVERRIDE_ROOT, env)
        if not os.path.isdir(env_dir):
            continue
        if env in ("experiment", "test"):
            for exp in os.listdir(env_dir):
                exp_dir = os.path.join(env_dir, exp)
                if os.path.isdir(exp_dir):
                    envs.append(f"{env}/{exp}")
        else:
            envs.append(env)
    return envs


def find_groups_for_env(env_path):
    """Return groups that contain at least one override under ``env_path``."""
    groups = []
    base = os.path.join(OVERRIDE_ROOT, env_path)
    if not os.path.isdir(base):
        return groups
    for entry in os.listdir(base):
        group_dir = os.path.join(base, entry)
        if not os.path.isdir(group_dir):
            continue
        for root, _, files in os.walk(group_dir):
            if any(f.endswith(".yml") for f in files):
                groups.append(entry)
                break
    return groups


def parse_env_path(env_path):
    """Return (env_name, exp_name) tuple from a path like ``prod`` or ``experiment/foo``."""
    parts = env_path.split("/")
    env_name = parts[0]
    exp_name = parts[1] if len(parts) > 1 else None
    return env_name, exp_name


def validate_cli_args(env_name, exp):
    """Validate and normalize the environment/experiment arguments."""
    if env_name == "all":
        if exp is not None:
            print(
                "When env=all, exp must not be provided",
                file=sys.stderr,
            )
            sys.exit(1)
        return env_name, "all"

    try:
        env = Env(env_name)
    except ValueError:
        print(f"Unknown env '{env_name}'", file=sys.stderr)
        sys.exit(1)

    if env is Env.PROD:
        if exp is not None:
            print("exp parameter is not allowed when env=prod", file=sys.stderr)
            sys.exit(1)
        return env.value, "all"

    if not exp:
        print(
            "exp parameter is required when env is experiment or test",
            file=sys.stderr,
        )
        sys.exit(1)

    return env.value, exp


def render_job(env_name, exp_name, env_path, group, job_name, template, filename):
    """Render a single job configuration file."""
    override_file = os.path.join(
        OVERRIDE_ROOT,
        env_path,
        group,
        job_name,
        "config.yml",
    )

    data = {}
    if os.path.exists(override_file):
        with open(override_file) as f:
            data = yaml.safe_load(f) or {}

    data.setdefault("environment", env_name)
    if env_name in (Env.EXPERIMENT.value, Env.TEST.value):
        data.setdefault("experimentName", exp_name)
    else:
        data.pop("experimentName", None)

    if exp_name:
        partition = f"{env_name}/{exp_name}"
    else:
        partition = env_name
    data.setdefault("data_namespace", partition)

    out_dir = os.path.join(OUTPUT_ROOT, env_path, group, job_name)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, filename)
    try:
        rendered = template.render(**data)
    except exceptions.UndefinedError as e:
        message = str(e)
        # Try to extract the missing variable name using regex, but always print the full message
        match = re.search(r"'([^']+)'", message)
        if match:
            missing_key = match.group(1)
            print(
                f"Error generating {env_path}/{job_name}/{filename}: "
                f"configuration '{missing_key}' is required but no value was provided "
                f"in {override_file}",
                file=sys.stderr,
            )
        else:
            print(
                f"Error generating {env_path}/{job_name}/{filename}: {message}",
                file=sys.stderr,
            )
        return

    data_dict = yaml.safe_load(rendered) or {}
    data_dict.pop("job_name", None)

    with open(out_path, "w") as f:
        yaml.dump(
            data_dict,
            f,
            Dumper=TemplateDumper,
            sort_keys=False,
            width=4096,
        )
    print(f"Wrote {out_path}")


def generate_group(env_name, exp_name, env_path, group, templates):
    """Generate all jobs for a single group."""
    for t_path, template in templates.items():
        job_path = os.path.splitext(t_path)[0]
        if not job_path.startswith(f"{group}/"):
            continue
        job_dir, filename = os.path.split(job_path)
        job_name = job_dir[len(f"{group}/") :]
        render_job(env_name, exp_name, env_path, group, job_name, template, filename)


def generate_env(env_name, exp_name, env_path, templates):
    """Generate all groups for a single environment path."""
    groups = find_groups_for_env(env_path)
    for group in groups:
        generate_group(env_name, exp_name, env_path, group, templates)


def generate_all(env_filter="all", exp_filter="all"):
    """Generate configuration files following the env -> exp layout.

    All groups that contain overrides under the selected environment are
    processed automatically.
    """
    if env_filter == "all":
        exp_filter = "all"
    templates = find_templates()
    env_paths = find_env_roots()
    if env_filter != "all":
        env_paths = [p for p in env_paths if p.startswith(env_filter)]
        if not env_paths:
            print(f"Environment '{env_filter}' not found", file=sys.stderr)
            return

    for env_path in env_paths:
        env_name, exp_name = parse_env_path(env_path)
        if exp_filter != "all" and exp_name != exp_filter:
            continue
        generate_env(env_name, exp_name, env_path, templates)


def parse_cli_args(argv):
    """Parse simple key=value arguments from ``argv`` in env -> exp order."""
    env_name = None
    exp = None
    for arg in argv:
        if "=" in arg:
            key, value = arg.split("=", 1)
            if key == "env":
                env_name = value
            elif key == "exp":
                exp = value
    if env_name is None:
        print(
            "Usage: generate_configs.py env=<env|all> exp=<exp|all>",
            file=sys.stderr,
        )
        sys.exit(1)

    return validate_cli_args(env_name, exp)


if __name__ == "__main__":
    env_name, exp = parse_cli_args(sys.argv[1:])
    generate_all(env_name, exp)
