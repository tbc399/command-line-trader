import click
import asyncio
import pydantic

from functools import wraps
from tabulate import tabulate
from datetime import datetime

import broker as br


def coro(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper


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


@position.command()
def list():

    broker = br.Tradier(
        '6YA05267',
        access_token='ey39F8VMeFvhNsq4vavzeQXThcpL'
    )
    
    positions = broker.positions
    
    if len(positions) > 1:
        quotes = broker.get_quotes([x.name for x in positions])
    else:
        quotes = broker.get_quote(positions[0].name)
        
    account = broker.account_balance
    now = datetime.utcnow()
    
    table = [
        [
            x.name,
            x.size,
            color_pl(percent_change(x.cost_basis, y.price * x.size)),
            ((y.price * x.size) / account.total_equity) * 100,
            (now - x.time_acquired).days
        ] for x, y in zip(
            sorted(positions, key=lambda x: x.name),
            sorted(quotes, key=lambda x: x.name))
        ]
    #  TODO: add in days in position
    click.echo()
    click.echo(
        tabulate(
            table,
            headers=[
                f'Name ({len(table)})',
                'Quantity',
                'Gain/Loss (%)',
                'Concentration (%)',
                'Days Held'
            ],
            tablefmt='fancy_grid',
            floatfmt='.2f'
        )
    )
    click.echo()
    
    
@position.command()
@click.argument('name')
@click.option('-a', '--allocation', type=click.IntRange(1, 100), default=2)
@click.option('-s', '--stop-loss', type=click.IntRange(1, 50), default=None)
@click.option('-t', '--take-profit', type=click.IntRange(1, 1000), default=None)
@click.option('-p', '--preview/--no-preview', default=True)
def enter(name, allocation, stop_loss, take_profit, preview):
    
    broker = br.Tradier(
        '6YA05267',
        access_token='ey39F8VMeFvhNsq4vavzeQXThcpL'
    )
    
    balances = broker.account_balance
    account_base = balances.total_equity - balances.open_pl
    
    allocation_size = (allocation / 100) * account_base
    
    #quote = broker.get_quote(name)
    


@position.command()
@click.argument('name')
def exit(name):
    #  TODO: check that name is actually currently held
    #  TODO: remove any open orders
    click.echo(f'exit a position {name}')


if __name__ == '__main__':
    cli()
