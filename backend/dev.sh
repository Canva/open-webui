export CORS_ALLOW_ORIGIN="http://localhost:5173;http://localhost:5080"
PORT="${PORT:-5080}"
uvicorn open_webui.main:app --port $PORT --host 0.0.0.0 --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" --reload
