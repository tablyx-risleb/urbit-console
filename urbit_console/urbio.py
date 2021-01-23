#!python3

import asks, time, secrets, re, attr, trio

from typing import Any, Optional, Dict, AsyncIterator

# Basically a clone of urlock-py built on asks rather than requests

class UrbitError(Exception):
    pass

@attr.s(auto_attribs=True)
class SSEEvent:
    event_type: str = 'message'
    data: str = ''
    event_id: str = ''

class SSEStream:
    def __init__(self, url: str, s: Optional[asks.Session] = None) -> None:
        if url.endswith('/'):
            url = url[:-1]
        self.url = url
        self.conn = None
        if s is None:
            self.session = asks
        else:
            self.session = s
        self.recon_delay = 1000
        self.verbose = False
        self.closed = False
        # self.cancel_scope = None

    async def connect(self) -> bool:
        self.conn = await self.session.get(self.url, stream=True)
        if self.conn.status_code == 204:
            return False
        assert self.conn.headers['Content-Type'] == 'text/event-stream'
        return True

    async def events(self) -> AsyncIterator[SSEEvent]:
        cur_event = SSEEvent()
        last_event_id = ''

        async def process_data():
            nonlocal cur_event, last_event_id
            data = b''
            async for dc in self.conn.body:
                data += dc
                if not (data.endswith(b"\n") or data.endswith(b"\r")):
                    continue
                for bl in data.splitlines():
                    l = bl.decode()
                    if self.verbose:
                        print('l=' + repr(l))

                    if l == '':
                        if cur_event.data != '':
                            if cur_event.data.endswith('\n'):
                                cur_event.data = cur_event.data[:-1]
                            yield cur_event
                        cur_event = SSEEvent(event_id=last_event_id)
                        continue

                    if ':' not in l:
                        f, v = l, ''
                    else:
                        f, v = l.split(':', maxsplit=1)
                    if v.startswith(' '):
                        v = v[1:]

                    # line began with colon: comment/ignore
                    if f == '':
                        continue

                    if f == 'event':
                        cur_event.event_type = v if v != '' else 'message'
                    elif f == 'data':
                        cur_event.data += v
                        cur_event.data += '\n'
                    elif f == 'id':
                        last_event_id = v
                        cur_event.event_id = v
                    elif f == 'retry':
                        try:
                            self.recon_delay = int(v)
                        except ValueError:
                            pass
                    if self.verbose:
                        print('cur_event=' + str(cur_event))
                data = b''

        while True:
            async with self.conn.body:
                async for ev in process_data():
                    yield ev

            # connection closed locally by close()
            if self.closed:
                break

            # connection closed on server end
            await trio.sleep(self.recon_delay / 1000.0)
            if not await self.connect():
                break

    async def close(self) -> None:
        await self.conn.body.close()
        self.closed = True
        # if self.cancel_scope is not None:
        #     self.cancel_scope.cancel()

def verify_result(r, op: str, require_code: Optional[int] = None) -> None:
    if ((require_code is not None and r.status_code != require_code) or
        (r.status_code // 100 != 2)):
        raise UrbitError(f"error on {op}: "
                         f"{r.status_code} {r.reason_phrase}")

@attr.s(auto_attribs=True)
class Subscription:
    id: int
    ship: str
    app: str
    path: str

class UrbIO:
    def __init__(self, url: str, code: str) -> None:
        # 5 is a guess, we know we need more than 1 to support the SSE
        # subscription but no idea what the real optimum is
        self.session = asks.Session(connections=5, persist_cookies=True)
        self.uid = f"{int(time.time())}-{secrets.token_hex(3)}"
        self.last_event = 0
        self.url = url
        if code.startswith('~'):
            code = code[1:]
        # I could validate this for being real @p but I don't want to
        if not re.match(r"^([a-z]{6}-){3}[a-z]{6}$", code):
            raise ValueError("invalid code format")
        self.code = code
        self.channel_url = f"{self.url}/~/channel/{self.uid}"
        self.subscriptions: Dict[int, Subscription] = {}
        self._stream_rv = None
        self.deleted = False
        self.verbose = True

    def new_event_id(self) -> int:
        if self.deleted:
            raise UrbitError("attempted to use deleted subscription")
        self.last_event += 1
        return self.last_event

    async def connect(self) -> None:
        r = await self.session.post(self.url + '/~/login',
                                    data={'password': self.code})
        if self.verbose:
            print(r.__dict__)
        verify_result(r, 'connect')

    async def _do_put(self, action: str, data: Dict[str, Any]):
        packet_id = self.new_event_id()
        json = [{
            'id': packet_id,
            'action': action,
            **data}]
        if self.verbose:
            print(self.channel_url, json)
        r = await self.session.put(self.channel_url, json=json)
        if self.verbose:
            print(r.__dict__)
        verify_result(r, action)
        return packet_id, r

    # pokes don't return any data (I think?)
    async def poke(self, ship: str, app: str, mark: str, j: Any) -> None:
        await self._do_put('poke', {
            'ship': ship,
            'app': app,
            'mark': mark,
            'json': j
        })

    async def ack(self, event_id):
        await self._do_put('ack', { 'event-id': event_id })

    async def subscribe(self, ship: str, app: str, path: str) -> Subscription:
        packet, r = await self._do_put('subscribe', {
            'ship': ship,
            'app': app,
            'path': path
        })
        rv = Subscription(id=packet, ship=ship, app=app, path=path)
        self.subscriptions[packet] = rv
        return rv

    async def unsubscribe(self, subscription_id) -> None:
        await self._do_put('unsubscribe', {'subscription': subscription_id})
        del self.subscriptions[subscription_id]

    async def delete(self) -> None:
        await self._do_put('delete', {})
        if self._stream_rv is not None:
            await self._stream_rv.close()
        self.deleted = True

    async def event_stream(self) -> SSEStream:
        r = SSEStream(self.channel_url, self.session)
        await r.connect()
        self._stream_rv = r
        return r

    async def scry(self, app: str, path: str, mark: str) -> bytes:
        url = f"{self.url}/~/scry/{app}{path}.{mark}"
        r = await self.session.get(url)
        return r.content
