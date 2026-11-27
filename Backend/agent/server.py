"""Loopback-only agent. Pairing authorizes one connection, never a cloud account."""
import asyncio
import hmac
import json
import secrets
import time
from datetime import datetime, timezone
from collections import deque
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed
from .protocol import decode
from .tracker import KeystrokeTracker, WindowTracker

DISPLAY = {'development':'editor','terminal':'terminal','browser':'browser',
           'communication':'chat','productivity':'docs'}

class Sensors:
    def __init__(self):
        self.keyboard = None
        self.window = None
        self.camera = None

    def start(self):
        self.keyboard = KeystrokeTracker()
        self.window = WindowTracker()
        self.keyboard.start()

    def set_camera(self, on):
        if on:
            if self.camera is None:
                from ml_models.fatigue_model import FatigueService
                self.camera = FatigueService()
            self.camera.start()
        elif self.camera is not None:
            if not self.camera.stop():
                raise RuntimeError('Camera did not stop')
            self.camera = None

    def stop(self):
        try:
            self.set_camera(False)
        finally:
            if self.keyboard is not None:
                self.keyboard.stop()
                self.keyboard = None
            self.window = None

    def poll(self):
        self.window.update()
        with self.keyboard._lock:
            return self.keyboard.last_press_time

    def sample(self):
        keys = self.keyboard.get_and_reset()
        switches, category = self.window.snapshot_and_reset()
        return dict(keystroke_count=keys, window_switches=switches,
                    idle_seconds=self.keyboard.idle_seconds(30), app_category=category,
                    camera=(self.camera.get_state() or None) if self.camera else None)

class AgentServer:
    def __init__(self, sensors=None, interval=30):
        self.sensors = sensors or Sensors()
        self.interval = interval
        self.owner = None
        self.session = None
        self.camera_on = False
        self.category = 'unknown'
        self.code = None
        self.expires = 0
        self.blocked = False
        self.watch = None
        self.history = deque(maxlen=10)

    def new_code(self):
        self.code = f'{secrets.randbelow(1000000):06d}'
        self.expires = time.monotonic() + 120
        print(f'FLOW pairing code: {self.code} (valid for 120 seconds)', flush=True)

    async def send(self, ws, msg):
        await ws.send(json.dumps(msg, allow_nan=False))

    async def status(self, ws):
        paired = self.owner is ws
        await self.send(ws, dict(type='status', paired=paired,
            behavior_on=paired and self.session is not None,
            camera_on=paired and self.camera_on,
            app_category=DISPLAY.get(self.category,'other') if paired else None,
            version='1.1', session_id=self.session if paired else None))

    async def stop(self):
        self.session = None
        self.camera_on = False
        self.watch = None
        self.category = 'unknown'
        self.history.clear()
        try:
            await asyncio.to_thread(self.sensors.stop)
        except Exception:
            self.blocked = True
            raise

    async def handler(self, ws):
        # Reject other connections while an owner is active. A single pending
        # connection is also enforced by reserving the slot before any await.
        if self.owner is not None or self.blocked or getattr(self,'pending',False):
            await ws.close(1008, 'Agent busy'); return
        self.pending = True
        try:
            await self.status(ws)
            # One attempt per connection; rotate code after failure/disconnect.
            if time.monotonic() >= self.expires:
                self.new_code()
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(.01,self.expires-time.monotonic()))
                msg = decode(raw)
                if time.monotonic() >= self.expires:
                    raise ValueError('Expired pairing')
                if msg['type'] != 'get_status':
                    break
                await self.status(ws)
            if (msg['type'] != 'pair' or time.monotonic() > self.expires or
                    not hmac.compare_digest(msg['code'].encode(), self.code.encode())):
                await ws.close(1008,'Pairing failed'); return
            self.owner = ws
            self.code = None
            await self.status(ws)
            # Serialize sensor operations with sampling; never stop a worker
            # while its to_thread operation is still running.
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=.5)
                except asyncio.TimeoutError:
                    raw = None
                if raw is not None:
                    msg = decode(raw)
                    kind = msg['type']
                    if kind == 'start_session':
                        if self.session is not None:
                            await self.stop()
                        await asyncio.to_thread(self.sensors.start)
                        self.session = msg['session_id']
                        deadline = time.monotonic()+self.interval
                    elif kind == 'stop_session':
                        await self.stop()
                    elif kind == 'set_camera':
                        if msg['on'] and self.session is None:
                            raise ValueError('No active session')
                        await asyncio.to_thread(self.sensors.set_camera,msg['on'])
                        self.camera_on = msg['on']
                    elif kind == 'watch_resumption':
                        if self.session is None:
                            raise ValueError('No active session')
                        self.watch = (msg['break_id'],time.monotonic())
                    elif kind != 'get_status':
                        raise ValueError('Already paired')
                    await self.status(ws)
                if self.session is not None:
                    last = await asyncio.to_thread(self.sensors.poll)
                    if self.watch and last is not None and last >= self.watch[1]:
                        bid, started = self.watch
                        self.watch = None
                        await self.send(ws,dict(type='resumption',break_id=bid,seconds_to_first_edit=int(last-started)))
                    if time.monotonic() >= deadline:
                        data = await asyncio.to_thread(self.sensors.sample)
                        self.category = data['app_category']
                        self.history.append(data['window_switches'])
                        camera = data['camera']
                        await self.send(ws,dict(type='signals',session_id=self.session,
                            timestamp=datetime.now(timezone.utc).isoformat(),**data,
                            keys_per_min=data['keystroke_count']*2,switches_per_5min=sum(self.history),
                            idle_sec=data['idle_seconds'],eye_score=camera.get('fatigue_score') if camera else None))
                        deadline = time.monotonic()+self.interval
        except ConnectionClosed:
            pass
        except (ValueError, asyncio.TimeoutError):
            await ws.close(1008,'Invalid request or pairing timeout')
        except Exception:
            await ws.close(1011,'Sensor operation failed')
        finally:
            try:
                if self.owner is ws:
                    await self.stop()
            finally:
                self.owner = None
                self.pending = False
                if not self.blocked:
                    self.new_code()

    async def run(self):
        async with serve(self.handler,'127.0.0.1',8765,origins=[None],
                         max_size=4096,max_queue=4,ping_interval=10,ping_timeout=10):
            self.new_code()
            print('FLOW agent listening on ws://127.0.0.1:8765',flush=True)
            await asyncio.Future()
