# Build environment that matches Lambda's OS (AL2023)
FROM public.ecr.aws/amazonlinux/amazonlinux:2023

# Install Chromium + chromedriver + minimal utilities
RUN dnf -y update && \
    dnf -y install chromium chromium-headless chromium-chromedriver \
                   glibc-langpack-en unzip zip findutils && \
    dnf clean all

# Prepare /opt layout for a Lambda Layer
# (We copy binaries and any linked shared libs we need.)
RUN mkdir -p /layer/opt/chromium /layer/opt/lib

# Copy chromium & chromedriver
# NOTE: paths may vary by distro build; these two are typical.
RUN cp /usr/lib64/chromium-browser/chromium-browser /layer/opt/chromium/chrome || true && \
    cp /usr/bin/chromium-browser /layer/opt/chromium/chrome || true && \
    cp /usr/bin/chromedriver /layer/opt/chromedriver

# Collect core linked libs for the chrome binary (best-effort)
# This pulls the library paths reported by ldd and copies them to /opt/lib
RUN set -e; \
    BIN="/layer/opt/chromium/chrome"; \
    if [ -f "$BIN" ]; then \
      ldd "$BIN" | awk '{print $3}' | grep -E '^/' | xargs -I{} cp -v --parents {} /layer; \
    fi

# Final layer zip location
WORKDIR /layer
RUN zip -r9 /chromium-layer.zip .
