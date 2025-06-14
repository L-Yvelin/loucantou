#!/bin/bash

# Image Optimization Script with Symlink Support
# Version 2.1 - Handles symbolic links and provides verbose output

# Check dependencies
if ! command -v convert &> /dev/null; then
    echo "Error: ImageMagick is not installed."
    exit 1
fi

# Validate input
if [ $# -lt 2 ]; then
    echo "Usage: $0 <source_folder> <resolution1> [resolution2 ...]"
    exit 1
fi

SOURCE_DIR="$1"
shift
RESOLUTIONS=("$@")

# Create optimized folder
OPT_DIR="${SOURCE_DIR}/optimized"
mkdir -p "$OPT_DIR"

# Build find command with proper quoting and symlink following
find_args=()
for format in jpg jpeg png gif bmp tiff webp; do
    find_args+=(-iname "*.${format}" -o)
done
# Remove the last -o
unset 'find_args[${#find_args[@]}-1]'

echo "Starting image optimization:"
echo "  Source:      $SOURCE_DIR"
echo "  Destination: $OPT_DIR"
echo "  Resolutions: ${RESOLUTIONS[*]}"
echo ""
echo "Debug: Find command will be:"
echo "find -L \"$SOURCE_DIR\" -type f \( ${find_args[@]} \)"
echo ""

# Process all images (including following symlinks with -L)
total_count=0
processed_count=0

while IFS= read -r -d $'\0' img; do
    ((total_count++))
    
    # Get real path if this is a symlink
    if [ -L "$img" ]; then
        real_path=$(readlink -f "$img")
        echo "Found symlink: $img -> $real_path"
    else
        real_path="$img"
    fi
    
    # Verify the file exists and is readable
    if [ ! -f "$real_path" ]; then
        echo "Warning: Target does not exist: $img -> $real_path"
        continue
    fi
    
    # Get relative path (handles paths with spaces)
    rel_path="${img#$SOURCE_DIR/}"
    rel_path="${rel_path#/}" # Remove leading slash if present
    
    # Create destination directory
    dest_dir="${OPT_DIR}/$(dirname "$rel_path")"
    mkdir -p "$dest_dir"
    
    # Process file
    filename=$(basename -- "$rel_path")
    extension="${filename##*.}"
    filename_noext="${filename%.*}"
    
    # Generate WebP versions for each resolution
    for res in "${RESOLUTIONS[@]}"; do
        dest_file="${dest_dir}/${filename_noext}-${res}.webp"
        
        if [ ! -f "$dest_file" ]; then
            echo "Converting: ${rel_path} -> ${res}w WebP"
            if ! convert "$real_path" -resize "${res}x" -quality 85 -define webp:lossless=false -strip "$dest_file"; then
                echo "Error: Failed to convert $real_path"
                rm -f "$dest_file" 2>/dev/null
                continue
            fi
            ((processed_count++))
        else
            echo "Skipping existing: ${dest_file}"
        fi
    done
done < <(find -L "$SOURCE_DIR" -type f \( "${find_args[@]}" \) -print0)

echo ""
echo "Optimization complete!"
echo "  Total images found:    $total_count"
echo "  WebP files generated:  $processed_count"
echo "  Total resolutions:     ${#RESOLUTIONS[@]} per image"
echo "  Total output files:    $(( total_count * ${#RESOLUTIONS[@]} ))"