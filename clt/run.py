"""
This is a proof of concept short term momentum strategy.
Things to figure out:
1. What size bar to use. I'm thinking either 5, 10 or 15 minute bars.
2. When do we want to rebalance?
 - open all positions at the beginning of the day and close out all positions at the end of the day. This would be
 restrictive since you have the 3 day rule to settle transactions.
 - Setup a rolling timeframe that would span multiple days
3. Have to find some way to persist state across restarts potentially.
4. Have to do a check against settled cash before buying new names
"""

import asyncio
import string
from dataclasses import dataclass
from datetime import datetime, timedelta
from os import environ
from statistics import correlation, linear_regression
from typing import List

import click
import httpx
from dateutil import parser
from exchange_calendars import get_calendar
from pandas import Timestamp
from tiingo import TiingoClient

from clt import broker as brkr
from clt.utils import asink

# tiingo_client = TiingoClient()
# tiingo_token = environ.get("TIINGO_API_KEY")
#
# tradier_account = environ.get("TRADIER_ACCOUNT")
# tradier_token = environ.get("TRADIER_API_BEARER")
# tradier_url = environ.get("TRADIER_URL")

calendar = get_calendar("NYSE")

# period over which to calculate momentum
look_back_period = 126


def session_subtract(session, n):
    while n > 0:
        session = calendar.previous_session(session)
        n -= 1
    return session


@click.group(invoke_without_command=True)
@click.option("-p", "--plot", is_flag=True)
@click.pass_context
@asink
async def run(ctx):
    broker = brkr.Tradier("6YA05267", access_token="ey39F8VMeFvhNsq4vavzeQXThcpL")

    while True:
        now = Timestamp.utcnow()
        today = now.today().date()
        # if not calendar.is_session(today):
        #     await asyncio.sleep(5)
        #     continue

        # setup rebalance frequency
        # first_minute = calendar.session_first_minute(today)
        # last_minute = calendar.session_last_minute(today)
        #
        # if first_minute <= now < last_minute:
        #     print("Market is open")
        #     # make one trade in the morning and close it out in the afternoon?
        # elif now < first_minute:
        #     print("Before market open")
        #     # Need to update list of symbols
        # elif now >= last_minute:
        #     print("After market close")

        print("Fetching names")

        # fetch relevant names form Tiingo with the start of a new trading day
        desirable_characters = string.ascii_letters + string.digits
        # last_session = calendar.previous_session(today).date()
        last_session = today - timedelta(days=1)

        symbols = [
            x["ticker"]
            for x in tiingo_client.list_stock_tickers()
            if x["exchange"] in ("NYSE", "NASDAQ", "AMEX")
            and x["assetType"].lower() == "stock"
            and x["endDate"]
            and parser.parse(x["endDate"]).date() in (today, last_session)
            and all([y in desirable_characters for y in x["ticker"]])
        ]

        # Filter down to an appropriate set of names that have enough volume to trade

        # Fetch price data for each name
        async def get_price(symbol):
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://api.tiingo.com/iex/{symbol}/prices",
                    params={
                        "resampleFreq": "5min",
                        "columns": "date,close,volume",
                        "startDate": str(session_subtract(last_session, 3).date()),
                    },
                    headers={"Authorization": f"Token {tiingo_token}"},
                )
                return symbol, resp.json()

        tasks = [get_price(symbol) for symbol in symbols[:100]]
        minute_prices = await asyncio.gather(*tasks)

        # sort on volume and pull the top 1k or 2k

        # compute correlation and slope for each name
        momentum_quality = set()
        for symbol, data in minute_prices:
            close_prices = [x["close"] for x in data[-look_back_period:]]
            rng = list(range(1, len(close_prices) + 1))
            try:
                r_value = correlation(rng, close_prices)
            except Exception as e:
                print(f"Error in computing correlation for {symbol}")
                continue
            slope = linear_regression(rng, close_prices).slope
            momentum_quality.add((symbol, slope * r_value**2))

        # sort momentum quality
        top_ranked_momentum = [
            name for name, _ in sorted(momentum_quality, key=lambda _: _[1], reverse=True)[:20]
        ]

        # get current portfolio
        positions = {pos.name: pos for pos in await broker.positions}
        position_names = positions.keys()

        # diff top names and current names to establish what to sell and what to buy
        names_to_buy = set(top_ranked_momentum) - set(position_names)
        names_to_sell = set(position_names) - set(top_ranked_momentum)

        # sell what needs to be sold
        for name in names_to_sell:
            order_id = await place_market_sell(name, positions[name].size)
            print(f"Selling off {name}")

        # buy what needs to be bought if we have the settled cash to do so
        for name in names_to_buy:
            await place_market_buy(
                name,
            )
