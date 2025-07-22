# Confetti

This repository demonstrates a simple configuration generation workflow using **Jinja2** templates and YAML overrides. Generated files are written into the `configs` directory and should not be manually edited.

## Requirements

* Python 3
* `make`

## Structure
```
config-templates/   # Jinja2 templates
config-overrides/   # Human-provided values
configs/            # Generated output
```

Override files and generated configs are organized with the environment as the
first directory level. Under each environment you can have one or more *group*
directories that contain related jobs. For example, overrides for the `prod`
environment might live under `config-overrides/prod/audience/` and the
generated files would be written to `configs/prod/audience/`. The generator
automatically processes any group that contains at least one override so you do
not need to specify the group name on the command line. Future groups such as
`feature_store` or `kongming` can use the same pattern and will be picked up
automatically when overrides are added.

Each job template provides two files: `behavioral_config.yml.j2` for the
behavior-related settings and `outputs.yml.j2` for any output paths. Running the
generator renders these templates to `behavioral_config.yml` and `outputs.yml`
under the corresponding job directory. Each generated YAML file contains plain
key/value pairs. The rendered YAML includes an `environment` key that is set to
`prod`, `test` or `experiment`. Non-production files also include an
`experimentName` key with the experiment identifier.

## Usage
Run the generator:
```bash
make build
```
The Makefile forwards two parameters to `generate_configs.py`:
`env` and `exp`. The script discovers groups by looking for overrides under the
given environment and experiment. None of the parameters default to `all` so
you must specify the desired value explicitly. To generate every configuration
you can pass `env=all`:
```bash
make build env=all
```
When a higher-level option is set to `all` no lower level option may be
specified. For example, it is invalid to provide `exp` when `env=all`.
When `env` is `experiment` or `test` you must also provide an `exp` value. The
`prod` environment does not take an experiment parameter.
To generate the configs for a single experiment you might run:
```bash
make build env=experiment exp=yanan-demo
```
The `generate_configs.py` script automatically installs `Jinja2` and `PyYAML` if they
are missing. The `build` target runs the script and populates `configs` with rendered
YAML files.
You can clean out generated files with:
```bash
make clean
```
The clean target uses Python so it works on Windows as well as Unix-like systems.

## Customizing date formats

Templates can format dates using two global variables:

- `run_date_format` controls how the `run_date` placeholder is rendered and
  defaults to `%Y-%m-%d`.
- `version_date_format` controls paths that incorporate the run date and
  defaults to `%Y%m%d`.

Override these values in your job-specific configuration files when a different
format is required.

## CI pipeline

When a merge request updates `config-overrides/` without regenerating the files
under `configs/`, the GitLab pipeline automatically runs `make build env=all`.
If new files are produced, a commit named `ci: auto-generate configs` is pushed
back to the branch so the generated configs stay in sync.
