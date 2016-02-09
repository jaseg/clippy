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
import contextlib
import math

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
		pl = struct.pack('!HHHHH', CMD_LED_DRAW, 0, 0, 0x627a, 0) + bz2.compress(frame)
		self.sock.sendto(pl, (HOST, PORT))
#		for i in range(100):
#			time.sleep(0.0001)
		self.sock.sendto(pl, (HOST, PORT))

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
				if 'exitBranch' in f:
					f['next'] = lambda f, idx: f['exitBranch']
				elif 'branching' in f:
					f['next'] = lambda f, idx: weightedChoice(
							[ (b['weight']/100, b['frameIndex']) for b in  f['branching']['branches'] ]
							, default=idx+1)
				else:
					f['next'] = lambda f, idx: idx+1
		self.picmap = Image.open(path / 'map.png')
		self.path   = path
	
	def __call__(self, action):
		for frame in self._animate(action):
#			print('frame:', frame)
			if 'images_encoded' in frame: # some frames contain branch info and sound, but no images
				yield frame['images_encoded']
			time.sleep(frame['duration']/1000)

	def precalculate_images(self, dsp, termsize):
		print('\033[93mPrecalculating images\033[0m')
		total = sum(1 for ani in self.config['animations'].values() for f in ani['frames'] if 'images' in f)
		i = 0
		for ani in self.config['animations'].values():
			for f in ani['frames']:
				if 'images' in f:
					print(('(\033[38;5;245m{: '+str(1+int(math.log10(total)))+'}/{}\033[0m) ').format(i, total), end='')
					i += 1
					f['images_encoded'] = self._precalculate_one_image(tuple(f['images'][0]), dsp, termsize)
					print()
		print('\033[93mdone.\033[0m')
		self._precalculate_one_image.cache_clear()
	
	@functools.lru_cache(maxsize=None)
	def _precalculate_one_image(self, coords, dsp, termsize):
		img = self._get_image(*coords)
		return ( dsp.encode_image(img, dsp.size) if dsp else None,
			pixelterm.termify_pixels(resize_image(img, termsize)) if termsize else None )
	
	def _animate(self, action):
		anim, idx = self.config['animations'][action]['frames'], 0
		while idx < len(anim):
			yield anim[idx]
			idx = anim[idx]['next'](anim[idx], idx)

	def _get_image(self, x, y):
		print('\033[38;5;96mcropbox:\033[0m {:04} {:04} {:04} {:04} \033[38;5;96mmap:\033[0m {:04} {:04}'.format(
			x, y, *self.config['framesize'], *self.picmap.size), end='')
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
	parser.add_argument('-x', '--termsize', type=str)
	parser.add_argument('-s', '--socket', action='store_true')
	parser.add_argument('-b', '--bind', type=str, default='0.0.0.0:2342')
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
	if args.socket:
		tx, ty = (args.termsize or '60x30').split('x')
		tx, ty = int(tx), int(ty)
	elif args.terminal:
		tx, ty = args.termsize.split('x') or os.get_terminal_size()
		tx, ty = int(tx), int(ty)
	termsize = (tx, ty*2) if args.terminal or args.socket else None
	agent.precalculate_images(dsp, termsize)

	if args.socket:
		import socketserver
		class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
			pass
		class ClippyRequestHandler(socketserver.BaseRequestHandler):
			def handle(self):
				with contextlib.suppress(BrokenPipeError):
					while True:
						action = random.choice(agent.animations)
						print('[\033[38;5;245m{}\033[0m] Playing: {}'.format(self.client_address[0], action))
						for _img_dsp, img_term in agent(action):
							self.request.sendall(b'\033[H'+img_term.encode())
		host, port = args.bind.split(':')
		port = int(port)
		server = ThreadedTCPServer((host, port), ClippyRequestHandler)
		server.serve_forever()
	elif args.endless:
		while True:
			if random.random() > 0.2:
				action = random.choice(agent.animations)
				print('Playing:', action)
				for img_dsp, img_term in agent(action):
					if args.terminal:
						print('\033[H'+img_term)
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
