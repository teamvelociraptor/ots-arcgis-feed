import os
import traceback
from dataclasses import dataclass
from opentakserver.extensions import logger
from flask import current_app as app
import yaml


@dataclass
class DefaultConfig:
    OTS_ARCGIS_FEED_ENABLED = True

    OTS_ARCGIS_FEED_REQUEST_TIMEOUT = 30

    OTS_ARCGIS_FEED_CALLSIGN_FIELD = "InstallationName"

    OTS_ARCGIS_FEED_FEEDS = []

    @staticmethod
    def validate(config: dict) -> dict[str, bool | str]:
        try:
            for key, value in config.items():
                if key not in DefaultConfig.__dict__.keys():
                    return {"success": False, "error": f"{key} is not a valid config key"}

                if key == "OTS_ARCGIS_FEED_ENABLED" and not isinstance(value, bool):
                    return {"success": False, "error": f"{key} should be a boolean"}
                elif key == "OTS_ARCGIS_FEED_REQUEST_TIMEOUT" and not isinstance(value, int):
                    return {"success": False, "error": f"{key} should be an integer"}
                elif key == "OTS_ARCGIS_FEED_CALLSIGN_FIELD" and not isinstance(value, str):
                    return {"success": False, "error": f"{key} should be a string"}
                elif key == "OTS_ARCGIS_FEED_FEEDS" and not isinstance(value, list):
                    return {"success": False, "error": f"{key} should be a list"}

            return {"success": True, "error": ""}
        except BaseException as e:
            logger.error(traceback.format_exc())
            return {"success": False, "error": str(e)}

    @staticmethod
    def save_config_settings(settings: dict[str, any]):
        try:
            with open(os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml"), "r") as config_file:
                config = yaml.safe_load(config_file.read())

            for setting, value in settings.items():
                config[setting] = value
                app.config.update({setting: value})

            with open(os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml"), "w") as config_file:
                yaml.safe_dump(config, config_file)

        except BaseException as e:
            logger.error(f"Failed to save settings {settings}: {e}")

    @staticmethod
    def update_config(config: dict) -> dict:
        try:
            valid = DefaultConfig.validate(config)
            if valid["success"]:
                DefaultConfig.save_config_settings(config)
                return {"success": True}
            else:
                return valid
        except BaseException as e:
            logger.error(f"Failed to update config: {e}")
            logger.error(traceback.format_exc())
            return {"success": False, "error": str(e)}
