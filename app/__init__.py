"""
Royal Brothers Fitness Gym - Flask Application Factory
Builds and configures the Flask app: config, Flask-Mail, blueprints,
and static frontend serving.

The actual server entry point is wsgi.py at the project root, which
imports create_app() from here. This split (factory in a package,
thin entry point at the root) is the standard Flask production layout
and is what Render/Railway/Gunicorn expect.
"""

import os

from flask import Flask, jsonify, request, send_from_directory
from flask_mail import Mail
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .security import is_same_origin
mail = Mail()
from .routes.auth_routes import auth_bp
from .routes.membership_routes import membership_bp
from .routes.contact_routes import contact_bp
from .routes.admin_routes import admin_bp
from .routes.admin_pages_routes import admin_pages_bp  # Phase 3: admin-only HTML pages
from .routes.ai_routes import ai_bp  # Gemini test route (temporary)
from .routes.fitness_routes import fitness_bp  # Step 2: Fitness Profile
from .routes.workout_routes import workout_bp  # Step 3: AI Workout Plan
from .routes.daily_routes import daily_bp  # Step 4: AI Daily Planner
from .routes.progress_routes import progress_bp  # Step 5: Fitness Progress
from .routes.insights_routes import insights_bp  # Step 6: AI Fitness Insights
from .routes.recommendation_routes import recommend_bp  # Step 7: Smart Workout Recommendations
from .routes.nutrition_routes import nutrition_bp  # Step 8: AI Nutrition Planner
from .routes.dashboard_routes import dashboard_bp  # Step 9: Member AI Dashboard

# Flask-Mail instance, shared by any route module that needs to send
# email (imported lazily inside functions as `from .. import mail` to
# avoid circular imports with the blueprints above).



def create_app():
    app = Flask(
        __name__,
        static_folder="static",
        static_url_path="",
    )

    # Load Config (reads environment variables; raises a clear error at
    # startup if a required secret is missing -- see app/config.py)
    app.config.from_object(Config)

    # Trust forwarded host/scheme headers only when the operator has
    # explicitly counted the trusted reverse-proxy hops. Default is zero.
    proxy_count = app.config.get("TRUSTED_PROXY_COUNT", 0)
    if proxy_count:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=proxy_count,
            x_proto=proxy_count,
            x_host=proxy_count,
            x_port=proxy_count,
        )

    # Initialize Flask-Mail
    mail.init_app(app)

    # Register API blueprints
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(membership_bp, url_prefix="/api/membership")
    app.register_blueprint(contact_bp, url_prefix="/api/contact")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")
    app.register_blueprint(admin_pages_bp, url_prefix="/admin")  # Phase 3: friction insights page
    app.register_blueprint(ai_bp, url_prefix="/ai")  # Gemini test route (temporary)
    app.register_blueprint(fitness_bp, url_prefix="/api/fitness-profile")  # Step 2
    app.register_blueprint(workout_bp, url_prefix="/api/workout-plan")  # Step 3
    app.register_blueprint(daily_bp, url_prefix="/api/daily-plan")  # Step 4
    app.register_blueprint(progress_bp, url_prefix="/api/progress")  # Step 5
    app.register_blueprint(insights_bp, url_prefix="/api/insights")  # Step 6
    app.register_blueprint(recommend_bp, url_prefix="/api/workout-recommendations")  # Step 7
    app.register_blueprint(nutrition_bp, url_prefix="/api/nutrition-plan")  # Step 8
    app.register_blueprint(dashboard_bp, url_prefix="/api/dashboard")  # Step 9

    # Home page
    @app.route("/")
    def serve_index():
        return send_from_directory(app.static_folder, "index.html")

    # Serve HTML/CSS/JS/image files (multi-page frontend, no templating)
    @app.route("/<path:filename>")
    def serve_frontend_files(filename):
        return send_from_directory(app.static_folder, filename)

    @app.before_request
    def reject_cross_origin_mutations():
        """Reject supplied cross-origin Origin headers on all state changes.

        Missing Origin remains accepted for compatibility with existing
        non-browser clients; new browser-facing write routes should still
        require an explicit same-origin Origin where appropriate.
        """
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        origin = request.headers.get("Origin")
        if origin is not None and not is_same_origin(origin, request.host_url):
            message = "Cross-site requests are not allowed."
            return jsonify({
                "success": False,
                "message": message,
                "error": {"code": "cross_origin", "message": message},
            }), 403
        return None

    return app
