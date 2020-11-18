import sys
import click
import asyncio
import pydantic
import itertools
#import mplfinance

from functools import wraps
from tabulate import tabulate
from datetime import datetime
from typing import Collection

import broker as br


def coro(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper


async def wait_n_spin(coroutine, info: str, persist: bool = True):
    
    task = asyncio.ensure_future(coroutine)
    
    spinner = itertools.cycle(['|', '/', '-', '\\'])

    while not task.done():
        sys.stdout.write('\r')
        sys.stdout.write(f'{info} {cyan(next(spinner))} ')
        sys.stdout.flush()
        await asyncio.sleep(0.1)
        
    if persist:
        sys.stdout.write('\r')
        sys.stdout.write(f'{info}  \n')
    else:
        sys.stdout.write('\r')
        sys.stdout.write(' ' * len(f'{info} {cyan(next(spinner))} '))
        sys.stdout.write('\r')

    return task.result()


class DetailedPosition(pydantic.BaseModel):
    name: str
    cost_basis: float
    quantity: int
    current_basis: float
    allocation: float
    gain_loss: float
    gain_loss_percent: float


def red(text):
    return f'\033[91m{text}\033[0m'


def green(text):
    return f'\033[32m{text}\033[0m'


def cyan(text):
    return f'\033[36m{text}\033[0m'


@click.group()
def cli():
    pass


@cli.group()
def position():
    pass


def percent_change(start, end):
    return ((end - start) / start) * 100


def color_pl(pl):
    return green(pl) if pl >= 0 else red(pl)


async def _wait_for_pending_orders(pending_order_ids, broker):

    while pending_order_ids:
        
        await asyncio.sleep(.5)
        
        orders: Collection[br.Order] = await asyncio.gather(*[
            broker.order_status(order_id)
            for order_id in pending_order_ids
        ])
        
        for order in orders:
            if order.status == br.OrderStatus.FILLED:
                pending_order_ids.remove(order.id)
                yield order
            elif order.status in (
                    br.OrderStatus.REJECTED,
                    br.OrderStatus.EXPIRED,
                    br.OrderStatus.ERROR):
                pending_order_ids.remove(order.id)
                yield order
            elif order.status == br.OrderStatus.CANCELED:
                pending_order_ids.remove(order.id)
                yield order
            else:
                pass


@position.command(name='list')
@coro
async def list_():
    
    broker = br.Tradier(
        '6YA05267',
        access_token='ey39F8VMeFvhNsq4vavzeQXThcpL'
    )
    
    positions, account_ = await wait_n_spin(
        asyncio.gather(
            broker.positions,
            broker.account_balance
        ),
        'loading',
        persist=False
    )
    
    quotes = await wait_n_spin(
        broker.get_quotes([x.name for x in positions]),
        'loading',
        persist=False
    )
    
    now = datetime.utcnow()
    
    table = [
        [
            x.name,
            x.size,
            color_pl(percent_change(x.cost_basis, y.price * x.size)),
            ((y.price * x.size) / account_.total_equity) * 100,
            '-',
            '-',
            (now - x.time_opened).days
        ] for x, y in zip(
            sorted(positions, key=lambda x: x.name),
            sorted(quotes, key=lambda x: x.name)
        )
    ]
    
    click.echo()
    click.echo(
        tabulate(
            table,
            headers=[
                f'Name ({len(table)})',
                'Quantity',
                'Gain/Loss (%)',
                'Concentration (%)',
                'Stop Loss',
                'Take Profit',
                'Days Held'
            ],
            tablefmt='fancy_grid',
            floatfmt='.2f'
        )
    )
    click.echo()
    

@cli.command()
@click.argument('name')
@coro
async def plot(name):
    
    broker = br.Tradier(
        '6YA05267',
        access_token='ey39F8VMeFvhNsq4vavzeQXThcpL'
    )
    
    history_data = await wait_n_spin(broker.history(name), 'loading')
    #mplfinance.plot(history_data)


@position.command()
@click.argument('name')
@click.option('-a', '--allocation', type=click.IntRange(1, 100), default=2)
@click.option('-s', '--stop-loss', type=click.IntRange(1, 50), default=None)
@click.option('-p', '--preview/--no-preview', default=True)
@coro
async def enter(name, allocation, stop_loss, preview):
    
    broker = br.Tradier(
        '6YA05267',
        access_token='ey39F8VMeFvhNsq4vavzeQXThcpL'
    )
    
    balances, quote, positions = await asyncio.gather(
        broker.account_balance,
        broker.get_quote(name),
        broker.positions
    )
    
    if name in positions:
        click.echo(f'position already open for {name}')
        return
    
    account_base = balances.total_equity - balances.open_pl
    allocation_size = (allocation / 100) * account_base
    
    if quote.price >= allocation_size:
        click.echo('quote is too big for given allocation size')
        return
    
    allocation_quantity = int(allocation_size / quote.price)
    actual_allocation = ((allocation_quantity * quote.price) / account_base) * 100
    
    if stop_loss:
        stop_price = quote.price * ((100 - stop_loss) / 100)
        if stop_price >= quote.price:
            click.echo('stop loss price must be less than quote price')
            return
        
    #  TODO: need to add validation that enough settled funds exist

    if preview:
        click.echo(
            f'Enter new long position for {name} @ '
            f'{allocation_quantity} shares for a '
            f'{actual_allocation:.2f}% allocation'
        )
        if stop_loss:
            click.echo(f'Stop loss @ {stop_price:.2f} ({stop_loss}%)')
        click.confirm('Continue?', abort=True)

    click.echo('placing market order')
    order_id = await broker.place_market_buy(name, allocation_quantity)
    
    async for order in _wait_for_pending_orders({str(order_id)}, broker):
        if order.status != br.OrderStatus.FILLED:
            click.echo(f'could not place market order: {order.status}')
            return
        else:
            click.echo('market order filled')
    
    if stop_loss:
        stop_price = quote.price * ((100 - stop_loss) / 100)
        await broker.place_stop_loss(
            name,
            order.executed_quantity,
            stop_price
        )


@position.command(name='exit')
@click.argument('name')
@coro
async def exit_(name):

    broker = br.Tradier(
        '6YA05267',
        access_token='ey39F8VMeFvhNsq4vavzeQXThcpL'
    )
    
    orders, positions = await wait_n_spin(
        asyncio.gather(broker.orders, broker.positions),
        'checking',
        persist=False
    )
    
    if name not in positions:
        click.echo(f'{name} is not currently held')
        return
    
    open_orders = [order for order in orders if order.type == 'open']
    for order in open_orders:
        click.echo(f'cancelling open {order.type} order {order.id}')
        
    await wait_n_spin(
        asyncio.gather(
            [broker.cancel_order(order.id) for order in open_orders]
        ), 'cancelling open orders'
    )

    pos = [x for x in positions if x == name][0]
    await wait_n_spin(
        broker.place_market_sell(name, pos.size),
        f'placing market sell for {name}'
    )

    
@position.command()
def history():
    click.echo('position history')


@position.command()
@click.argument('name')
@coro
async def adjust(name):
    click.echo('adjust position')
    
    async def do_something():
        await asyncio.sleep(1)
        return 34*93
    
    result = await wait_n_spin(do_something(), 'doing something', persist=False)
    
    click.echo(result)
    
    
@cli.group(invoke_without_command=True)
@click.pass_context
@coro
async def account(ctx):
    
    if ctx.invoked_subcommand is not None:
        return

    broker = br.Tradier(
        '6YA05267',
        access_token='ey39F8VMeFvhNsq4vavzeQXThcpL'
    )

    balances = await wait_n_spin(
        broker.account_balance,
        'loading',
        persist=False
    )
    
    click.echo('')
    open_pl_percentage = (balances.open_pl /
                          (balances.total_equity - balances.open_pl)) * 100
    click.echo(
        tabulate(
            [[
                balances.total_equity,
                balances.long_value,
                green(open_pl_percentage) if open_pl_percentage > 0
                else red(open_pl_percentage)
            ]],
            headers=[
                f'Total Equity',
                'Long Value',
                'Open P/L (%)',
            ],
            tablefmt='fancy_grid',
            floatfmt=',.2f'
        )
    )
    click.echo('')
    

@account.command()
@coro
async def returns():
    
    broker = br.Tradier(
        '6YA05267',
        access_token='ey39F8VMeFvhNsq4vavzeQXThcpL'
    )
    
    returns_ = await wait_n_spin(
        broker.account_returns,
        'loading',
        persist=False
    )
    
    click.echo('')
    click.echo(
        tabulate(
            [[
                returns_.total_return,
                returns_.ytd_return
            ]],
            headers=[
                f'Total Returns',
                'YTD Returns'
            ],
            tablefmt='fancy_grid',
            floatfmt=',.2f'
        )
    )
    click.echo('')
    returns_.returns


if __name__ == '__main__':
    cli()
