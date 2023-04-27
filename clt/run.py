"""
This is a proof of concept short term momentum strategy.
Things to figure out:
1. What size bar to use. I'm thinking either 5, 10 or 15 minute bars. Let's try 15 minute bars
2. When do we want to rebalance? Let's do once a day at midday since that lines up nicely with the 15 minute bars
 - open all positions at the beginning of the day and close out all positions at the end of the day. This would be
 restrictive since you have the 3 day rule to settle transactions.
 - Setup a rolling timeframe that would span multiple days
3. Have to find some way to persist state across restarts potentially.
4. Have to do a check against settled cash before buying new names
5. Need to handle 429 too many requests per hour
"""

import asyncio
import string
from datetime import timedelta
from os import environ
from statistics import correlation, linear_regression

import click
import httpx
import toolz
from dateutil import parser
from exchange_calendars import get_calendar
from pandas import Timestamp
from tiingo import TiingoClient

from clt import position
from clt.utils import asink

tiingo_client = TiingoClient()
tiingo_token = environ.get("TIINGO_API_KEY")

calendar = get_calendar("NYSE")

# period over which to calculate momentum
look_back_period = 130  # roughly about 4 days of 15min bars
portfolio_size = 25  # target portfolio size
quality_threshold = 0.93  # looking for r values gte this


def session_subtract(session, n):
    while n > 0:
        session = calendar.previous_session(session)
        n -= 1
    return session


async def fetch_symbols(today, broker, allocation):
    # filter on types of symbols
    desirable_characters = string.ascii_letters + string.digits
    last_session = calendar.previous_session(today).date()
    # last_session = calendar.previous_session(today - timedelta(days=2)).date()
    # today = Timestamp.utcnow().date() - timedelta(days=2)

    symbols = [
        x["ticker"]
        for x in tiingo_client.list_stock_tickers()
        if x["exchange"] in ("NYSE", "NASDAQ", "AMEX")
        and x["assetType"].lower() == "stock"
        and x["endDate"]
        and parser.parse(x["endDate"]).date() in (today, last_session)
        and all([y in desirable_characters for y in x["ticker"]])
    ]

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.tiingo.com/tiingo/daily/prices",
            headers={"Authorization": f"Token {tiingo_token}"},
            timeout=5,
        )
        daily_prices = [
            (item["ticker"].upper(), {"close": item["close"], "volume": item["volume"]})
            for item in resp.json()
            if item["ticker"].upper() in symbols
        ]

    balance = await broker.account_balance
    account_base = balance.total_equity - balance.open_pl
    max_price = account_base * allocation

    # TODO: filter for price that makes sense
    # TODO: switch this to percentage later
    affordable_daily_prices = [
        (symbol, data) for symbol, data in daily_prices if data and data["close"] <= max_price
    ]
    high_volume_filtered = sorted(affordable_daily_prices, key=lambda x: x[1]["volume"])[-4000:]
    return [symbol for symbol, _ in high_volume_filtered]


async def rebalance(broker, today, symbols):
    last_session = calendar.previous_session(today)
    # last_session = calendar.previous_session(today - timedelta(days=3))

    # Fetch price data for each name
    async def get_price(symbol):
        async with httpx.AsyncClient() as client:
            retries = 3
            while retries > 0:
                try:
                    resp = await client.get(
                        f"https://api.tiingo.com/iex/{symbol}/prices",
                        params={
                            "resampleFreq": "15min",
                            "columns": "date,close,volume",
                            "startDate": str(session_subtract(last_session, 4).date()),
                        },
                        headers={"Authorization": f"Token {tiingo_token}"},
                        timeout=5,
                    )
                    if resp.status_code == httpx.codes.TOO_MANY_REQUESTS:
                        print("Hit request limit")
                        return symbol, {}
                    return symbol, resp.json()
                except httpx.ConnectTimeout as error:
                    retries -= 1
                except httpx.ReadTimeout as error2:
                    retries -= 1
            print(f"Failed to get minute prices for {symbol}")
            return symbol, []

    chunked_tasks = toolz.partition(100, [get_price(symbol) for symbol in symbols])
    minute_prices = []
    for chunk in chunked_tasks:
        minute_prices += await asyncio.gather(*chunk)
        await asyncio.sleep(2)

    # compute correlation and slope for each name
    momentum_quality = set()
    r_values = []
    for symbol, data in minute_prices:
        try:
            close_prices = [x["close"] for x in data[-look_back_period:]]
        except TypeError as error:
            print(error)
            continue
        rng = list(range(1, len(close_prices) + 1))
        try:
            r_value = correlation(rng, close_prices)
            if r_value < quality_threshold:
                continue  # only the highest quality
            r_values.append((symbol, r_value))
        except Exception as e:
            print(f"Error in computing correlation for {symbol}: {e}")
            print(data)
            continue
        slope = linear_regression(rng, close_prices).slope
        # momentum_quality.add((symbol, slope * r_value**2))
        momentum_quality.add((symbol, slope))

    # sort momentum quality
    top_ranked_momentum = [
        name
        for name, _ in sorted(momentum_quality, key=lambda _: _[1], reverse=True)[:portfolio_size]
    ]

    # get current portfolio
    positions = {pos.name: pos for pos in await broker.positions}
    position_names = positions.keys()

    # diff top names and current names to establish what to sell and what to buy
    names_to_buy = set(top_ranked_momentum) - set(position_names)
    names_to_sell = set(position_names) - set(top_ranked_momentum)

    # sell what needs to be sold
    for name in names_to_sell:
        click.echo(f"attempting to close out {name}")
        await position.exit_(broker, name)

    # buy what needs to be bought if we have the settled cash to do so
    for name in names_to_buy:
        click.echo(f"attempting to enter into {name}")
        await position.enter_(broker, name, (100 // portfolio_size), None, False)


@click.command
@click.pass_context
@asink
async def run(ctx):
    broker = ctx.obj.get("context").broker

    # Need to grab symbols here to initialize
    symbols = await fetch_symbols(Timestamp.utcnow().date(), broker, portfolio_size)
    last_symbol_refresh = Timestamp.today().date()  # check this will work with other tz times
    last_rebalance = Timestamp.today().date() - timedelta(days=1)

    while True:
        now = Timestamp.utcnow()
        today = now.today().date()

        if not calendar.is_session(today):
            await asyncio.sleep(5)
            continue

        # setup rebalance frequency
        first_minute = calendar.session_first_minute(today)
        last_minute = calendar.session_last_minute(today)

        # await rebalance(broker, today, symbols)
        # return

        if first_minute <= now < last_minute:
            # market is open
            # rebalance every day at noon
            if now.tz_convert("America/Chicago").hour == 12:
                if last_rebalance < today:
                    click.echo("Rebalancing")
                    await rebalance(broker, today, symbols)
                    last_rebalance = today
        elif (first_minute - timedelta(minutes=10)) < now < first_minute:
            # update the symbols list
            if not symbols or last_symbol_refresh < today:
                click.echo("Refreshing symbols list")
                symbols = await fetch_symbols(today, broker, portfolio_size)
                last_symbol_refresh = today

        await asyncio.sleep(5)
