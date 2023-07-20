import asyncio
import os
from collections import defaultdict
from datetime import date

import click
import pandas
from tabulate import tabulate

from clt import broker as br
from clt.utils import asink, green, load_and_spin, red


@click.group(invoke_without_command=True)
@click.option("-p", "--plot", is_flag=True)
@click.pass_context
@asink
async def account(ctx, plot):
    if ctx.invoked_subcommand is not None:
        return

    print(ctx)
    broker = ctx.obj.get("context").broker

    balances, pnl, account_history = await load_and_spin(
        asyncio.gather(
            broker.account_balance,
            broker.account_pnl(since_date=date(year=2015, month=1, day=1)),
            broker.account_history(),
        ),
        "loading",
        persist=False,
    )

    if plot:
        agg = defaultdict(int)
        for x, y in [(x.time_closed, x.proceeds - x.cost_basis) for x in pnl] + [
            (x.date, x.amount) for x in account_history
        ]:
            agg[x] += y

        running_sum = 0
        account_value = []
        for x, y in sorted(agg.items(), key=lambda x: x[0]):
            running_sum += y
            print(x, running_sum)
            account_value.append((x, running_sum, 0, 0, 0))

        df = pandas.DataFrame(account_value, columns=("date", "close", "open", "high", "low"))
        df["date"] = pandas.to_datetime(df["date"])
        df = df.set_index("date")
        # mplfinance.plot(df, type='line')
        return

    click.echo("")
    open_pl_percentage = (balances.open_pl / (balances.total_equity - balances.open_pl)) * 100
    click.echo(
        tabulate(
            [
                [
                    balances.total_equity,
                    balances.long_value,
                    balances.settled_cash,
                    green(open_pl_percentage)
                    if open_pl_percentage > 0
                    else red(open_pl_percentage),
                ]
            ],
            headers=[
                f"Total Equity",
                "Long Value",
                "Settled Cash",
                "Open P/L (%)",
            ],
            tablefmt="fancy_grid",
            floatfmt=",.2f",
        )
    )
    click.echo("")


@account.command()
@click.option("-p", "--plot")
@click.pass_context
@asink
async def returns(ctx, plot):
    broker = ctx.obj.get("context").broker

    since = date(year=date.today().year, month=1, day=1)

    balances, pnl, history_ = await load_and_spin(
        asyncio.gather(
            broker.account_balance, broker.account_pnl(since_date=since), broker.account_history()
        ),
        "loading",
        persist=False,
    )

    pnl_sum = sum(x.proceeds - x.cost_basis for x in pnl)
    account_value = balances.total_equity - balances.open_pl

    returns_ = (pnl_sum / (account_value - pnl_sum)) * 100

    click.echo("")
    click.echo(
        tabulate(
            [[returns_, pnl_sum]],
            headers=[f"Return Percentage", "Return Value"],
            tablefmt="fancy_grid",
            floatfmt=",.2f",
        )
    )
    click.echo("")


@account.command(name="new")
def new_account():
    home_dir = os.environ["HOME"]

    account_name = click.prompt("Account name")
    broker = click.prompt("Broker")
    account_number = click.prompt("Account number")
