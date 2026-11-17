import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # debug mode only ever listens on this computer: the debugger lets anyone who can reach it run code
    debug = os.environ.get("FLASK_DEBUG") == "1"
    app.run(host="127.0.0.1" if debug else os.environ.get("HOST", "0.0.0.0"), debug=debug)