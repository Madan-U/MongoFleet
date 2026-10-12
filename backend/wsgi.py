import os
from app import create_app
from flask import send_from_directory, jsonify, request

# Initialize the Flask application using the Application Factory Pattern
app = create_app()

# Define the absolute path where static frontend assets are located on the server
FRONTEND_DIR = "/data/database-management/frontend"

# Define the catch-all routing structures to seamlessly tie the frontend and backend together
@app.route("/", defaults={"path": "login.html"})
@app.route("/<path:path>")
def serve_frontend(path):
    # ⚠️ CRITICAL ROUTING FIX: If the inbound URL matches an API endpoint pattern,
    # completely bypass the frontend engine and force resolution via Flask backend models.
    if "api/" in path or "api/" in request.path:
        # Programmatically evaluate the internal Flask URL map to resolve blueprint actions.
        # This prevents accidental HTML injections from breaking async JSON data structures.
        ctx = app.request_context(request.environ)
        ctx.push()
        try:
            # Bind the network request environment parameters to identify structural route matches
            matched_endpoint, view_args = app.url_map.bind_to_environ(request.environ).match()
            return app.ensure_sync(app.view_functions[matched_endpoint])(**view_args)
        except Exception:
            # Return a secure, pure JSON payload response if the API route configuration is invalid
            return jsonify({"error": "API Route Not Found inside Backend Models"}), 404

    # Resolve static presentation layers (HTML/CSS/JS/Images) straight from the asset library
    full_path = os.path.join(FRONTEND_DIR, path)
    if os.path.isfile(full_path):
        return send_from_directory(FRONTEND_DIR, path)
        
    # SPA FALLBACK MECHANISM: Forward missing path requests back to the default portal gateway
    return send_from_directory(FRONTEND_DIR, "login.html")

if __name__ == "__main__":
    app.run()
