import click
import asyncio

from datetime import datetime, date
from typing import Collection
from tabulate import tabulate

from clt import broker as br

from clt.utils import load_and_spin, color_pl, percent_change, asink


@click.group()
def position():
    pass


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
@asink
async def list_():
    
    broker = br.Tradier(
        '6YA05267',
        access_token='ey39F8VMeFvhNsq4vavzeQXThcpL'
    )
    
    positions, account_ = await load_and_spin(
        asyncio.gather(
            broker.positions,
            broker.account_balance
        ),
        'loading',
        persist=False
    )
    
    quotes = await load_and_spin(
        broker.get_quotes([x.name for x in positions]),
        'loading',
        persist=False
    )
    
    today = datetime.utcnow().date()
    
    table = [
        [
            x.name,
            x.size,
            color_pl(percent_change(x.cost_basis, y.price * x.size)),
            ((y.price * x.size) / account_.total_equity) * 100,
            '-',
            '-',
            (today - x.time_opened.date()).days
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


@position.command()
@click.argument('name')  # , nargs=-1)
@click.option('-a', '--allocation', type=click.IntRange(1, 100), default=2)
@click.option('-s', '--stop-loss', type=click.IntRange(1, 50), default=None)
@click.option('-p', '--preview/--no-preview', default=False)
@asink
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
        click.echo('placing stop loss order')
        stop_price = quote.price * ((100 - stop_loss) / 100)
        await broker.place_stop_loss(
            name,
            order.executed_quantity,
            round(stop_price, 2)
        )


@position.command(name='exit')
@click.argument('name', required=False)
#@click.option('-a', '--all', is_flag=True, name='all_')
@asink
async def exit_(name: str):
    
    broker = br.Tradier(
        '6YA05267',
        access_token='ey39F8VMeFvhNsq4vavzeQXThcpL'
    )
    
    orders, positions = await load_and_spin(
        asyncio.gather(broker.orders, broker.positions),
        'checking',
        persist=False
    )
    
    if name not in positions:
        click.echo(f'{name} is not currently held')
        return
    
    open_orders = [
        order for order in orders
        if order.status == br.OrderStatus.OPEN
           and order.name.lower() == name.lower()
    ]
    
    await load_and_spin(
        asyncio.gather(
            *[broker.cancel_order(order.id) for order in open_orders]
        ), 'cancelling open orders'
    )
    
    pos = [x for x in positions if x == name][0]
    await load_and_spin(
        broker.place_market_sell(name, pos.size),
        f'placing market sell for {name.upper()}'
    )


@position.command()
@asink
async def history():
    broker = br.Tradier(
        '6YA05267',
        access_token='ey39F8VMeFvhNsq4vavzeQXThcpL'
    )
    
    since = date(year=date.today().year, month=1, day=1)
    
    pnl = await load_and_spin(
        broker.account_pnl(since_date=since),
        'loading',
        persist=False
    )
    
    table = [
        [
            x.name,
            x.size,
            color_pl(percent_change(x.cost_basis, x.proceeds)),
            (x.time_closed - x.time_opened).days
        ] for x in pnl
    ]
    
    click.echo()
    click.echo(
        tabulate(
            table,
            headers=[
                f'Name ({len(table)})',
                'Quantity',
                'Gain/Loss (%)',
                'Days Held'
            ],
            tablefmt='fancy_grid',
            floatfmt='.2f'
        )
    )
    click.echo()


@position.command()
@click.argument('name')
@asink
async def adjust(name):
    click.echo('adjust position')
    
    async def do_something():
        await asyncio.sleep(1)
        return 34 * 93
    
    result = await load_and_spin(do_something(), 'doing something',
                                 persist=False)
    
    click.echo(result)

