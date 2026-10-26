#!/bin/bash
set -Eeuo pipefail
bootstrap_id='@@BOOTSTRAP_SHA256@@'
mkdir -p /etc/arcium-worker
rm -f /etc/arcium-worker/bootstrap-failed
trap 'printf "%s\n" "$bootstrap_id" > /etc/arcium-worker/bootstrap-failed' ERR
version_dir=/opt/arcium-worker/nativelink-v1.6.5
mount_unit=$(systemd-escape --path --suffix=mount /var/lib/arcium-worker)

check_service_access() {
  runuser -u arcium-worker -- test -x "$version_dir/nativelink"
  runuser -u arcium-worker -- test -r /etc/arcium-worker/nativelink.json
}

grow_cache() {
  /usr/local/libexec/arcium-check-cache
  local device=/dev/disk/by-id/google-arcium-cache
  test -b "$device"
  test "$(blkid -s TYPE -o value "$device")" = ext4
  if [ "$(blockdev --getsize64 "$device")" -lt @@CACHE_MIN_BYTES@@ ]; then
    echo 'Cache device is undersized; explicitly expand it before using this profile.' >&2
    return 1
  fi
  # With no requested size, resize2fs grows to the verified whole device.
  # It is harmless when already expanded and never reformats retained data.
  resize2fs "$device"
}

wait_for_service() {
  for attempt in {1..60}; do
    if systemctl is-active --quiet arcium-nativelink && \
       curl --fail --silent --max-time 2 http://127.0.0.1:50061/status >/dev/null; then
      return 0
    fi
    sleep 1
  done
  systemctl --no-pager status arcium-nativelink >&2 || true
  return 1
}

# A normal resume only verifies the immutable installation and starts units.
if [ -f /etc/arcium-worker/bootstrap-id ] && \
   [ "$(cat /etc/arcium-worker/bootstrap-id)" = "$bootstrap_id" ]; then
  chmod 755 "$version_dir"
  (cd "$version_dir" && sha256sum --check nativelink.sha256)
  check_service_access
  systemctl start "$mount_unit"
  grow_cache
  systemctl start arcium-nativelink
  wait_for_service
  exit 0
fi

systemctl stop arcium-nativelink.service 2>/dev/null || true
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl python3 coreutils e2fsprogs util-linux \
  libstdc++6 libgcc-s1 zlib1g libtinfo6 libxml2 libzstd1

device=/dev/disk/by-id/google-arcium-cache
test -b "$device"
filesystem=$(blkid -s TYPE -o value "$device" || true)
if [ -z "$filesystem" ]; then
  # Only the explicitly attached arcium-cache data disk may be initialized.
  mkfs.ext4 -F "$device"
elif [ "$filesystem" != ext4 ]; then
  echo "Refusing unexpected cache filesystem: $filesystem" >&2
  exit 1
fi
mkdir -p /var/lib/arcium-worker /etc/arcium-worker /usr/local/libexec
cat > "/etc/systemd/system/$mount_unit" <<'MOUNT'
[Unit]
Description=Arcium worker cache disk
Before=arcium-nativelink.service

[Mount]
What=/dev/disk/by-id/google-arcium-cache
Where=/var/lib/arcium-worker
Type=ext4
Options=defaults,nodev,nosuid
TimeoutSec=90

[Install]
WantedBy=multi-user.target
MOUNT
cat > /usr/local/libexec/arcium-check-cache <<'CHECK'
#!/bin/bash
set -euo pipefail
expected=$(readlink -f /dev/disk/by-id/google-arcium-cache)
actual=$(findmnt --mountpoint /var/lib/arcium-worker --noheadings --output SOURCE)
test -n "$actual"
test "$(readlink -f "$actual")" = "$expected"
CHECK
chmod 755 /usr/local/libexec/arcium-check-cache
systemctl daemon-reload
systemctl enable --now "$mount_unit"
/usr/local/libexec/arcium-check-cache
grow_cache
# Cache data outlives the OS disk. Use a stable service identity, refusing
# collisions instead of silently inheriting another package's account.
if ! getent group arcium-worker >/dev/null; then
  groupadd --gid 45000 arcium-worker
fi
if ! id arcium-worker >/dev/null 2>&1; then
  useradd --no-create-home --no-log-init --uid 45000 --gid arcium-worker --home-dir /var/lib/arcium-worker --shell /usr/sbin/nologin arcium-worker
fi
test "$(id -u arcium-worker)" = 45000
test "$(id -g arcium-worker)" = 45000
owner_value=
if [ -f /var/lib/arcium-worker/.service-owner ] && [ ! -L /var/lib/arcium-worker/.service-owner ]; then
  owner_value=$(cat /var/lib/arcium-worker/.service-owner)
fi
if [ "$owner_value" != 45000:45000 ]; then
  # One-time migration of an older cache with an allocated service UID. Stay
  # on the verified data filesystem and never follow a cached symlink.
  find /var/lib/arcium-worker -xdev -exec chown -h 45000:45000 {} +
  owner_marker=$(mktemp /var/lib/arcium-worker/.owner-XXXXXX)
  printf '%s\n' 45000:45000 > "$owner_marker"
  chown -h 45000:45000 "$owner_marker"
  mv -T -- "$owner_marker" /var/lib/arcium-worker/.service-owner
fi

mkdir -p /opt/arcium-worker
if [ ! -d "$version_dir" ]; then
  staging=$(mktemp -d /opt/arcium-worker/.install-XXXXXX)
  (
    cd "$staging"
    curl --fail --location --retry 3 --output nativelink.tar.gz \
      https://github.com/TraceMachina/nativelink/releases/download/v1.6.5/nativelink-1.6.5-x86_64-unknown-linux-musl.tar.gz
    printf '%s\n' '093d2e0baac5311444762449b703a45b738d570065d2e17c2db1fcf39d8ad051  nativelink.tar.gz' | sha256sum --check -
    tar --extract --gzip --file=nativelink.tar.gz --no-same-owner
    chmod 755 nativelink
    sha256sum nativelink > nativelink.sha256
    rm nativelink.tar.gz
  )
  chmod 755 "$staging"
  mv "$staging" "$version_dir"
fi
chmod 755 "$version_dir"
(cd "$version_dir" && sha256sum --check nativelink.sha256)
cat > /etc/arcium-worker/nativelink.json <<'NATIVELINK_CONFIG'
@@NATIVELINK_CONFIG@@
NATIVELINK_CONFIG
check_service_access
cat > /etc/systemd/system/arcium-nativelink.service <<SERVICE
[Unit]
Description=Arcium NativeLink build worker
After=network-online.target
RequiresMountsFor=/var/lib/arcium-worker
BindsTo=$mount_unit
After=$mount_unit

[Service]
User=arcium-worker
Group=arcium-worker
Environment=RUST_LOG=info
ExecStartPre=/usr/local/libexec/arcium-check-cache
ExecStart=$version_dir/nativelink /etc/arcium-worker/nativelink.json
Restart=on-failure
RestartSec=3
LimitNOFILE=65536
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=/var/lib/arcium-worker
CapabilityBoundingSet=

[Install]
WantedBy=multi-user.target
SERVICE
systemctl daemon-reload
systemctl enable --now arcium-nativelink
wait_for_service
printf '%s\n' "$bootstrap_id" > /etc/arcium-worker/bootstrap-id
