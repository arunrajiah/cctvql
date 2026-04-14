"""Constants for the cctvQL Home Assistant integration."""

DOMAIN = "cctvql"
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8000
DEFAULT_SCAN_INTERVAL = 30  # seconds

CONF_HOST = "host"
CONF_PORT = "port"
CONF_API_KEY = "api_key"
CONF_SCAN_INTERVAL = "scan_interval"

# Data keys returned by the coordinator
DATA_HEALTH = "health"
DATA_CAMERAS = "cameras"
DATA_CAMERA_HEALTH = "camera_health"
DATA_EVENTS = "events"

# Sensor unique-ID suffixes
SENSOR_CAMERAS_ONLINE = "cameras_online"
SENSOR_CAMERAS_OFFLINE = "cameras_offline"
SENSOR_ADAPTER_STATUS = "adapter_status"
SENSOR_LLM_STATUS = "llm_status"
SENSOR_EVENTS_RECENT = "events_recent"

# PTZ valid actions
PTZ_ACTIONS = ("left", "right", "up", "down", "zoom_in", "zoom_out", "home", "preset")
