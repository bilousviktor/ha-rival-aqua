import asyncio, sys, pathlib, datetime
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "rival_aqua"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import aiohttp
from aiohttp import web
import importlib.util

# load api.py and levels.py without the HA package __init__
def load(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod; spec.loader.exec_module(mod); return mod
base = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "rival_aqua"
api = load("api", base / "api.py")
from mock_controller import Controller

async def main():
    ctl = Controller()
    runner = web.AppRunner(ctl.app()); await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8765); await site.start()
    async with aiohttp.ClientSession() as s:
        c = api.RivalAquaClient("127.0.0.1:8765", s)
        info = await c.async_get_info()
        assert info.channel_count == 5 and not info.fan_enabled, info
        assert info.channel_names[:5] == ["Cool White", "Green", "Blue", "Warm White", "Red"], info.channel_names
        assert info.version == "2.1"
        st = await c.async_get_state(include_schedule=True)
        assert st.levels == [58, 9, 9, 9, 9] and not st.manual, st
        assert len(st.schedule) == 9 and st.schedule[0][3].minute == 11*60 and st.schedule[0][3].level == 59
        await c.async_set_manual(True, [58, 9, 9, 9, 9])
        st = await c.async_get_state(); assert st.manual and st.hand_mode and st.manual_unlocked
        await c.async_set_channel(2, 77); await c.async_set_all([10, 20, 30, 40, 101])
        st = await c.async_get_state(); assert st.levels == [10, 20, 30, 40, 100], st.levels
        await c.async_set_manual(False)
        st = await c.async_get_state(); assert not st.manual and st.levels == [58, 9, 9, 9, 9]
        await c.async_sync_time(datetime.datetime(2026, 11, 18, 13, 5, 9)); assert ctl.clock == (13, 5, 9)
        await c.async_set_night_indicator(False); assert ctl.stat is False
        print("writes sent:", [l for l in ctl.log if not l.startswith(("/chnumb", "/curlevel", "/hand", "/block", "/name", "/color", "/curver", "/chart"))][:12])
        # unreachable host
        bad = api.RivalAquaClient("127.0.0.1:1", s)
        try:
            await bad.async_get_info(); raise SystemExit("expected error")
        except api.RivalConnectionError as e:
            print("unreachable ok:", type(e).__name__)
    await runner.cleanup()
    print("API OK")

asyncio.run(main())
