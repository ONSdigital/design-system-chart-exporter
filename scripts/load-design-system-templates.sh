#!/usr/bin/env bash
#
# Downloads and vendors the ONS Design System templates and assets into
# templates/, so the render context needs ZERO network access (SSRF
# mitigation). Adapted from the spike's loader script, with its stale
# Wagtail path (cms/jinja2) corrected and asset vendoring added.
#
# Usage: load-design-system-templates.sh {TAG_NAME}
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${DIR}/.." || exit

if [ $# -eq 0 ] || [ "$1" == "" ]; then
    echo "Usage: load-design-system-templates.sh {TAG_NAME}"
    exit 1
fi
TAG_NAME="$1"

REPO_NAME="onsdigital/design-system"
DOWNLOAD_URL="https://github.com/${REPO_NAME}/releases/download/${TAG_NAME}/templates.zip"
CDN_URL=${CDN_URL:-"https://cdn.ons.gov.uk"}
CDN_BASE="${CDN_URL}/sdc/design-system/${TAG_NAME}"

TEMP_DIR=$(mktemp -d)
trap 'rm -rf "${TEMP_DIR}"' EXIT

#
# Jinja templates (components + layout macros)
#
echo "Fetching ${DOWNLOAD_URL}"
curl --silent --fail -L --url "${DOWNLOAD_URL}" --output "${TEMP_DIR}/templates.zip"
unzip -q -o "${TEMP_DIR}/templates.zip" -d "${TEMP_DIR}"

rm -rf ./templates/components ./templates/layout
mkdir -p ./templates
mv -f "${TEMP_DIR}/templates/components" "${TEMP_DIR}/templates/layout" ./templates/
echo "Saved Design System templates to 'templates/components' and 'templates/layout'"

#
# Assets: CSS (with fonts inlined as data: URIs) and the JS bundle, which
# includes Highcharts and the chart bootstrapping code
#
mkdir -p ./templates/assets
echo "Fetching CSS and JS bundles from ${CDN_BASE}"
curl --silent --fail --compressed "${CDN_BASE}/css/main.css" --output "${TEMP_DIR}/main.css"
curl --silent --fail --compressed "${CDN_BASE}/scripts/main.js" --output "./templates/assets/main.js"

mkdir -p "${TEMP_DIR}/fonts"
grep -o 'url("\.\./fonts/[^"]*")' "${TEMP_DIR}/main.css" | sed 's|url("../fonts/||;s|")||' | sort -u |
    while read -r FONT_FILE; do
        echo "Fetching font ${FONT_FILE}"
        curl --silent --fail "${CDN_BASE}/fonts/${FONT_FILE}" --output "${TEMP_DIR}/fonts/${FONT_FILE}"
    done

python3 scripts/inline_css_fonts.py "${TEMP_DIR}/main.css" "${TEMP_DIR}/fonts" "./templates/assets/main.css"
echo "Saved Design System assets to 'templates/assets'"
