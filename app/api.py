import logging
from flask import Flask, jsonify, request

from app.config import Config
from app.db import init_db
from app import jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kazi-q.api")


def create_app() -> Flask:
    app = Flask("kazi-q")

    @app.route("/health")
    def health():
        return jsonify({"status": "ok"})

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