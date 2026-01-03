"""Generate a custom icon for ulogger."""
from PIL import Image, ImageDraw, ImageFont
import os

# Create multiple sizes for the .ico file
sizes = [256, 128, 64, 48, 32, 16]
images = []

for size in sizes:
    # Create image with transparent background
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Calculate proportions
    margin = size // 10
    inner_size = size - 2 * margin

    # Draw a terminal window background (dark blue-gray)
    terminal_color = (30, 40, 50, 255)
    border_radius = size // 8
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=border_radius,
        fill=terminal_color,
        outline=(60, 80, 100, 255),
        width=max(1, size // 64)
    )

    # Draw terminal title bar
    title_height = size // 8
    draw.rounded_rectangle(
        [margin, margin, size - margin, margin + title_height],
        radius=border_radius,
        fill=(50, 60, 70, 255)
    )

    # Draw terminal buttons (red, yellow, green circles)
    button_size = max(2, size // 32)
    button_y = margin + title_height // 2
    button_spacing = size // 16

    # Red button
    draw.ellipse(
        [margin + button_spacing, button_y - button_size,
         margin + button_spacing + button_size * 2, button_y + button_size],
        fill=(255, 95, 86, 255)
    )

    # Yellow button
    draw.ellipse(
        [margin + button_spacing * 2 + button_size * 2, button_y - button_size,
         margin + button_spacing * 2 + button_size * 4, button_y + button_size],
        fill=(255, 189, 46, 255)
    )

    # Green button
    draw.ellipse(
        [margin + button_spacing * 3 + button_size * 4, button_y - button_size,
         margin + button_spacing * 3 + button_size * 6, button_y + button_size],
        fill=(39, 201, 63, 255)
    )

    # Draw text lines representing log output
    text_start_y = margin + title_height + size // 10
    line_height = size // 12
    num_lines = min(5, (size - text_start_y - margin) // line_height)

    # Color-coded log lines (different colors for different log levels)
    colors = [
        (255, 85, 85, 255),   # Red - ERROR
        (255, 200, 87, 255),  # Yellow - WARN
        (100, 255, 150, 255), # Green - INFO
        (100, 200, 255, 255), # Blue - DEBUG
        (180, 180, 180, 255)  # Gray - TRACE
    ]

    for i in range(num_lines):
        y = text_start_y + i * line_height
        line_width = inner_size - size // 5
        line_thickness = max(1, size // 48)

        # Draw line with varying widths
        width_variation = (i % 3) * size // 10
        color = colors[i % len(colors)]

        draw.rectangle(
            [margin + size // 10, y,
             margin + size // 10 + line_width - width_variation, y + line_thickness],
            fill=color
        )

    # Draw a small "µ" symbol in bottom right corner
    if size >= 32:
        try:
            font_size = size // 4
            # Try to use a font, fall back to default if not available
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except:
                font = ImageFont.load_default()

            # Draw µ symbol
            mu_text = "µ"
            # Get text size using textbbox
            bbox = draw.textbbox((0, 0), mu_text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            text_x = size - margin - text_width - size // 20
            text_y = size - margin - text_height - size // 20

            # Draw with slight shadow for depth
            draw.text((text_x + 1, text_y + 1), mu_text, fill=(0, 0, 0, 128), font=font)
            draw.text((text_x, text_y), mu_text, fill=(100, 200, 255, 255), font=font)
        except:
            pass  # Skip text if font rendering fails

    images.append(img)

# Save as .ico file
output_path = 'ulogger.ico'
images[0].save(
    output_path,
    format='ICO',
    sizes=[(s, s) for s in sizes]
)

print(f"✓ Icon created: {output_path}")
print(f"  Sizes: {', '.join(f'{s}x{s}' for s in sizes)}")
