#!/usr/bin/env python3

import json
import random
import socket
import struct
import time
import numpy
import bz2
import os
import functools

from PIL import Image

from pixelterm import pixelterm

HOST, PORT    = "172.23.42.29",2342
CMD_LED_DRAW = 18

def resize_image(img, size):
	tw, th = size
	w, h = img.size
	a, b = w/tw, h/th
	f = 1/max(a, b)
	pos = int((tw-w*f)/2), int((th-h*f)/2)
	buf = Image.new('RGBA', (tw, th))
	buf.paste(img.resize((int(w*f), int(h*f))).convert('RGBA'), pos)
	buf2 = Image.new('RGBA', (tw, th), (0, 0, 0, 255))
	return Image.alpha_composite(buf2, buf)

class Display:
	def __init__(self):
		self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		self.size = 56*8, 8*20

	def sendframe(self, frame):
		self.sock.sendto(struct.pack('!HHHHH', CMD_LED_DRAW, 0,
			(56*8*(12*20-8))%65536, 0x627a, 0) + # do. not. fucking. ask.
				bz2.compress(frame), (HOST, PORT))

	@staticmethod
	def do_gamma(im, gamma):
		"""Fast gamma correction with PIL's image.point() method"""
		invert_gamma = 1.0/gamma
		lut = [pow(x/255., invert_gamma) * 255 for x in range(256)]
		lut = lut*4 # need one set of data for each band for RGBA
		im = im.point(lut)
		return im

	@staticmethod
	def encode_image(img, displaysize):
		return numpy.frombuffer(Display.do_gamma(resize_image(img, displaysize), 0.5).convert('1').tobytes(), dtype='1b')

def weightedChoice(choices, default=None):
	acc = 0
	r = random.random()
	for weight, choice in choices:
		if r < (acc + weight):
			return choice
		acc += weight
	return default

class Agent:
	def __init__(self, path: 'pathlib.Path'):
		self.config = json.loads((path / 'agent.json').read_text())
		for ani in self.config['animations'].values():
			for f in ani['frames']:
				branching, exitBranch = f.get('branching'), f.get('exitBranch')
				if 'branching' in f:
					f['next'] = lambda f, idx: weightedChoice(
							[ (b['weight']/100, b['frameIndex']) for b in  f['branching']['branches'] ]
							, default=idx+1)
				elif 'exitBranch' in f:
					f['next'] = lambda f, idx: f['exitBranch']
				else:
					f['next'] = lambda f, idx: idx+1
		self.picmap = Image.open(path / 'map.png')
		self.path   = path
	
	def __call__(self, action):
		print('Playing:', action)
		for frame in self._animate(action):
			print('frame:', frame)
			if 'images_encoded' in frame: # some frames contain branch info and sound, but no images
				yield frame['images_encoded']
			time.sleep(frame['duration']/1000)

	def precalculate_images(self, dsp, termsize):
		for ani in self.config['animations'].values():
			for f in ani['frames']:
				if 'images' in f:
					f['images_encoded'] = self._precalculate_one_image(tuple(f['images'][0]), dsp, termsize)
		self._precalculate_one_image.cache_clear()
	
	@functools.lru_cache(maxsize=None)
	def _precalculate_one_image(self, coords, dsp, termsize):
		img = self.get_image(*coords)
		return ( dsp.encode_image(img, dsp.size) if dsp else None,
			pixelterm.termify_pixels(resize_image(img, termsize)) if termsize else None )
	
	def _animate(self, action):
		anim, idx = self.config['animations'][action]['frames'], 0
		while idx < len(anim):
			yield anim[idx]
			idx = anim[idx]['next'](anim[idx], idx)

	def get_image(self, x, y):
		print('cropbox:', x, y, *self.config['framesize'], 'map:', self.picmap.size)
		tw, th = self.config['framesize']
		return self.picmap.crop((x, y, x+tw, y+th))

	@property
	def animations(self):
		return list(self.config['animations'].keys())

if __name__ == '__main__':
	import argparse, pathlib, sys

	parser = argparse.ArgumentParser()
	parser.add_argument('-l', '--list', action='store_true')
	parser.add_argument('-a', '--agent', default='Clippy')
	parser.add_argument('-e', '--endless', action='store_true')
	parser.add_argument('-d', '--display', action='store_true')
	parser.add_argument('-t', '--terminal', action='store_true')
	parser.add_argument('action', default='Greeting', nargs='?')
	args = parser.parse_args()

	agent_path = pathlib.Path('agents') / args.agent
	if not agent_path.is_dir():
		print('Agent not found. Exiting.')
		sys.exit(1)

	if args.list:
		print('\n'.join(Agent(agent_path).animations))
		sys.exit(0)

	dsp = Display() if args.display else None
	agent = Agent(agent_path)
	tx, ty = os.get_terminal_size()
	termsize = (tx, ty*2) if args.terminal else None
	agent.precalculate_images(dsp, termsize)

	if args.endless:
		while True:
			if random.random() > 0.2:
				for img_dsp, img_term in agent(random.choice(agent.animations)):
					if args.terminal:
						print('\033[H', end='')
						print(pixelterm.termify_pixels(
								resize_image(img, termsize)))
					if args.display:
						dsp.sendframe(img_dsp)
			time.sleep(1)
	else:
		for img_dsp,  img_term in agent(args.action):
			if args.terminal:
				print(pixelterm.termify_pixels(
						resize_image(img, termsize)))
			if args.display:
				dsp.sendframe(img_dsp)
