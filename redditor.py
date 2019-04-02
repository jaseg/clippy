#!/usr/bin/env python3

import json
import random
import socket
import struct
import time
import bz2
import os
import functools
import contextlib
import math
import ctypes
import io
from urllib.parse import *

import numpy as np
from PIL import Image
import praw
import bs4
import requests

from pixelterm import pixelterm

import pxf

def lesearchiter(term):
	last = None
	print('Searching term="{}", [initial]'.format(term))
	for s in r.search(term):
		last = s
		yield s
	while True:
		print('Searching term="{}", after={}'.format(term, last.fullname))
		for s in r.search(term, limit=100, after=last.fullname):
			last = s
			yield s

if __name__ == '__main__':
	import argparse, pathlib, sys

	parser = argparse.ArgumentParser()
	parser.add_argument('-p', '--pixelflut', type=str, default='94.45.232.225:1234')
	parser.add_argument('term')
	args = parser.parse_args()

	target, *params = args.pixelflut.split('@')
	host, port = target.split(':')
	port = int(port)
	x, y, *_r = params[0].split(',') if params else (0, 0, None)
	w, h, reps = _r if _r else (320, 240)
	x, y, w, h, reps = map(int, (x, y, w, h, reps))
	pf = pxf.Pixelflut(host, port, x, y, w, h, reps) if args.pixelflut else None

	r = praw.Reddit('Pixelflut search test by /u/jaseg')
	r.refresh_access_information()

	terms = args.term.split(',')
	print('Search terms:', terms)

	imgnum = 0
	for s in lesearchiter(random.choice(terms)):
		try:
			url = s.url
#			print(url)
			if s.stickied:
#				print(' → stickied')
				continue
			if s.is_self:
#				print(' → self')
				continue
			stripped_down = urlunparse(urlparse(url)[:3] + (None,None,None))
			l = stripped_down.lower()
			if any(l.endswith(e) for e in ('.gif')):
#				print(' → GIF filter')
				continue
			rq = requests.get(url)
			if not rq.headers.get('content-type', '').startswith('image/'):
				soup = bs4.BeautifulSoup(rq.text, 'lxml')
				img = soup.find('img')
				newurl = img.attrs['src']
				if newurl.startswith('//'):
					newurl = 'http:'+newurl
#				print('Fetching', newurl)
				rq = requests.get(newurl)
			if not rq.headers.get('content-type', '').startswith('image/'):
#				print(' → image filter:', rq.headers.get('content-type'))
				continue

			with open('/tmp/testdir/img_{}'.format(imgnum), 'wb') as f:
				f.write(rq.content)
			imgnum += 1
			if imgnum >= 20:
				sys.exit(0)
#				bio = io.BytesIO()
#				bio.write(rq.content)
#				bio.seek(0)
#				pimg = Image.open(bio)
#				pf.encode_image(pimg, idx=0)
#				pf.sendframe(0)
		except Exception as e:
			print(' → Exception:', e)

