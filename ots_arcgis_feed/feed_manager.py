import datetime
import json
import traceback
from xml.etree.ElementTree import tostring

import pika
from flask import current_app as app

from opentakserver.extensions import apscheduler, logger

from .arcgis_client import fetch_arcgis_features, parse_feature
from .cot_generator import generate_event, generate_point, add_detail

# Track UIDs per feed so we can delete removed markers
_previous_uids = {}


def _publish_to_exchanges(channel, group, message, properties):
    """Publish a CoT message to all 3 RabbitMQ exchanges."""
    channel.basic_publish(
        exchange="cot_parser", routing_key="", body=message, properties=properties,
    )
    channel.basic_publish(
        exchange="groups", routing_key=f"{group}.OUT", body=message, properties=properties,
    )
    channel.basic_publish(
        exchange="firehose", routing_key="", body=message, properties=properties,
    )


def scheduled_fetch_and_publish_feed(feed_config):
    """APScheduler entry point — wraps fetch_and_publish_feed with app context."""
    with apscheduler.app.app_context():
        fetch_and_publish_feed(feed_config)


def fetch_and_publish_feed(feed_config):
    """Fetch ArcGIS features, publish CoT events, delete removed markers.

    Must be called within a Flask app context.
    Returns a result dict with counts.
    """
    feed_name = feed_config["name"]
    feed_url = feed_config["url"]
    stale_minutes = feed_config.get("stale_minutes", 1440)
    cot_type = feed_config.get("cot_type", "a-f-G-U-C")
    cot_type_field = feed_config.get("cot_type_field")
    cot_type_mapping = feed_config.get("cot_type_mapping", {})
    group = feed_config.get("group", "__ANON__")
    timeout = app.config.get("OTS_ARCGIS_FEED_REQUEST_TIMEOUT", 30)
    callsign_field = feed_config.get("callsign_field",
                                     app.config.get("OTS_ARCGIS_FEED_CALLSIGN_FIELD", "InstallationName"))

    try:
        features = fetch_arcgis_features(feed_url, timeout=timeout)
        if not features:
            logger.warning(f"ArcGIS feed '{feed_name}': no features returned")
            return {"success": True, "feed": feed_name, "published": 0, "deleted": 0, "total_features": 0}

        rabbit_credentials = pika.PlainCredentials(
            app.config.get("OTS_RABBITMQ_USERNAME"),
            app.config.get("OTS_RABBITMQ_PASSWORD"),
        )
        rabbit_connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=app.config.get("OTS_RABBITMQ_SERVER_ADDRESS"),
                credentials=rabbit_credentials,
            )
        )
        channel = rabbit_connection.channel()
        channel.exchange_declare(exchange=group, exchange_type="fanout")

        now = datetime.datetime.now(datetime.timezone.utc)
        stale_time = now + datetime.timedelta(minutes=stale_minutes)
        properties = pika.BasicProperties(
            expiration=app.config.get("OTS_RABBITMQ_TTL"),
        )
        published = 0
        current_uids = set()

        for feature in features:
            parsed = parse_feature(feature, callsign_field=callsign_field)
            if parsed is None:
                continue

            uid = f"arcgis-{feed_name}-{parsed['object_id']}"
            current_uids.add(uid)

            # Resolve per-feature CoT type from mapping, fall back to feed default
            feature_cot_type = cot_type
            if cot_type_field and cot_type_mapping:
                field_value = feature.get("attributes", {}).get(cot_type_field)
                if field_value is not None:
                    feature_cot_type = cot_type_mapping.get(str(field_value), cot_type)

            event = generate_event(
                start_time=now, stale_time=stale_time, uid=uid, cot_type=feature_cot_type,
            )
            event = generate_point(event, lat=parsed["lat"], lon=parsed["lon"])
            event = add_detail(event, "contact", {"callsign": parsed["callsign"]})
            if parsed["remarks"]:
                event = add_detail(event, "remarks", {}, text=parsed["remarks"])

            cot_xml = tostring(event, encoding="unicode")
            message = json.dumps({"cot": cot_xml, "uid": app.config["OTS_NODE_ID"]})
            _publish_to_exchanges(channel, group, message, properties)
            published += 1

        # Delete markers that no longer exist in the feed
        previous = _previous_uids.get(feed_name, set())
        removed = previous - current_uids
        for uid in removed:
            delete_event = generate_event(
                start_time=now, stale_time=stale_time, uid=uid, cot_type="t-x-d-d",
            )
            delete_event = generate_point(delete_event)
            cot_xml = tostring(delete_event, encoding="unicode")
            message = json.dumps({"cot": cot_xml, "uid": app.config["OTS_NODE_ID"]})
            _publish_to_exchanges(channel, group, message, properties)

        _previous_uids[feed_name] = current_uids

        channel.close()
        rabbit_connection.close()

        logger.info(
            f"ArcGIS feed '{feed_name}': published {published}/{len(features)} CoT events, "
            f"deleted {len(removed)} removed markers"
        )
        return {
            "success": True, "feed": feed_name,
            "published": published, "deleted": len(removed),
            "total_features": len(features),
        }

    except BaseException as e:
        logger.error(f"ArcGIS feed '{feed_name}' failed: {e}")
        logger.error(traceback.format_exc())
        return {"success": False, "feed": feed_name, "error": str(e)}


def clear_feed(feed_name, group="__ANON__"):
    """Send delete CoT events for all tracked markers in a feed.

    Must be called within a Flask app context.
    """
    previous = _previous_uids.get(feed_name, set())
    if not previous:
        return {"success": True, "feed": feed_name, "deleted": 0}

    try:
        rabbit_credentials = pika.PlainCredentials(
            app.config.get("OTS_RABBITMQ_USERNAME"),
            app.config.get("OTS_RABBITMQ_PASSWORD"),
        )
        rabbit_connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=app.config.get("OTS_RABBITMQ_SERVER_ADDRESS"),
                credentials=rabbit_credentials,
            )
        )
        channel = rabbit_connection.channel()

        now = datetime.datetime.now(datetime.timezone.utc)
        stale_time = now + datetime.timedelta(minutes=1)
        properties = pika.BasicProperties(
            expiration=app.config.get("OTS_RABBITMQ_TTL"),
        )

        for uid in previous:
            delete_event = generate_event(
                start_time=now, stale_time=stale_time, uid=uid, cot_type="t-x-d-d",
            )
            delete_event = generate_point(delete_event)
            cot_xml = tostring(delete_event, encoding="unicode")
            message = json.dumps({"cot": cot_xml, "uid": app.config["OTS_NODE_ID"]})
            _publish_to_exchanges(channel, group, message, properties)

        channel.close()
        rabbit_connection.close()

        deleted = len(previous)
        _previous_uids[feed_name] = set()
        logger.info(f"ArcGIS feed '{feed_name}': cleared {deleted} markers")
        return {"success": True, "feed": feed_name, "deleted": deleted}

    except BaseException as e:
        logger.error(f"Failed to clear feed '{feed_name}': {e}")
        logger.error(traceback.format_exc())
        return {"success": False, "feed": feed_name, "error": str(e)}
