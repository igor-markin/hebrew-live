"""Local inference: disable ONNX's native uploader before any runtime import."""
import os
os.environ['ORT_DISABLE_TELEMETRY'] = '1'
