import numpy as np
import ctypes
import time

from misc import resize_image

class Pixelflut:
	def __init__(self, host, port, x, y, w, h, reps):
		self.host, self.port = host.encode(), port
		self.x, self.y = x, y
		self.w, self.h = w, h
		self.reps = reps
		self.dbuf = np.zeros(w*h*4, dtype=np.uint8)
		self.so = ctypes.CDLL('./pixelflut.so')
		self.sock = None
	
	def reset_images(self):
		self.so.reset_images()
	
	def sendframe(self, idx):
		for _ in range(self.reps):
			if self.sock is None:
				while self.sock is None or self.sock < 0:
					time.sleep(1)
					self.sock = self.so.cct(self.host, self.port)
			if self.so.sendframe(self.sock, idx, self.w, self.h, self.x, self.y):
				self.so.discct(self.sock)
				self.sock = None

	def encode_image(self, img, idx=None):
		frame = np.array(resize_image(img, (self.w, self.h), blackbg=False)).reshape(self.w*self.h*4)
		np.copyto(self.dbuf, frame)
		cptr = self.dbuf.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8))
		if idx is None:
			return self.so.store_image(cptr, self.w, self.h)
		else:
			self.so.store_image_idx(cptr, self.w, self.h, idx)
			return None

class Getch:
    def __call__(self):
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch

