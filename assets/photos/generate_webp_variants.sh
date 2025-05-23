#!/bin/bash

# WebP variant generator for photos directory
sizes=(400 800 1200 1920)

echo "Starting WebP generation for all images in photos directory..."

find "." -type f \( -iname '*.png' -o -iname '*.jpg' \) | while read -r img; do
    # Skip if it's the script itself
    if [[ "$img" == *"generate_webp_variants.sh"* ]]; then
        continue
    fi
    
    base="${img%.*}"
    name=$(basename "$base")
    dir=$(dirname "$img")
    
    # Create webp directory in the same location as the image
    webp_dir="$dir/webp"
    mkdir -p "$webp_dir"
    
    echo "Processing: $img"
    
    for size in "${sizes[@]}"; do
        output_file="$webp_dir/${name}-${size}.webp"
        convert "$img" -resize ${size}x -quality 85 "$output_file"
        echo "  → Generated: $output_file"
    done
    
    echo "✅ Completed: $img"
    echo ""
done

echo "🎉 All WebP variants generated!"
echo ""
echo "Generated structure:"
find . -name "webp" -type d | while read -r webp_dir; do
    echo "$webp_dir/"
    ls -la "$webp_dir" | grep -v "^total" | sed 's/^/  /'
done