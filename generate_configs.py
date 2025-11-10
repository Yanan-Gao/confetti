import copy
import os
import sys
import subprocess
import importlib
from enum import Enum
import re


def log_info(message):
    """Log an informational message."""
    print(f"[INFO] {message}")


def log_warn(message):
    """Log a warning message."""
    print(f"[WARN] {message}", file=sys.stderr)


def log_error(message):
    """Log an error message."""
    print(f"[ERROR] {message}", file=sys.stderr)


# Ensure the script is executed with Python 3
if sys.version_info.major < 3:
    log_error("This script requires Python 3.")
    sys.exit(1)


def ensure_dependency(pkg, import_name=None):
    """Install the given package if the import fails."""
    import_name = import_name or pkg
    try:
        importlib.import_module(import_name)
    except ImportError:
        log_info(f"Installing missing dependency {pkg}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])


# Ensure color output is available before other imports
ensure_dependency("colorama")
from colorama import Fore, Style, init as colorama_init

colorama_init()


def log_info(message):
    print(f"{Fore.WHITE}[INFO] {message}{Style.RESET_ALL}")


def log_warn(message):
    print(f"{Fore.YELLOW}[WARN] {message}{Style.RESET_ALL}", file=sys.stderr)


def log_error(message):
    print(f"{Fore.RED}[ERROR] {message}{Style.RESET_ALL}", file=sys.stderr)


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

# Each job group contains templates for individual jobs. A job may provide
# multiple template files such as ``identity_config.yml.j2``,
# ``output_config.yml.j2`` and ``execution_config.yml.j2``. These render
# directly to files of the same name under ``configs`` with plain key/value
# pairs.

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
    """Return groups present under ``env_path``.

    In the past, at least one ``.yml`` override file was required for a group to
    be processed. This forced users to add empty override files merely to enable
    generation. Now every directory directly under the environment path is
    treated as a group. If a group contains no override files the jobs will warn
    when rendered, but generation will still occur.
    """
    groups = []
    base = os.path.join(OVERRIDE_ROOT, env_path)
    if not os.path.isdir(base):
        return groups
    for entry in os.listdir(base):
        group_dir = os.path.join(base, entry)
        if os.path.isdir(group_dir):
            groups.append(entry)
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
            log_error("When env=all, exp must not be provided")
            sys.exit(1)
        return env_name, "all"

    try:
        env = Env(env_name)
    except ValueError:
        log_error(f"Unknown env '{env_name}'")
        sys.exit(1)

    if env is Env.PROD:
        if exp is not None:
            log_error("exp parameter is not allowed when env=prod")
            sys.exit(1)
        return env.value, "all"

    if not exp:
        log_error("exp parameter is required when env is experiment or test")
        sys.exit(1)

    return env.value, exp


_variant_cache = {}


def _load_variant_defaults(group, job_name):
    """Return the default variant definitions for a job, preserving order."""

    cache_key = (group, job_name)
    if cache_key in _variant_cache:
        return copy.deepcopy(_variant_cache[cache_key])

    variants_path = os.path.join(
        TEMPLATE_ROOT,
        group,
        job_name,
        "variants.yml",
    )

    if not os.path.exists(variants_path):
        _variant_cache[cache_key] = []
        return []

    with open(variants_path) as f:
        raw = yaml.safe_load(f) or {}

    variants = raw.get("variants", []) if isinstance(raw, dict) else []
    cleaned = []
    for entry in variants:
        if not isinstance(entry, dict):
            log_warn(
                f"Ignoring invalid variant entry in {variants_path}: {entry!r}"
            )
            continue
        name = entry.get("name")
        if not name:
            log_warn(
                f"Ignoring variant without name in {variants_path}: {entry!r}"
            )
            continue
        cleaned.append(copy.deepcopy(entry))

    _variant_cache[cache_key] = cleaned
    return copy.deepcopy(cleaned)


def _merge_variants(defaults, overrides, override_file):
    """Merge default variants with overrides, keeping defaults order."""

    defaults = [copy.deepcopy(v) for v in defaults]
    overrides = overrides or []
    if not isinstance(overrides, list):
        log_warn(
            f"Variants override in {override_file} must be a list; found {type(overrides).__name__}"
        )
        return defaults

    override_map = {}
    for entry in overrides:
        if not isinstance(entry, dict):
            log_warn(
                f"Ignoring invalid variant override in {override_file}: {entry!r}"
            )
            continue
        name = entry.get("name")
        if not name:
            log_warn(
                f"Ignoring variant override without name in {override_file}: {entry!r}"
            )
            continue
        override_map[name] = {k: v for k, v in entry.items() if k != "name"}

    merged = []
    seen = set()
    for default in defaults:
        name = default.get("name")
        if not name:
            continue
        combined = copy.deepcopy(default)
        override_values = override_map.pop(name, None)
        if override_values:
            combined.update(override_values)
        merged.append(combined)
        seen.add(name)

    for name, override_values in override_map.items():
        combined = {"name": name}
        combined.update(override_values)
        merged.append(combined)

    if not merged and overrides:
        # No defaults were present; use overrides as-is (after cleaning above)
        for entry in overrides:
            name = entry.get("name") if isinstance(entry, dict) else None
            if not name:
                continue
            combined = {k: copy.deepcopy(v) for k, v in entry.items()}
            merged.append(combined)

    return merged


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
    else:
        log_warn(
            f"No override config found at {override_file}; using defaults"
        )

    variant_overrides = data.pop("variants", None)

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

    default_variants = _load_variant_defaults(group, job_name)
    merged_variants = _merge_variants(
        default_variants,
        variant_overrides,
        override_file,
    )

    variants_to_render = merged_variants if merged_variants else [None]

    for variant in variants_to_render:
        variant_name = None
        variant_values = {}
        if isinstance(variant, dict):
            variant_name = variant.get("name")
            variant_values = {
                k: copy.deepcopy(v)
                for k, v in variant.items()
                if k != "name"
            }

        render_data = copy.deepcopy(data)
        render_data.update(variant_values)
        if variant_name:
            render_data["variant"] = variant_name
        elif "variant" not in render_data:
            render_data["variant"] = None

        out_dir = os.path.join(OUTPUT_ROOT, env_path, group, job_name)
        if variant_name:
            out_dir = os.path.join(out_dir, variant_name)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, filename)
        try:
            rendered = template.render(**render_data)
        except exceptions.UndefinedError as e:
            message = str(e)
            match = re.search(r"'([^']+)'", message)
            location = f"{env_path}/{job_name}"
            if variant_name:
                location += f"[{variant_name}]"
            if match:
                missing_key = match.group(1)
                log_error(
                    f"Error generating {location}/{filename}: "
                    f"configuration '{missing_key}' is required but no value was provided "
                    f"in {override_file}"
                )
            else:
                log_error(
                    f"Error generating {location}/{filename}: {message}"
                )
            continue

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
        log_info(f"Wrote {out_path}")


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
            log_error(f"Environment '{env_filter}' not found")
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
        log_error(
            "Usage: generate_configs.py env=<env|all> exp=<exp|all>"
        )
        sys.exit(1)

    return validate_cli_args(env_name, exp)


if __name__ == "__main__":
    env_name, exp = parse_cli_args(sys.argv[1:])
    generate_all(env_name, exp)
