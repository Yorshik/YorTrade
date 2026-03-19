import logging

from aiohttp import web

from app.web.application import setup_app


def main():
    app = setup_app(config_path=".env")
    logging.info("Application started. Press Ctrl+C to stop.")
    web.run_app(app, host="0.0.0.0", port=5000)


if __name__ == "__main__":
    main()
