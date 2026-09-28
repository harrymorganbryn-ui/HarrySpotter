"""Make logo.ico (Windows icon) from the Mac logo.icns, falling back to lab_logo.png."""
from PIL import Image

sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
try:
    img = Image.open("logo.icns")
    img.load()
    source = "logo.icns"
except Exception:
    img = Image.open("lab_logo.png")
    source = "lab_logo.png"
img = img.convert("RGBA")
side = max(img.size)
square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
square.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
square.save("logo.ico", sizes=sizes)
print(f"logo.ico made from {source}")
