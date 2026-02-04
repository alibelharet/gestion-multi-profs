from edumaster import create_app

app = create_app()


if __name__ == "__main__":
    # Local dev over http: Secure cookies would prevent session from persisting.
    app.config["SESSION_COOKIE_SECURE"] = False
    app.run(host="0.0.0.0", port=5000, debug=False)
