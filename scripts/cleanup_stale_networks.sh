#!/usr/bin/env bash
# cleanup_stale_networks.sh
#
# Recovers from stale Docker network/IPAM allocations left behind by previous
# transcriber3 deployments on Coolify.
#
# Background: the current `docker-compose.yml` does NOT pin a static IP on
# the gateway service and does NOT configure IPAM subnets — Coolify creates
# the network and Docker IPAM auto-assigns the subnet. This script is mainly
# needed to clean up leftover containers and networks from previous deployments
# that may have used static IPs (`172.29.0.2` or `10.99.42.2`) and stuck
# IPAM allocations.
#
# This script:
#   1. Stops and removes any leftover containers from the current Coolify
#      project (looked up by name prefix).
#   2. Removes the project's Compose networks (gateway, edge, data,
#      formatting-control, formatting-egress, transcription-egress) so Docker
#      fully releases their IPAM allocations.
#   3. Reports any other host-wide Docker networks whose subnet overlaps the
#      SUBNET argument (defaults to 10.99.42.0/24, the previous default), so
#      the operator can decide whether to remove them.
#
# Usage:
#   sudo bash scripts/cleanup_stale_networks.sh [PROJECT_NAME] [SUBNET]
#
# Examples:
#   sudo bash scripts/cleanup_stale_networks.sh
#   sudo bash scripts/cleanup_stale_networks.sh rz3pn8ec7zauw1ktok7jlpmj 10.99.42.0/24
#
# Run this on the Coolify host (the machine that runs the Docker daemon), NOT
# inside a container. Requires the docker CLI and root privileges.

set -euo pipefail

PROJECT_NAME="${1:-}"
GATEWAY_SUBNET="${2:-10.99.42.0/24}"

log() { printf '[cleanup] %s\n' "$*"; }
warn() { printf '[cleanup][WARN] %s\n' "$*" >&2; }
err() { printf '[cleanup][ERROR] %s\n' "$*" >&2; }

if ! command -v docker >/dev/null 2>&1; then
  err "docker CLI not found. Run this script on the Coolify host, not inside a container."
  exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
  warn "Not running as root. If docker commands fail, re-run with: sudo bash $0 $*"
fi

# Compose service names defined in docker-compose.yml (used for container lookup
# when no project name is supplied).
SERVICE_NAMES=(
  storage-init
  formatting-storage-init
  postgres
  redis
  migrate
  api
  worker-1 worker-2 worker-3 worker-4 worker-5
  scheduler
  opencode-runtime
  formatting-worker
  formatting-dispatcher
  gateway
)

# Compose network names defined in docker-compose.yml.
NETWORK_NAMES=(
  edge
  gateway
  data
  formatting-control
  formatting-egress
  transcription-egress
)

# Step 1: discover leftover containers.
log "Step 1: discovering leftover containers."
LEFTOVER_CONTAINERS=()
if [[ -n "${PROJECT_NAME}" ]]; then
  # Filter by Coolify/Compose project name prefix.
  while IFS= read -r line; do
    [[ -n "${line}" ]] && LEFTOVER_CONTAINERS+=("${line}")
  done < <(docker ps -a --filter "name=^${PROJECT_NAME}" --format '{{.Names}}')
else
  # No project name supplied: match any container whose name ends with one of
  # the canonical service names (Coolify uses "<project>-<service>-<random>").
  for svc in "${SERVICE_NAMES[@]}"; do
    # Escape hyphens for the grep regex.
    esc_svc="${svc//-/\\-}"
    while IFS= read -r line; do
      [[ -n "${line}" ]] && LEFTOVER_CONTAINERS+=("${line}")
    done < <(docker ps -a --format '{{.Names}}' | grep -E "(^|-)${esc_svc}(-|$)" || true)
  done
fi

if [[ "${#LEFTOVER_CONTAINERS[@]}" -eq 0 ]]; then
  log "No leftover containers found."
else
  log "Found ${#LEFTOVER_CONTAINERS[@]} leftover container(s):"
  for c in "${LEFTOVER_CONTAINERS[@]}"; do printf '  - %s\n' "${c}"; done

  log "Stopping leftover containers (grace 30s)..."
  docker stop --time=30 "${LEFTOVER_CONTAINERS[@]}" >/dev/null 2>&1 || \
    warn "docker stop reported non-zero; continuing."

  log "Removing leftover containers..."
  docker rm -f "${LEFTOVER_CONTAINERS[@]}" >/dev/null 2>&1 || \
    warn "docker rm reported non-zero; continuing."
