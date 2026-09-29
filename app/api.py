import logging
from flask import Flask, jsonify, request
from flask_cors import CORS

from app.config import Config
from app.db import init_db
from app import jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kazi-q.api")


VALID_STATES = {"pending", "running", "succeeded", "failed", "dead"}


def create_app() -> Flask:
    app = Flask("kazi-q")
    CORS(app)

    @app.route("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.route("/jobs", methods=["GET"])
    def list_jobs():
        state = request.args.get("state")
        job_type = request.args.get("type")
        try:
            limit = int(request.args.get("limit", "100"))
        except ValueError:
            return jsonify({"error": "limit must be an integer"}), 400

        if state is not None and state not in VALID_STATES:
            return jsonify({"error": f"unknown state '{state}'"}), 400

        rows = jobs.list_jobs(state=state, job_type=job_type, limit=limit)
        return jsonify([jobs.to_dict(j) for j in rows])

    @app.route("/jobs", methods=["POST"])
    def post_job():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "body must be a JSON object"}), 400

        job_type = body.get("type")
        payload = body.get("payload", {})

        try:
            job = jobs.enqueue(job_type, payload)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

        return jsonify(jobs.to_dict(job)), 201

    @app.route("/jobs/<job_id>")
    def get_job(job_id):
        job = jobs.get(job_id)
        if job is None:
            return jsonify({"error": "job not found"}), 404
        return jsonify(jobs.to_dict(job))

    @app.route("/jobs/<job_id>", methods=["DELETE"])
    def delete_job(job_id):
        ok = jobs.delete(job_id)
        if not ok:
            return jsonify({"error": "job not found"}), 404
        return "", 204

    @app.route("/jobs/<job_id>/retry", methods=["POST"])
    def retry_job(job_id):
        job = jobs.retry(job_id)
        if job is None:
            return jsonify({"error": "job not found"}), 404
        return jsonify(jobs.to_dict(job))

    @app.route("/jobs/stats")
    def get_stats():
        return jsonify(jobs.stats())

    @app.route("/jobs/dead")
    def get_dead():
        dead = jobs.list_dead()
        return jsonify([jobs.to_dict(j) for j in dead])

    return app


def main():
    init_db()
    app = create_app()
    log.info("kazi-q API listening on %s:%s", Config.HOST, Config.PORT)
    app.run(host=Config.HOST, port=Config.PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()