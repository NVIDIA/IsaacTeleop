# syntax=docker/dockerfile:1
# OAK-D Camera Streamer - ARM (sender only)
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-gi \
    gir1.2-gstreamer-1.0 \
    # USB for OAK-D
    libusb-1.0-0-dev \
    udev \
    # GStreamer (appsrc, h264parse, rtph264pay, udpsink)
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir depthai

# udev rules for OAK-D
RUN echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"' > /etc/udev/rules.d/80-movidius.rules

COPY . /oakd_streamer

COPY --chmod=755 <<'EOF' /usr/local/bin/oakd-entrypoint
#!/bin/bash
set -e
if [ "$(id -u)" -eq 0 ] && command -v udevadm >/dev/null 2>&1; then
    if ! pgrep -x udevd > /dev/null 2>&1; then
        mkdir -p /run/udev
        /lib/systemd/systemd-udevd --daemon 2>/dev/null || true
        udevadm trigger 2>/dev/null || true
        udevadm settle 2>/dev/null || true
        sleep 1
    fi
fi
exec "$@"
EOF

WORKDIR /oakd_streamer
ENTRYPOINT ["/usr/local/bin/oakd-entrypoint"]
CMD ["/bin/bash"]
