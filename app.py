"""Flask entrypoint for Stock_analyze v3 staged upgrade.

The original analytics/AI APIs remain in ``ai_routes.py``.  This file only
registers the new multi-page UI and feature APIs so the existing technical,
fundamental, reporter and Ollama modules can continue to work unchanged.
"""
from __future__ import annotations

import os

from flask import Flask

from ai_routes import register_ai_routes
from database import init_db
from routes.features import features_bp
from routes.pages import pages_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.getenv("STOCK_ANALYZE_SECRET_KEY", "dev-secret-key-change-me")

    init_db()
    register_ai_routes(app)
    app.register_blueprint(features_bp)
    app.register_blueprint(pages_bp)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
