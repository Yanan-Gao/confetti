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

Each job template provides three files: `identity_config.yml.j2` for the
behavior-related settings, `output_config.yml.j2` for any output paths, and
`execution_config.yml.j2` for runtime options. Running the generator renders
these templates to `identity_config.yml`, `output_config.yml`, and
`execution_config.yml` under the corresponding job directory. Each generated
YAML file contains plain key/value pairs. The rendered YAML includes an
`environment` key that is set to `prod`, `test` or `experiment`.
Non-production files also include an `experimentName` key with the experiment
identifier.

## Usage

### Example workflow
- **Onboard a new group** – create a template folder under the template root (config-templates/{group}), usually you'll want to have some jobs. See below about how to create a job template. E.g, I've already created a group called audience.
- **Onboard a new job** – create a folder under the group (config-templates/{group}/{jobName}), with the usual three config templates (`identity_config.yml.j2`, `output_config.yml.j2` and `execution_config.yml.j2`) and run build (see below).
- **Add a new parameter** – add the field to the template accordingly, and run the build.
- **Add a new experiment** – place overrides in `config-overrides` for the jobs that you want to change, and provide override values accordingly, and run the build.
- **Change an argument** – edit the corresponding override file and run the build.

**!!Remember you don't need, and you should not to change any files under configs/ path!!**

### Build

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

### Runtime configuration

Once build-time configs are generated, runtime values such as `run_date` can be
resolved and uploaded to a hashed location. Use:

```bash
make generate-runtime-config env=<env> [exp=<exp>] [job=<job>] run_date=<YYYYMMDD>
```

Non-production environments require an `exp` value while production must omit it.
The command renders the runtime configuration, injects the `audienceJarPath`,
writes the files under `runtime-configs/` and uploads them to the matching S3
location.

## Reserved keywords

The generator populates several keys automatically, which helps user to populate values automatically, or as 
runtime value placeholder etc. Do **not** override them unless you know what you are doing:

- `environment` – one of `prod`, `test` or `experiment`.
- `experimentName` – the experiment identifier for non-production environments.
- `data_namespace` – base path partition derived from the environment.
- `run_date` – the logical run date used by templates.
- `run_date_format` – format string for `run_date` (default `%Y-%m-%d`).
- `version_date_format` – version path date format (default `%Y%m%d`).
- `full_version_date_format` – full timestamp format (default `%Y%m%d000000`).

## Configuration groups

Each job exposes three configuration files:

1. **identity** – settings that impact results, rendered from
   `identity_config.yml.j2`.
2. **execution** – options controlling how the job runs. Currently the only
   field is `forceRun`, rendered from `execution_config.yml.j2`.
3. **output** – paths to all expected outputs, rendered from
   `output_config.yml.j2`.

Provide a single `config.yml` in your override folder to replace any values in
these templates. If a template omits a default value for a field, that field
becomes required in your override.

## CI pipeline

Every branch triggers an automatic build. If you modify `config-overrides/`
without updating the generated files, the pipeline runs `make build env=all` and check if there 
is any diff, if found any diff, the pipeline will fail, so give user a warning of not building.

Your branch deployment targets the **test** environment. After your changes are
merged into `master`, the pipeline deploys the **experiment** and **prod**
configs.
