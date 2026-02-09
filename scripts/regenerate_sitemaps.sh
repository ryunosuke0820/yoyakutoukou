#!/bin/bash

# SD6-10 Sitemap Regeneration Script
# Run this from /home/aoxacgmk/

# List of Subdomains to process (SD6-10)
SITES=(
    "sd06-hitozuma"
    "sd07-oneesan"
    "sd08-jukujo"
    "sd09-iyashi"
    "sd10-otona"
)

echo "=== Starting Sitemap Regeneration for SD6-10 ==="

for SITE in "${SITES[@]}"; do
    SITE_PATH="/home/aoxacgmk/public_html/$SITE.av-kantei.com"
    
    echo ""
    echo "--- Processing: $SITE ---"
    
    if [ ! -d "$SITE_PATH" ]; then
        echo "Warning: Directory $SITE_PATH not found. Skipping."
        continue
    fi

    # 1. Flush Rewrite Rules (Essential for fixing 404s on sitemap.xml)
    echo "Flushing rewrite rules..."
    wp rewrite flush --path=$SITE_PATH --quiet
    
    # 2. Check for common SEO/Sitemap plugins and attempt regeneration
    
    # Google XML Sitemaps (Auctollo)
    if wp plugin is-active google-sitemap-generator --path=$SITE_PATH --quiet; then
        echo "Detected: Google XML Sitemaps"
        # Often just needs a rewrite flush, but we can try to trigger a rebuild if CLI supported
        # CLI support is limited, but flushing rules usually fixes it.
    fi

    # Yoast SEO
    if wp plugin is-active wordpress-seo --path=$SITE_PATH --quiet; then
        echo "Detected: Yoast SEO"
        # Triggers sitemap cache clear
        wp option update wpseo_sitemap_cache_validator "$(date +%s)" --path=$SITE_PATH --quiet
    fi

    # All in One SEO
    if wp plugin is-active all-in-one-seo-pack --path=$SITE_PATH --quiet; then
        echo "Detected: All in One SEO"
        # AIOSEO sitemap regeneration often happens on visit, but clearing cache helps
    fi

    echo "Done: $SITE"
done

echo ""
echo "=== Sitemap Regeneration Completed ==="
echo "Please check https://[subdomain].av-kantei.com/sitemap.xml for each site."
