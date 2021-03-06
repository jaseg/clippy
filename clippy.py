#!/usr/bin/env python3

import json
import random
import socket
import struct
import time
import numpy as np
import bz2
import os
import functools
import contextlib
import math
import threading

from PIL import Image

from pixelterm import pixelterm

import pxf
from misc import resize_image

HOST, PORT    = "172.23.42.29",2342
CMD_LED_DRAW = 18

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

class Display:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.size = 56*8, 8*20

    def sendframe(self, frame):
        pl = struct.pack('!HHHHH', CMD_LED_DRAW, 0, 0, 0x627a, 0) + bz2.compress(frame)
        self.sock.sendto(pl, (HOST, PORT))
#       for i in range(100):
#           time.sleep(0.0001)
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
        return np.frombuffer(Display.do_gamma(resize_image(img, displaysize), 0.5).convert('1').tobytes(), dtype='1b')

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
    
    def __call__(self, action, sleep=True):
        for frame in self._animate(action):
#           print('frame:', frame)
            if 'images_encoded' in frame: # some frames contain branch info and sound, but no images
                yield frame['images_encoded']
            if sleep:
                time.sleep(frame['duration']/1000)

    def precalculate_images(self, pf, dsp, termsize):
        print('\033[93mPrecalculating images\033[0m', flush=True)
        total = sum(1 for ani in self.config['animations'].values() for f in ani['frames'] if 'images' in f)
        i = 0
        for ani in self.config['animations'].values():
            for f in ani['frames']:
                if 'images' in f:
                    print(('(\033[38;5;245m{: '+str(1+int(math.log10(total)))+'}/{}\033[0m)').format(i, total), end='', flush=True)
                    i += 1
                    f['images_encoded'] = self._precalculate_one_image(tuple(f['images'][0]), pf, dsp, termsize)
                    print(flush=True)
        print('\033[93mdone.\033[0m', flush=True)
        self._precalculate_one_image.cache_clear()
    
    @functools.lru_cache(maxsize=None)
    def _precalculate_one_image(self, coords, pf, dsp, termsize):
        img = self._get_image(*coords)
        return ( pf.encode_image(img) if pf else None,
            dsp.encode_image(img, dsp.size) if dsp else None,
            pixelterm.termify_pixels(resize_image(img, termsize)) if termsize else None )
    
    def _animate(self, action):
        anim, idx = self.config['animations'][action]['frames'], 0
        while idx < len(anim):
            yield anim[idx]
            idx = anim[idx]['next'](anim[idx], idx)

    def _get_image(self, x, y):
        print('\033[38;5;96mcropbox:\033[0m {:04} {:04} {:04} {:04} \033[38;5;96mmap:\033[0m {:04} {:04}'.format(
            x, y, *self.config['framesize'], *self.picmap.size), end='', flush=True)
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
    parser.add_argument('-i', '--interactive', action='store_true')
    parser.add_argument('-w', '--wait', type=int, default=120)
    parser.add_argument('-p', '--pixelflut', type=str)
    parser.add_argument('-t', '--terminal', action='store_true')
    parser.add_argument('-x', '--termsize', type=str)
    parser.add_argument('-s', '--socket', action='store_true', help='Listen on TCP socket (telnet-compatible)')
    parser.add_argument('-k', '--kill-after', type=int, default=60, help='Kill TCP connections after {kill_after} seconds')
    parser.add_argument('-n', '--nosleep', action='store_true')
    parser.add_argument('-b', '--bind', type=str, default='0.0.0.0:2342')
    parser.add_argument('action', default='Greeting', nargs='?')
    args = parser.parse_args()

    agent_paths = []
    for agent in args.agent.split(','):
        agent_path = pathlib.Path('agents') / agent
        if not agent_path.is_dir():
            print('Agent "{}" not found. Exiting.'.format(agent), flush=True)
            sys.exit(1)
        agent_paths.append(agent_path)

    if args.list:
        print('\n'.join(Agent(agent_path).animations), flush=True)
        sys.exit(0)

    dsp = Display() if args.display else None

    if args.pixelflut:
        target, *params = args.pixelflut.split('@')
        host, port = target.split(':')
        port = int(port)
        x, y, *_r = params[0].split(',') if params else (0, 0, None)
        w, h, reps = _r if _r else (320, 240)
        x, y, w, h, reps = map(int, (x, y, w, h, reps))
        pf = pxf.Pixelflut(host, port, x, y, w, h, reps) if args.pixelflut else None
    else:
        pf = None
    agents = []
    for path in agent_paths:
        agent = Agent(path)
        if args.socket:
            tx, ty = (args.termsize or '60x30').split('x')
            tx, ty = int(tx), int(ty)
        elif args.terminal:
            tx, ty = args.termsize.split('x') or os.get_terminal_size()
            tx, ty = int(tx), int(ty)
        termsize = (tx, ty*2) if args.terminal or args.socket else None
        agent.precalculate_images(pf, dsp, termsize)
        agents.append(agent)

    runlock = threading.Lock()
    ts = time.time()
    if args.interactive:
        from tkinter import *

        def recalc_size(delta):
            global runlock
            with runlock:
                print('resetting', flush=True)
                pf.reset_images()
                pf.w += delta
                pf.h += delta
                print('recalcing', flush=True)
                for agent in Agents:
                    agent.precalculate_images(pf, dsp, termsize)

        def keyfunc(ev):
            global ts
            ch = ev.char
            if ch == '+':
                recalc_size(50)
            elif ch == '-':
                recalc_size(-50)
            if ch == 'w':
                pf.y -= 10
            elif ch == 'a':
                pf.x -= 10
            elif ch == 's':
                pf.y += 10
            elif ch == 'd':
                pf.x += 10
            elif ch == 'e':
                pf.reps += 1
            elif ch == 'q':
                if pf.reps > 1:
                    pf.reps -= 1
            elif ch == 'n':
                ts = time.time() - args.wait - 1

        def tkrun():
            tkr = Tk()
            tkf = Frame(tkr, width=100, height=100)
            tkf.bind('<Key>', keyfunc)
            tkf.pack()
            tkf.focus_set()
            tkr.mainloop()

        tkrunner = threading.Thread(target=tkrun, daemon=True)
        tkrunner.start()
    
    if args.socket:
        import socketserver
        class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
            pass
        class ClippyRequestHandler(socketserver.BaseRequestHandler):
            def handle(self):
                with contextlib.suppress(BrokenPipeError):
                    start = time.time()
                    srcaddr, srcport = self.client_address
                    print(f'Connection from {srcaddr}:{srcport}')

                    agent = random.choice(agents)
                    while True:
                        action = random.choice(agent.animations)
                        #print('[\033[38;5;245m{}\033[0m] Playing: {}'.format(self.client_address[0], action), flush=True)
                        for _img_pf, _img_dsp, img_term in agent(action):
                            if time.time() - start > args.kill_after:
                                return
                            self.request.sendall(b'\033[H'+img_term.encode())
        host, port = args.bind.split(':')
        port = int(port)
        server = ThreadedTCPServer((host, port), ClippyRequestHandler)
        server.serve_forever()
    elif args.endless:
        while True:
            print('Starting', ts, flush=True)
            for agent in agents:
                while time.time() - ts < args.wait:
                    if random.random() > 0.2:
                        action = random.choice(agent.animations)
                        print('Playing:', action, flush=True)
                        for img_pf, img_dsp, img_term in agent(action, not args.nosleep):
                            with runlock:
                                if args.terminal:
                                    print('\033[H'+img_term, flush=True)
                                if args.display:
                                    dsp.sendframe(img_dsp)
                                if args.pixelflut:
                                    pf.sendframe(img_pf)
                                if time.time() - ts > args.wait:
                                    print('Force-advance', ts, flush=True)
                                    break
                    if not args.nosleep:
                        time.sleep(1)
                print('Advancing', ts, flush=True)
                ts = time.time()
    else:
        for img_pf, img_dsp, img_term in agents[0](args.action, not args.nosleep):
            if args.terminal:
                print(img_term, flush=True) #pixelterm.termify_pixels(
                        #resize_image(img, termsize)))
            if args.display:
                dsp.sendframe(img_dsp)
            if args.pixelflut:
                pf.sendframe(img_pf)

