import os
import pathlib
import traceback

import yaml
from flask import Blueprint, jsonify, Flask, current_app as app, request, send_from_directory
from flask_security import roles_accepted
from opentakserver.plugins.Plugin import Plugin
from opentakserver.extensions import apscheduler, logger

from .default_config import DefaultConfig
from .feed_manager import scheduled_fetch_and_publish_feed, fetch_and_publish_feed, clear_feed
import importlib.metadata


class ArcGISFeedPlugin(Plugin):
    metadata = pathlib.Path(__file__).resolve().parent.name
    url_prefix = f"/api/plugins/{metadata.lower()}"
    blueprint = Blueprint("ArcGISFeedPlugin", __name__, url_prefix=url_prefix)

    def __init__(self):
        super().__init__()
        self._job_ids = []

    def activate(self, app: Flask, enabled: bool = True):
        self._app = app
        self._load_config()
        self.load_metadata()

        try:
            if not enabled:
                logger.info(f"{self.name} is disabled")
                return

            if not self._config.get("OTS_ARCGIS_FEED_ENABLED", True):
                logger.info("ArcGIS Feed plugin is disabled via config")
                return

            feeds = self._config.get("OTS_ARCGIS_FEED_FEEDS", [])
            for feed in feeds:
                job_id = f"arcgis_feed_{feed['name']}"
                interval = feed.get("interval_minutes", 15)

                apscheduler.add_job(
                    id=job_id,
                    func=scheduled_fetch_and_publish_feed,
                    trigger="interval",
                    minutes=interval,
                    args=[feed],
                    replace_existing=True,
                )
                self._job_ids.append(job_id)
                logger.info(f"Scheduled ArcGIS feed '{feed['name']}' every {interval} minutes")

            logger.info(f"Successfully loaded {self.name}")
        except BaseException as e:
            logger.error(f"Failed to load {self.name}: {e}")
            logger.error(traceback.format_exc())

    def load_metadata(self):
        try:
            self.distro = pathlib.Path(__file__).resolve().parent.name
            self.metadata = importlib.metadata.metadata(self.distro).json
            self.name = self.metadata['name']
            self.metadata['distro'] = self.distro
            return self.metadata
        except BaseException as e:
            logger.error(e)
            logger.debug(traceback.format_exc())
            return None

    def _load_config(self):
        for key in dir(DefaultConfig):
            if key.isupper():
                self._config[key] = getattr(DefaultConfig, key)
                self._app.config.update({key: getattr(DefaultConfig, key)})

        with open(os.path.join(self._app.config.get("OTS_DATA_FOLDER"), "config.yml")) as yaml_file:
            yaml_config = yaml.safe_load(yaml_file)
            for key in self._config.keys():
                value = yaml_config.get(key)
                if value:
                    self._config[key] = value
                    self._app.config.update({key: value})

    def get_info(self):
        self.load_metadata()
        self.get_plugin_routes(self.url_prefix)
        return {'name': self.name, 'distro': self.distro, 'routes': self.routes}

    def stop(self):
        for job_id in self._job_ids:
            try:
                apscheduler.remove_job(job_id)
                logger.info(f"Removed scheduled job: {job_id}")
            except BaseException as e:
                logger.debug(f"Could not remove job {job_id}: {e}")
        self._job_ids.clear()

    @staticmethod
    @roles_accepted("administrator")
    @blueprint.route("/")
    def plugin_info():
        try:
            distribution = None
            distributions = importlib.metadata.packages_distributions()
            for distro in distributions:
                if str(__name__).startswith(distro):
                    distribution = distributions[distro][0]
                    break

            if distribution:
                info = importlib.metadata.metadata(distribution)
                return jsonify(info.json)
            else:
                return jsonify({'success': False, 'error': 'Plugin not found'}), 404
        except BaseException as e:
            logger.error(e)
            return jsonify({'success': False, 'error': str(e)}), 500

    @staticmethod
    @roles_accepted("administrator")
    @blueprint.route("/ui")
    def ui():
        ui_dir = os.path.join(pathlib.Path(__file__).parent.resolve(), "ui")
        return send_from_directory(ui_dir, "index.html", as_attachment=False)

    @staticmethod
    @blueprint.route('/assets/<file_name>')
    @blueprint.route("/ui/<file_name>")
    def serve(file_name):
        ui_dir = os.path.join(pathlib.Path(__file__).parent.resolve(), "ui")
        assets_path = os.path.join(ui_dir, "assets", file_name)
        root_path = os.path.join(ui_dir, file_name)
        if file_name and os.path.exists(assets_path):
            return send_from_directory(os.path.join(ui_dir, "assets"), file_name)
        elif file_name and os.path.exists(root_path):
            return send_from_directory(ui_dir, file_name)
        else:
            return '', 404

    @staticmethod
    @roles_accepted("administrator")
    @blueprint.route("/config")
    def config():
        config = {}
        for key in dir(DefaultConfig):
            if key.isupper():
                config[key] = app.config.get(key)
        return jsonify(config)

    @staticmethod
    @roles_accepted("administrator")
    @blueprint.route("/config", methods=["POST"])
    def update_config():
        try:
            result = DefaultConfig.update_config(request.json)
            if result["success"]:
                return jsonify(result)
            else:
                return jsonify(result), 400
        except BaseException as e:
            logger.error("Failed to update config: " + str(e))
            logger.error(traceback.format_exc())
            return jsonify({"success": False, "error": str(e)}), 400

    @staticmethod
    @roles_accepted("administrator")
    @blueprint.route("/fetch", methods=["POST"])
    def fetch_all():
        """Manually trigger a fetch for all configured feeds."""
        try:
            feeds = app.config.get("OTS_ARCGIS_FEED_FEEDS", [])
            results = []
            for feed in feeds:
                result = fetch_and_publish_feed(feed)
                results.append(result)
            return jsonify({"success": True, "feeds": results})
        except BaseException as e:
            logger.error(f"Failed to fetch feeds: {e}")
            logger.error(traceback.format_exc())
            return jsonify({"success": False, "error": str(e)}), 500

    @staticmethod
    @roles_accepted("administrator")
    @blueprint.route("/fetch/<feed_name>", methods=["POST"])
    def fetch_one(feed_name):
        """Manually trigger a fetch for a single feed by name."""
        try:
            feeds = app.config.get("OTS_ARCGIS_FEED_FEEDS", [])
            for feed in feeds:
                if feed["name"] == feed_name:
                    result = fetch_and_publish_feed(feed)
                    return jsonify(result)
            return jsonify({"success": False, "error": f"Feed '{feed_name}' not found"}), 404
        except BaseException as e:
            logger.error(f"Failed to fetch feed '{feed_name}': {e}")
            logger.error(traceback.format_exc())
            return jsonify({"success": False, "error": str(e)}), 500

    @staticmethod
    @roles_accepted("administrator")
    @blueprint.route("/clear/<feed_name>", methods=["POST"])
    def clear_one(feed_name):
        """Delete all markers for a feed from ATAK clients."""
        try:
            feeds = app.config.get("OTS_ARCGIS_FEED_FEEDS", [])
            for feed in feeds:
                if feed["name"] == feed_name:
                    result = clear_feed(feed_name, group=feed.get("group", "__ANON__"))
                    return jsonify(result)
            return jsonify({"success": False, "error": f"Feed '{feed_name}' not found"}), 404
        except BaseException as e:
            logger.error(f"Failed to clear feed '{feed_name}': {e}")
            logger.error(traceback.format_exc())
            return jsonify({"success": False, "error": str(e)}), 500
