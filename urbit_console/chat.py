#!python3

import click, trio, json
from .urbio import UrbIO

async def main(url: str, ship: str, code: str) -> None:
    u = UrbIO(url, code)
    try:
        await u.connect()
        await u.subscribe(ship, 'group-store', '/groups')
        s = await u.event_stream()
        async for ev in s.events():
            print(ev)
            do_ack = True
            try:
                d = json.loads(ev.data)
                print(json.dumps(d, indent=2))
                if d.get('ok', '') == 'ok':
                    do_ack = False
            except json.decoder.JSONDecodeError:
                pass
            if do_ack:
                await u.ack(ev.event_id)
    finally:
        await u.delete()

@click.command()
@click.argument('url')
@click.argument('ship')
@click.option('--code', prompt='+code', hide_input=True,
              envvar='URBIT_CODE',
              help="+code for your ship")
def sync_main(url: str, ship: str, code: str) -> None:
    trio.run(main, url, ship, code)
