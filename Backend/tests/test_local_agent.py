import asyncio
import json
import pytest
from websockets.asyncio.server import serve
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from agent.protocol import decode
from agent.server import AgentServer

@pytest.mark.parametrize('raw', ['[]','null','{}','{"type":"bad"}',
    '{"type":"set_camera","on":1}', '{"type":"pair","code":""}',
    '{"type":"get_status","token":"secret"}'])
def test_invalid(raw):
    with pytest.raises(ValueError):
        decode(raw)

class FakeSensors:
    def __init__(self):
        self.active = False
        self.camera = False
    def start(self): self.active = True
    def stop(self): self.active = self.camera = False
    def set_camera(self,on): self.camera = on
    def poll(self): return None
    def sample(self):
        assert self.active
        return dict(keystroke_count=3,window_switches=1,idle_seconds=2,
            app_category='development',camera={'ear':.3,'fatigue_score':.1} if self.camera else None)

async def recv(ws):
    return json.loads(await asyncio.wait_for(ws.recv(),3))

async def send(ws,kind,**fields):
    await ws.send(json.dumps(dict(type=kind,**fields)))

def test_lifecycle():
    async def run():
        sensors=FakeSensors(); agent=AgentServer(sensors,interval=.1); agent.new_code()
        async with serve(agent.handler,'127.0.0.1',0,origins=[None]) as server:
            url=f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'
            async with connect(url) as ws:
                assert not (await recv(ws))['paired']
                assert not sensors.active
                await send(ws,'pair',code=agent.code)
                assert (await recv(ws))['paired']
                await send(ws,'start_session',session_id='test')
                assert (await recv(ws))['behavior_on']
                event=await recv(ws)
                assert event['session_id']=='test' and event['camera'] is None
                await send(ws,'set_camera',on=True)
                assert (await recv(ws))['camera_on']
                assert (await recv(ws))['camera']['ear']==.3
                async with connect(url) as other:
                    with pytest.raises(ConnectionClosed): await other.recv()
                await send(ws,'stop_session')
                assert not (await recv(ws))['behavior_on']
                assert not sensors.active and not sensors.camera
                await send(ws,'start_session',session_id='second')
                assert (await recv(ws))['behavior_on']
            for _ in range(30):
                if not sensors.active: break
                await asyncio.sleep(.05)
            assert not sensors.active and not sensors.camera
    asyncio.run(run())

def test_unpaired_cannot_start():
    async def run():
        sensors=FakeSensors(); agent=AgentServer(sensors); agent.new_code()
        async with serve(agent.handler,'127.0.0.1',0,origins=[None]) as server:
            url=f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'
            async with connect(url) as ws:
                await recv(ws)
                await send(ws,'start_session',session_id='bad')
                with pytest.raises(ConnectionClosed): await ws.recv()
            assert not sensors.active
    asyncio.run(run())