fi

# Step 2: remove project Compose networks so IPAM is fully released.
log "Step 2: removing project Compose networks (if any)."
for net in "${NETWORK_NAMES[@]}"; do
  # Coolify prefixes Compose networks with the project name (e.g.
  # "rz3pn8ec7zauw1ktok7jlpmj_gateway"). Match both bare and prefixed forms.
  matches=()
  while IFS= read -r line; do
    [[ -n "${line}" ]] && matches+=("${line}")
  done < <(docker network ls --format '{{.Name}}' | grep -E "(^|_)${net}\$" || true)

  if [[ "${#matches[@]}" -eq 0 ]]; then
    log "  network '${net}': not present."
    continue
  fi

  for m in "${matches[@]}"; do
    log "  removing network '${m}'..."
    # Disconnect any remaining endpoints defensively, then delete.
    endpoints=$(docker network inspect "${m}" --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null || true)
    if [[ -n "${endpoints}" ]]; then
      for ep in ${endpoints}; do
        docker network disconnect -f "${m}" "${ep}" >/dev/null 2>&1 || true
      done
    fi
    docker network rm "${m}" >/dev/null 2>&1 || \
      warn "  could not remove network '${m}' (it may still have active endpoints)."
  done
done

# Step 3: scan host-wide Docker networks for subnet overlap with the configured
# GATEWAY_NETWORK_SUBNET.
log "Step 3: scanning host Docker networks for subnet overlap with '${GATEWAY_SUBNET}'."

subnet_to_cidr() {
  # Accept "10.99.42.0/24" or "10.99.42.0/255.255.255.0"; return "10.99.42.0/24".
  python3 - "$1" <<'PY'
import ipaddress, sys
net = ipaddress.ip_network(sys.argv[1], strict=False)
print(f"{net.network_address}/{net.prefixlen}")
PY
}

OVERLAP_FOUND=0
try_target="$(subnet_to_cidr "${GATEWAY_SUBNET}" 2>/dev/null || true)"
if [[ -z "${try_target}" ]]; then
  warn "Could not parse '${GATEWAY_SUBNET}' as a subnet; skipping overlap scan."
  try_target="${GATEWAY_SUBNET}"
fi

while IFS=$'\t' read -r net_name net_subnet; do
  [[ -z "${net_name}" ]] && continue
  cmp_cidr="$(subnet_to_cidr "${net_subnet}" 2>/dev/null || true)"
  if [[ -z "${cmp_cidr}" ]]; then
    continue
  fi
  if python3 - "${try_target}" "${cmp_cidr}" <<'PY'
import ipaddress, sys
a = ipaddress.ip_network(sys.argv[1], strict=False)
b = ipaddress.ip_network(sys.argv[2], strict=False)
sys.exit(0 if a.overlaps(b) else 1)
PY
  then
    warn "  network '${net_name}' uses subnet '${net_subnet}' which overlaps '${GATEWAY_SUBNET}'."
    OVERLAP_FOUND=1
  fi
done < <(docker network ls --format '{{.Name}}' | while read -r n; do
  sub=$(docker network inspect "${n}" --format '{{range .IPAM.Config}}{{.Subnet}} {{end}}' 2>/dev/null | awk '{print $1}')
  printf '%s\t%s\n' "${n}" "${sub:-}"
done)

if [[ "${OVERLAP_FOUND}" -eq 0 ]]; then
  log "No host Docker network overlaps '${GATEWAY_SUBNET}'. Clean to redeploy."
else
  warn "Overlap detected with previously-used subnet '${GATEWAY_SUBNET}'."
  warn "Remove the conflicting networks above before redeploying."
  warn "Note: the current docker-compose.yml no longer uses a static gateway IP"
  warn "or IPAM subnet, so the SUBNET argument only filters overlap detection"
  warn "for leftover networks from previous deployments."
fi

log "Done. You can now trigger a new deployment in Coolify."
log "If the deployment still fails with 'no configured subnet contains IP"
log "address <X>', verify that no GATEWAY_PEER_IP, GATEWAY_NETWORK_SUBNET,"
log "or FORWARDED_ALLOW_IPS environment variables are set in Coolify."
log "Inspect:"
log "  docker network ls"
log "  docker network inspect <network-name>"
log "and remove any lingering network whose Subnet overlaps '${GATEWAY_SUBNET}'."
