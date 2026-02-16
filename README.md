# ots-arcgis-feed

An [OpenTAKServer](https://github.com/brian7704/OpenTAKServer) plugin that fetches ArcGIS FeatureServer data and broadcasts it as Cursor on Target (CoT) events to ATAK/WinTAK clients via RabbitMQ.

## Features

- **Multiple ArcGIS Feeds** — configure any number of ArcGIS FeatureServer endpoints, each with its own polling interval, CoT type, and ATAK group
- **Automatic Marker Lifecycle** — tracks feature UIDs per feed; automatically sends CoT delete events (`t-x-d-d`) when features disappear from the source
- **Per-Feature CoT Type Mapping** — optionally map an ArcGIS attribute field to different CoT types for richer ATAK symbology
- **Management UI** — built-in web UI for viewing and updating plugin configuration (accessible from the OTS plugin page)
- **REST API** — manual fetch, clear, and config endpoints for automation
- **Live Config Updates** — change feed settings at runtime; persisted to `config.yml`

## Installation

### Via OTS Web UI (recommended)

1. Download the latest `.whl` from [Releases](https://github.com/teamvelociraptor/ots-arcgis-feed/releases)
2. Upload it on the OTS web UI **Plugins** page
3. Restart OpenTAKServer

### Via pip

```bash
pip install ots-arcgis-feed
# or install from a local wheel
pip install ots_arcgis_feed-1.0.0-py3-none-any.whl
```

## Configuration

Add feed definitions to your OTS `config.yml` (typically `~/ots/config.yml`):

```yaml
OTS_ARCGIS_FEED_ENABLED: true

OTS_ARCGIS_FEED_FEEDS:
  - name: my_feed
    url: "https://services.arcgis.com/.../FeatureServer/0/query?where=1%3D1&outSR=4326&outFields=*&returnGeometry=true&f=pjson"
    interval_minutes: 15
    stale_minutes: 1440
    cot_type: "a-f-G-U-C"
    group: "__ANON__"
    # Optional: map an ArcGIS field to different CoT types
    cot_type_field: null
    cot_type_mapping: {}
```

### Configuration Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `OTS_ARCGIS_FEED_ENABLED` | bool | `true` | Global enable/disable toggle |
| `OTS_ARCGIS_FEED_REQUEST_TIMEOUT` | int | `30` | HTTP request timeout (seconds) |
| `OTS_ARCGIS_FEED_CALLSIGN_FIELD` | str | `"InstallationName"` | ArcGIS attribute field used as the CoT callsign |
| `OTS_ARCGIS_FEED_FEEDS` | list | *(see above)* | List of feed definitions |

### Feed Definition Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Unique identifier for the feed |
| `url` | yes | ArcGIS FeatureServer query URL (must return `pjson` with `outSR=4326`) |
| `interval_minutes` | no | Polling interval (default: 15) |
| `stale_minutes` | no | CoT marker stale time in minutes (default: 1440) |
| `cot_type` | no | CoT type string for ATAK symbology (default: `a-h-G-U-C`) |
| `group` | no | RabbitMQ/ATAK group routing key (default: `__ANON__`) |
| `cot_type_field` | no | ArcGIS attribute field for per-feature type mapping |
| `cot_type_mapping` | no | `{field_value: cot_type}` mapping dict |

## Management API

All endpoints require the `administrator` role. Base path: `/api/plugins/ots_arcgis_feed`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/config` | View current plugin configuration |
| POST | `/config` | Update and persist config to `config.yml` |
| POST | `/fetch` | Manually trigger all feeds |
| POST | `/fetch/<feed_name>` | Manually trigger a specific feed |
| POST | `/clear/<feed_name>` | Send delete events for all markers in a feed |
| GET | `/ui` | Plugin management UI |

## Building from Source

### Plugin (Python)

```bash
cd ots_arcgis_feed
python -m venv .venv && source .venv/bin/activate
pip install build
python -m build --wheel
```

Output: `dist/ots_arcgis_feed-*.whl`

### UI (Node.js)

The management UI is a React + Mantine app built with Vite:

```bash
cd ots_arcgis_feed_ui
npm install
npm run build
```

Copy the build output into the plugin's static assets:

```bash
rm -rf ../ots_arcgis_feed/ots_arcgis_feed/ui
cp -r dist/ ../ots_arcgis_feed/ots_arcgis_feed/ui
```

Then rebuild the wheel to include the updated UI.

## Architecture

```
ArcGIS FeatureServer → arcgis_client.py → feed_manager.py → RabbitMQ → ATAK clients
```

| Module | Role |
|--------|------|
| `app.py` | Plugin entry point — registers scheduler jobs, exposes REST API |
| `arcgis_client.py` | HTTP client for ArcGIS REST API; parses feature JSON |
| `feed_manager.py` | Core logic — fetch, build CoT XML, publish to RabbitMQ, track marker lifecycle |
| `cot_generator.py` | CoT XML element builders |
| `default_config.py` | Default configuration and validation |

### Key Technologies

- **Python 3.10+** / Flask / APScheduler
- **RabbitMQ** (pika) for CoT event distribution
- **ArcGIS REST API** as the data source
- **React + Mantine + Vite** for the management UI

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).
