"""
Royal Brothers Fitness Gym - Admin Setup Script
Run this ONCE to create your first admin account.

How to run:
    Open the terminal in your GYM folder and run:
        python create_admin.py

    It will ask you to type a username and password, then save the
    admin account (with a securely hashed password) into the database.

You can delete this file after creating your admin account, or keep it
to create more admins later — running it again just adds another one.
"""

import getpass
import os
import sys

from werkzeug.security import generate_password_hash

# Allow running this script directly (`python scripts/create_admin.py`)
# from the project root by adding the project root to the import path,
# so the app package can be found.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.extensions import get_db_connection


def create_admin():
    print("=== Royal Brothers Fitness Gym - Create Admin Account ===")
    username = input("Enter admin username: ").strip()
    password = getpass.getpass("Enter admin password: ").strip()
    confirm = getpass.getpass("Confirm admin password: ").strip()

    if not username or not password:
        print("Username and password cannot be empty. Try again.")
        return

    if password != confirm:
        print("Passwords do not match. Try again.")
        return

    password_hash = generate_password_hash(password)

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if username already exists
    cursor.execute("SELECT id FROM admins WHERE username = %s", (username,))
    if cursor.fetchone():
        print(f"An admin with username '{username}' already exists.")
        cursor.close()
        conn.close()
        return

    cursor.execute(
        "INSERT INTO admins (username, password_hash) VALUES (%s, %s)",
        (username, password_hash),
    )
    conn.commit()
    cursor.close()
    conn.close()

    print(f"Admin account '{username}' created successfully.")


if __name__ == "__main__":
    create_admin()
