"""Poster policy constants shared by providers, validation and reports."""

POSTER_TITLE = "AI 免费资源雷达日报"
POSTER_NOTICE = "数据以官方页面为准"
POSTER_PROVIDER = "openai"
POSTER_MODEL = "gpt-image-2"
OPENCLAW_POSTER_PROVIDER = "openclaw"
OPENCLAW_POSTER_MODEL = "zai/cogview-3-flash"
POSTER_QUALITY = "medium"
POSTER_REQUEST_SIZE = "1088x1440"
POSTER_WIDTH = 1080
POSTER_HEIGHT = 1440
MAX_POSTER_ATTEMPTS_PER_DAY = 3
MAX_IMAGE_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_PIXELS = 32 * 1024 * 1024
KEYCHAIN_SERVICE = "ai-resource-radar.openai"
KEYCHAIN_ACCOUNT = "default"
OPENAI_IMAGE_ENDPOINT = "https://api.openai.com/v1/images/generations"
OPENCLAW_BINARY_ENV = "AI_RADAR_OPENCLAW_BIN"
POSTER_PROVIDER_METADATA = "poster.provider"
POSTER_MODEL_METADATA = "poster.model"
POSTER_ENABLED_METADATA = "poster.enabled"
POSTER_LAST_FAILURE_CODE_METADATA = "poster.last_failure.code"
POSTER_LAST_FAILURE_DATE_METADATA = "poster.last_failure.date"
POSTER_LAST_FAILURE_AT_METADATA = "poster.last_failure.at"
POSTER_ASPECT_RATIO_TOLERANCE = 0.08
POSTER_BENCHMARK_VERSION = "zh-poster-v1"
POSTER_BENCHMARK_CASE_COUNT = 6
POSTER_BENCHMARK_IMAGE_RETENTION_DAYS = 7

__all__ = [name for name in globals() if name.isupper()]
