"""A fake Rival WiFi controller that mimics the endpoints captured from a real one."""
from __future__ import annotations

from aiohttp import web

CHARTDATA = (
    'var channels = {datasets: [{borderColor: ColorCHarr[0],data: [{x:"00:00",y:0},{x:"09:00",y:0},'
    '{x:"10:00",y:14},{x:"11:00",y:59},{x:"20:00",y:59},{x:"21:00",y:14},{x:"23:00",y:0},{x:"24:00",y:0}]},\n'
    + "".join(
        '{borderColor: ColorCHarr[%d],data: [{x:"00:00",y:0},{x:"09:00",y:0},{x:"10:00",y:5},{x:"11:00",y:10},'
        '{x:"20:00",y:10},{x:"21:00",y:5},{x:"23:00",y:0},{x:"24:00",y:0}]},\n' % i
        for i in range(1, 9)
    )
    + "]};"
)


class Controller:
    def __init__(self, channels: int = 5, fan: bool = False) -> None:
        self.channels = channels
        self.fan = fan
        self.stat = True
        # Manual levels (/chmanlvl, set by /light and /lightsetmode). Like the real
        # controller, /curlevelrange always reports the schedule, even in hand mode.
        self.levels = [58, 9, 9, 9, 9][:channels]
        self.schedule_levels = [58, 9, 9, 9, 9][:channels]
        self.fan_level = 30
        self.hand = 0
        self.block = 0
        self.pwm_man = False
        self.clock = None
        # Captured from the real controller: interior points only
        self.times = [9 * 60, 10 * 60, 11 * 60, 20 * 60, 21 * 60, 23 * 60]
        self.points = [[0, 14, 59, 59, 14, 0]] + [[0, 5, 10, 10, 5, 0]] * 4 + [[0] * 6] * 4
        self.pending_times = None
        self.log: list[str] = []
        # Settings page state
        self.names = ["Cool White", "Green", "Blue ", "Warm White ", "Red", "Red 2", "White 2", "White 22", "Cooler"]
        self.colors = ["#FFFFFF", "#32CD32", "#0000ff", "#ffff00", "#ff0000", "#FF00FF", "#F0F0F0", "#F0FF00", "#FF4500"]
        self.hotspot = ("Rival_LED", "11223344")  # made-up values
        self.ip = "192.168.5.200"
        self.home = "HomeNet"
        self.scan_result = ["HomeNet", "HomeNet-5G", "Neighbour"]
        self.wifi_passwords = {"HomeNet-5G": "secret123"}
        self.reboots = 0
        self.factory_resets = 0

    def chartdata(self) -> str:
        fmt = lambda m: f"{m // 60:02d}:{m % 60:02d}"
        out = []
        for ch in range(9):
            pts = [f'{{x:"00:00",y:0}}'] + [
                f'{{x:"{fmt(t)}",y:{self.points[ch][i]}}}' for i, t in enumerate(self.times)
            ] + ['{x:"24:00",y:0}']
            out.append(f"{{borderColor: ColorCHarr[{ch}],data: [{','.join(pts)}]}},")
        return "var channels = {datasets: [" + "\n".join(out) + "\n]};"

    def app(self) -> web.Application:
        app = web.Application()
        r = app.router
        txt = lambda s: web.Response(text=str(s), content_type="text/plain")
        js = lambda s: web.Response(text=s, content_type="text/javascript")

        async def log_mw_wrap(handler):
            async def h(req):
                self.log.append(str(req.rel_url))
                return await handler(req)
            return h

        def add(path, fn):
            async def handler(req):
                self.log.append(str(req.rel_url))
                return fn(req)
            r.add_get(path, handler)

        add("/chnumb", lambda q: txt(f"{self.channels},{int(self.fan)},{int(self.stat)}"))
        add("/curlevelrange", lambda q: txt("".join(f"{v};" for v in self.schedule_levels + ([self.fan_level] if self.fan else []))))

        def chmanlvl(q):
            ch = int(q.query["ch"])
            return txt(self.fan_level if ch == 8 else self.levels[ch])
        add("/chmanlvl", chmanlvl)
        add("/handmodestate", lambda q: txt(self.hand))
        add("/blockrange", lambda q: txt(self.block))
        arr = lambda name, xs: js(f"var {name}=[" + ",".join(f"'{x}'" for x in xs) + "];")
        add("/namechannellist.js", lambda q: arr("ChannelNameArr", self.names))
        add("/color.js", lambda q: arr("ColorCHarr", self.colors))
        add("/curip", lambda q: txt(self.ip))
        add("/curhomelan", lambda q: txt(self.home))
        add("/wifisetup.js", lambda q: js(f"var WifiPointName='{self.hotspot[0]}';var WifiPointPass='{self.hotspot[1]}';"))
        self._wifilist: list[str] = []
        add("/wifilist.js", lambda q: arr("WifiName", self._wifilist))

        def scanlan(q):
            self._wifilist = list(self.scan_result); return txt("OK")
        add("/scanlan", scanlan)

        def connectwifi(q):
            ssid, pw = q.query["namewifi"], q.query["passwifi"]
            if ssid == "":
                self.home = ""
                return txt("OK")
            if self.wifi_passwords.get(ssid) == pw:
                self.home = ssid
                return txt("connect")
            return txt("error")
        add("/connectwifi", connectwifi)

        def reboot(q):
            self.reboots += 1; return txt("OK")
        add("/reboot", reboot)

        def setdefault(q):
            self.factory_resets += 1; return txt("OK")
        add("/setdefault", setdefault)

        def saveparam(q):
            self.hotspot = (q.query["namepoint"], q.query["passpoint"]); return txt("OK")
        add("/saveparam", saveparam)

        def savenamechan(q):
            for i in range(self.channels):
                self.names[i] = q.query[f"name{i}"]
            return txt("OK")
        add("/savenamechan", savenamechan)

        add("/curver", lambda q: txt("2.1"))
        add("/chartdata.js", lambda q: js(self.chartdata()))

        def pointtimes(q):
            n = int(q.query["pn"])
            self.pending_times = [int(q.query[f"p{i}"]) for i in range(n)]
            self.times = self.pending_times
            self.points = [[0] * n for _ in range(9)]
            return txt("OK")
        add("/pointtimes", pointtimes)

        def pointch(q):
            ch = int(q.query["ch"])
            self.points[ch] = [int(q.query[f"p{i}"]) for i in range(len(self.times))]
            return txt("OK")
        add("/pointch", pointch)

        def light(q):
            ch, lvl = int(q.query["range"]), int(q.query["level"])
            if ch == 8:
                self.fan_level = lvl
            else:
                self.levels[ch] = lvl
            return txt("OK")
        add("/light", light)

        def setmode(q):
            n = int(q.query["ch"])
            for i in range(n):
                self.levels[i] = int(q.query[f"l{i}"])
            if "f" in q.query:
                self.fan_level = int(q.query["f"])
            return txt("OK")
        add("/lightsetmode", setmode)

        def handmode(q):
            self.hand = int(q.query["onoff"]); return txt("OK")
        add("/handmode", handmode)

        def pwm(q):
            self.pwm_man = q.query["state"] == "true"; return txt("OK")
        add("/pwm_man", pwm)

        def blockset(q):
            self.block = 1 if q.query["state"] == "true" else 0
            return txt("OK")  # manual levels stay stored (seen on the real controller)
        add("/blockrangeset", blockset)

        def sync(q):
            self.clock = (int(q.query["hour"]), int(q.query["min"]), int(q.query["sec"])); return txt("OK")
        add("/synchtime", sync)

        def lightset(q):
            self.stat = q.query["state"] == "true"; return txt("OK")
        add("/lightset", lightset)
        return app


if __name__ == "__main__":
    # Stand-alone fake controller for manual testing, e.g. a dev Home Assistant pointed at it:
    #   python3 tests/mock_controller.py --port 8080 [--fan]
    import argparse

    parser = argparse.ArgumentParser(description="Fake Rival Aqua controller")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--fan", action="store_true", help="enable the cooler channel")
    args = parser.parse_args()

    ctl = Controller(fan=args.fan)

    @web.middleware
    async def print_requests(request, handler):
        print(request.method, request.rel_url, flush=True)
        return await handler(request)

    app = ctl.app()
    app.middlewares.append(print_requests)
    web.run_app(app, host=args.host, port=args.port, print=lambda _: print(f"Mock controller on :{args.port}"))
