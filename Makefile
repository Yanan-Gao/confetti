env ?=
exp ?=

.PHONY: build clean serve

ARGS := env=$(env)
ifneq ($(strip $(exp)),)
ARGS += exp=$(exp)
endif

build:
        python3 generate_configs.py $(ARGS)
clean:
        python -c "import shutil, os; shutil.rmtree('configs', ignore_errors=True); os.makedirs('configs', exist_ok=True)"

serve:
        python3 -m emr_launcher.service
