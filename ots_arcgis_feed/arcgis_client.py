import traceback

import requests
from opentakserver.extensions import logger

# Internal/computed fields to skip in remarks
SKIP_FIELDS = {
    "FID", "OBJECTID", "OBJECTID_1", "ObjectId", "SourceOID",
    "Shape__Length", "Shape__Len", "Shape__Area",
    "GlobalID", "SourceGlobalID", "IrwinID",
    "CreatedOnDateTime_dt", "ModifiedOnDateTime_dt",
}


def fetch_arcgis_features(url, timeout=30):
    """Fetch features from an ArcGIS FeatureServer query endpoint.

    Returns a list of feature dicts, or an empty list on failure.
    """
    try:
        r = requests.get(url, timeout=timeout)

        if r.status_code != 200:
            logger.error(f"ArcGIS request failed with status {r.status_code}: {r.text}")
            return []

        data = r.json()

        if "error" in data:
            logger.error(f"ArcGIS API error: {data['error']}")
            return []

        features = data.get("features", [])
        logger.info(f"Fetched {len(features)} features from ArcGIS")
        return features
    except BaseException as e:
        logger.error(f"Failed to fetch ArcGIS features: {e}")
        logger.error(traceback.format_exc())
        return []


def parse_feature(feature, callsign_field="InstallationName"):
    """Extract location, callsign, and remarks from a single ArcGIS feature.

    Returns a dict with keys: lat, lon, object_id, callsign, remarks
    or None if the feature lacks valid geometry.
    """
    try:
        attr = feature.get("attributes", {})
        geom = feature.get("geometry", {})

        lon = geom.get("x")
        lat = geom.get("y")
        if lon is None or lat is None:
            return None

        object_id = attr.get("OBJECTID") or attr.get("OBJECTID_1") or attr.get("FID") or attr.get("ObjectId")

        # Use configured callsign field, then try common name fields
        callsign = attr.get(callsign_field)
        if not callsign or str(callsign).strip() == "":
            for field in ("IncidentName", "InstallationName", "Plant_Name",
                          "Name", "NAME", "Affiliation", "OWNER"):
                val = attr.get(field)
                if val and str(val).strip():
                    callsign = val
                    break
        if not callsign or str(callsign).strip() == "":
            callsign = "Unknown"

        # Build remarks from all non-null, non-internal attributes
        remarks_parts = []
        for key, val in attr.items():
            if key in SKIP_FIELDS:
                continue
            if val is not None and str(val).strip() and str(val) != "-999999":
                remarks_parts.append(f"{key}: {val}")

        remarks = "\n".join(remarks_parts) if remarks_parts else ""

        return {
            "lat": lat,
            "lon": lon,
            "object_id": object_id,
            "callsign": str(callsign).strip(),
            "remarks": remarks,
        }
    except BaseException as e:
        logger.error(f"Failed to parse ArcGIS feature: {e}")
        logger.error(traceback.format_exc())
        return None
