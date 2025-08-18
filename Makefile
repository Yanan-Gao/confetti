env ?=
exp ?=
group ?=
job ?=
run_date ?=

.PHONY: build clean generate-runtime-config

ARGS := env=$(env)
ifneq ($(strip $(exp)),)
ARGS += exp=$(exp)
endif

build:
	python3 generate_configs.py $(ARGS)
clean:
	python -c "import shutil, os; shutil.rmtree('configs', ignore_errors=True); os.makedirs('configs', exist_ok=True)"

RUNTIME_ARGS := env=$(env)
ifneq ($(strip $(exp)),)
RUNTIME_ARGS += exp=$(exp)
endif
ifneq ($(strip $(group)),)
RUNTIME_ARGS += group=$(group)
endif
ifneq ($(strip $(job)),)
RUNTIME_ARGS += job=$(job)
endif
ifneq ($(strip $(run_date)),)
RUNTIME_ARGS += run_date=$(run_date)
endif

generate-runtime-config:
	python3 generate_runtime_config.py $(RUNTIME_ARGS)
