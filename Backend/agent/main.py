"""Launch with python -m agent.main from Backend."""
import asyncio
from .server import AgentServer


def run():
    try:
        asyncio.run(AgentServer().run())
    except KeyboardInterrupt:
        print('FLOW agent stopped')


if __name__ == '__main__':
    run()
