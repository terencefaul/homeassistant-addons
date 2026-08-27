#!/usr/bin/with-contenv bashio
set -e

DATA=/data
mkdir -p "${DATA}/branding" /run/nginx

# Generate the real-IP snippet from options rather than patching a checked-in
# config file. The reference add-on sed-patched its own nginx config at boot
# (run.sh:8-12); a generated include is the same flexibility without editing a
# file that is under version control.
CIDR="$(bashio::config 'trusted_proxy_cidr')"
{
  echo "# generated at boot from the trusted_proxy_cidr option"
  echo "real_ip_header CF-Connecting-IP;"
  echo "real_ip_recursive on;"
  if [ -n "${CIDR}" ] && [ "${CIDR}" != "null" ]; then
    echo "set_real_ip_from ${CIDR};"
  fi
} > /etc/nginx/real_ip.conf

bashio::log.info "Trusted proxy range: ${CIDR:-<none>}"

nginx -t

# Start the application FIRST and wait for it to answer.
#
# nginx serves static files the instant it starts, but the API takes a few
# seconds to come up. Starting nginx first leaves a window where the guest page
# loads and every action returns 502 -- which reads to a visitor as "the gate is
# broken" and to you as an intermittent fault. Better to not answer at all than
# to answer wrongly.
cd /app
python3 -m addon.main &
APP_PID=$!

for _ in $(seq 1 60); do
  if nc -z 127.0.0.1 8080 2>/dev/null; then
    break
  fi
  if ! kill -0 "${APP_PID}" 2>/dev/null; then
    bashio::log.error "Application exited during startup"
    exit 1
  fi
  sleep 0.5
done

if ! nc -z 127.0.0.1 8080 2>/dev/null; then
  bashio::log.error "Application did not start listening within 30s"
  kill "${APP_PID}" 2>/dev/null || true
  exit 1
fi

bashio::log.info "Application ready; starting nginx"
nginx

# Exit with the application, so Supervisor restarts the add-on if it dies
# rather than leaving nginx serving a page whose API is gone.
wait "${APP_PID}"
