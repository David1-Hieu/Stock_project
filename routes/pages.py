from __future__ import annotations

from flask import Blueprint, redirect, render_template

pages_bp = Blueprint("pages", __name__)


@pages_bp.get("/")
def dashboard_page():
    return render_template("dashboard.html", page="dashboard", title="Dashboard")


@pages_bp.get("/screener")
def screener_page():
    return render_template("screener.html", page="screener", title="Stock Screener")


@pages_bp.get("/analysis")
def analysis_home_page():
    return redirect("/analysis/FPT")


@pages_bp.get("/analysis/<symbol>")
def analysis_page(symbol: str):
    return render_template("stock_analysis.html", page="analysis", title=f"Phân tích {symbol.upper()}", symbol=symbol.upper())


@pages_bp.get("/watchlist")
def watchlist_page():
    return render_template("watchlist.html", page="watchlist", title="Watchlist")


@pages_bp.get("/portfolio")
def portfolio_page():
    return render_template("portfolio.html", page="portfolio", title="Portfolio")


@pages_bp.get("/ai-reports")
def reports_page():
    return render_template("ai_reports.html", page="ai_reports", title="AI Reports")


@pages_bp.get("/settings")
def settings_page():
    return render_template("settings.html", page="settings", title="Settings")


@pages_bp.get("/legacy")
def legacy_page():
    return render_template("index.html")
