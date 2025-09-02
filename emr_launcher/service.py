"""Flask service for launching EMR jobs."""
from flask import Flask, jsonify, request, render_template

from . import emr

app = Flask(__name__)


@app.get("/")
def index():
    """Render a placeholder index page."""
    return render_template("index.html")


@app.post("/jobs")
def create_job():
    """Launch an EMR job from a template.

    Expected JSON body::

        {
            "job": "AudienceCalibrationAndMergeJob",
            "env": "test|experiment|prod",
            "experiment": "name if env requires it",
            "overrides": {...},
            "runtime": {"run_date": "YYYYMMDD"},
            "forceRun": false
        }
    """
    payload = request.get_json(force=True)
    emr.launch_job(
        job=payload["job"],
        env=payload["env"],
        experiment=payload.get("experiment"),
        overrides=payload.get("overrides", {}),
        runtime=payload.get("runtime", {}),
        force_run=bool(payload.get("forceRun")),
    )
    return jsonify({"status": "submitted"})


@app.post("/clone")
def clone_cluster():
    """Clone an existing EMR cluster.

    Expects a JSON body::

        {"cluster_id": "j-ABCDEFGHI"}
    """
    payload = request.get_json(force=True)
    new_id = emr.clone_cluster(payload["cluster_id"], payload.get("overrides", {}))
    return jsonify({"status": "submitted", "cluster_id": new_id})


if __name__ == "__main__":  # pragma: no cover - manual execution
    app.run(host="0.0.0.0", port=8080)
