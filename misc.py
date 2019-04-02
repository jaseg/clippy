
from PIL import Image

def resize_image(img, size, blackbg=True):
	tw, th = size
	w, h = img.size
	a, b = w/tw, h/th
	f = 1/max(a, b)
	pos = int((tw-w*f)/2), int((th-h*f)/2)
	buf = Image.new('RGBA', (tw, th))
	buf.paste(img.resize((int(w*f), int(h*f))).convert('RGBA'), pos)
	if blackbg:
		buf2 = Image.new('RGBA', (tw, th), (0, 0, 0, 255))
		return Image.alpha_composite(buf2, buf)
	else:
		return buf

