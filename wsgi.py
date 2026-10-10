"""
Royal Brothers Fitness Gym - WSGI Entry Point

Local development:
    python wsgi.py

Production (Render / Railway / any WSGI host):
    gunicorn wsgi:app
    (see Procfile)
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
