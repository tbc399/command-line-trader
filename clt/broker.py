import asyncio
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Collection, List, Tuple

import httpx
import pandas
from httpx import codes
from pydantic import BaseModel


class Position(BaseModel):
    name: str
    size: int
    cost_basis: float
    time_opened: datetime

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if isinstance(other, Position):
            return self.name.lower() == other.name.lower()
        elif isinstance(other, str):
            return self.name.lower() == other.lower()


class ClosedPosition(Position):
    proceeds: float
    time_closed: datetime


class AccountAction(BaseModel):
    type: str
    amount: float
    date: datetime


class OrderStatus(Enum):
    OPEN = "open"
    FILLED = "filled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELED = "canceled"
    PENDING = "pending"
    PARTIALLY_FILLED = "partially_filled"
    CALCULATED = "calculated"
    ACCEPTED_FOR_BIDDING = "accepted_for_bidding"
    ERROR = "error"
    HELD = "held"


class MarketDay(BaseModel):
    open: datetime
    close: datetime


class Order(BaseModel):
    id: str
    name: str
    side: str
    type: str
    status: OrderStatus
    executed_quantity: int
    avg_fill_price: float


class Quote(BaseModel):
    name: str
    price: float


class AccountBalance:
    def __init__(
        self,
        total_cash: float,
        total_equity: float,
        open_pl: float,
        long_value: float,
        settled_cash: float,
    ):
        self._total_cash = total_cash
        self._total_equity = total_equity
        self._open_pl = open_pl
        self._long_value = long_value
        self._settled_cash = settled_cash

    @property
    def total_cash(self):
        return self._total_cash

    @property
    def total_equity(self):
        return self._total_equity

    @property
    def open_pl(self):
        return self._open_pl

    @property
    def long_value(self):
        return self._long_value

    @property
    def settled_cash(self):
        return self._settled_cash


class ReturnStream:
    def __init__(
        self,
        initial: float,
        closed_positions: List[ClosedPosition],
        admin_adjustments: List[Tuple[datetime, float]],
    ):

        self._initial = initial

        position_gains = [(x.time_closed, x.proceeds - x.cost_basis) for x in closed_positions]

        grouped_dollar_gains = defaultdict(float)
        for dt, gl in position_gains + admin_adjustments:
            grouped_dollar_gains[dt.date()] += gl

        self._gains = sorted(grouped_dollar_gains.items(), key=lambda x: x[0])

    @staticmethod
    def __percent_change(start, end):
        return ((end - start) / start) * 100

    @property
    def total_return(self) -> float:
        return ReturnStream.__percent_change(self._initial, sum(x[1] for x in self._gains))

    @property
    def ytd_return(self) -> float:
        current_year = datetime.utcnow().year
        starting_amount = sum(x[1] for x in self._gains if x[0].year < current_year)
        current_amount = sum(x[1] for x in self._gains)
        return ReturnStream.__percent_change(starting_amount, current_amount)

    @property
    def returns(self) -> Collection[Tuple[datetime, float]]:
        last_value = self._initial
        percentage_returns = []
        for dt, gl in self._gains:
            rtn = ReturnStream.__percent_change(self._initial, last_value + gl)
            percentage_returns.append((dt, rtn))
            last_value += gl
        return percentage_returns


class Broker(ABC):
    def __init__(self, account_number: str):
        self._account_number = account_number

    @abstractmethod
    async def place_market_sell(self, name: str, quantity: int):
        pass

    @abstractmethod
    async def place_market_buy(self, name: str, quantity: int):
        pass

    @property
    @abstractmethod
    async def positions(self) -> List[Position]:
        pass

    @abstractmethod
    async def get_quote(self, name: str) -> Quote:
        pass

    @abstractmethod
    async def get_quotes(self, names: Collection[str]) -> List[Quote]:
        pass

    @property
    @abstractmethod
    async def account_balance(self) -> AccountBalance:
        pass

    @property
    @abstractmethod
    async def orders(self) -> Collection[Order]:
        pass

    @abstractmethod
    async def cancel_order(self, order_id):
        pass

    @property
    @abstractmethod
    async def account_pnl(self) -> ReturnStream:
        pass

    @abstractmethod
    async def account_history(self):
        pass

    @abstractmethod
    async def calendar(self) -> List[MarketDay]:
        pass


class Tradier(Broker):
    def __init__(self, account_number: str, **kwargs):

        super().__init__(account_number)

        access_token = kwargs.get("access_token")
        if access_token is None:
            raise ValueError("must have an access token to instantiate Tradier broker")
        
        self._api_env = kwargs.get('env', 'api') # can also be 'sandbox'

        self._headers = dict(Accept="application/json", Authorization=f"Bearer {access_token}")

    def _form_url(self, endpoint):

        tradier_api_url = f"{self._api_env}.tradier.com"
        tradier_api_version = "v1"

        if tradier_api_url is None or tradier_api_version is None:
            raise EnvironmentError("TRADIER_API and TRADIER_API_VERSION cannot be null")

        base = f"https://{tradier_api_url}/{tradier_api_version}"
        components = (base, endpoint)
        almost_there = "/".join(x.strip("/") for x in components)
        complete_url = almost_there.replace("[[account]]", self._account_number)

        return complete_url

    async def _place_order(
        self,
        name: str,
        quantity: int,
        side: str,
        order_type: str = "market",
        stop_price: float = None,
    ) -> str:

        payload = {
            "class": "equity",
            "symbol": name,
            "side": side,
            "quantity": quantity,
            "type": order_type,
            "duration": "gtc",
        }

        if order_type in ("stop", "stop_limit"):
            payload["stop"] = stop_price

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url=self._form_url("/accounts/[[account]]/orders"),
                data=payload,
                headers=self._headers,
            )

        if response.status_code != codes.OK:
            raise IOError(
                f"failed to place market {side} order from Tradier "
                f"for {name} with a status code of"
                f" {response.status_code}: {response.text}"
            )
        return response.json()["order"]["id"]

    async def place_market_sell(self, name: str, quantity: int) -> str:
        return await self._place_order(name, quantity, "sell")

    async def place_market_buy(self, name: str, quantity: int) -> str:
        return await self._place_order(name, quantity, "buy")

    async def place_stop_loss(self, name: str, quantity: int, price: float):
        return await self._place_order(name, quantity, "sell", "stop", price)

    @property
    async def account_balance(self) -> AccountBalance:

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url=self._form_url("/accounts/[[account]]/balances/"), headers=self._headers
            )

        if response.status_code != httpx.codes.OK:
            raise IOError(
                f"failed to get account balance for account "
                f"{self._account_number} with a status code of "
                f"{response.status_code}: {response.text}"
            )

        balances = response.json()["balances"]

        return AccountBalance(
            total_cash=balances["total_cash"],
            total_equity=balances["total_equity"],
            open_pl=balances["open_pl"],
            long_value=balances["long_market_value"],
            settled_cash=balances["cash"]["cash_available"],
        )

    @property
    async def positions(self) -> List[Position]:

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url=self._form_url("/accounts/[[account]]/positions/"), headers=self._headers
            )

        if response.status_code != httpx.codes.OK:
            raise IOError(
                f"failed to get account positions for account "
                f"{self._account_number} with a status code of "
                f"{response.status_code}: {response.text}"
            )

        if response.json()["positions"] in (None, "null"):
            return list()

        positions = response.json()["positions"]["position"]

        if isinstance(positions, list):

            return [
                Position(
                    name=pos["symbol"],
                    size=pos["quantity"],
                    cost_basis=pos["cost_basis"],
                    time_opened=datetime.strptime(pos["date_acquired"], "%Y-%m-%dT%H:%M:%S.%fZ"),
                )
                for pos in positions
            ]

        else:

            print(positions)

            return [
                Position(
                    name=positions["symbol"],
                    size=positions["quantity"],
                    cost_basis=positions["cost_basis"],
                    time_opened=datetime.strptime(
                        positions["date_acquired"], "%Y-%m-%dT%H:%M:%S.%fZ"
                    ),
                )
            ]

    async def get_quote(self, name: str) -> Quote:

        quotes = await self.get_quotes([name])
        return quotes[0]

    async def get_quotes(self, names: Collection[str]) -> List[Quote]:

        if not names:
            return []

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url=self._form_url("/markets/quotes/"),
                params=dict(symbols=",".join(names), greeks=False),
                headers=self._headers,
            )

        if response.status_code != codes.OK:
            raise IOError(
                f"failed to get quotes from Tradier for symbol(s) {names} "
                f"with a status code of {response.status_code}: {response.text}"
            )

        quotes = response.json()["quotes"]["quote"]

        if isinstance(quotes, list):
            return [Quote(name=quote["symbol"], price=float(quote["last"])) for quote in quotes]
        else:
            return [Quote(name=quotes["symbol"], price=float(quotes["last"]))]

    async def order_status(self, order_id: str) -> Order:

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url=self._form_url(f"/accounts/[[account]]/orders/{order_id}"),
                headers=self._headers,
            )

        if response.status_code != httpx.codes.OK:
            raise IOError(
                f"failed to get order status for order {order_id} "
                f"{self._account_number} with a status code of "
                f"{response.status_code}: {response.text}"
            )

        order = response.json()["order"]

        return Order(
            id=order_id,
            name=order["symbol"],
            side=order["side"],
            type=order["type"],
            status=OrderStatus(order["status"]),
            executed_quantity=int(float(order["exec_quantity"])),
            avg_fill_price=float(order["avg_fill_price"]),
        )

    @property
    async def orders(self) -> Collection[Order]:

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url=self._form_url(f"/accounts/[[account]]/orders"), headers=self._headers
            )

        if response.status_code != httpx.codes.OK:
            raise IOError(
                f"failed to get orders with a status code of "
                f"{response.status_code}: {response.text}"
            )

        orders = response.json()["orders"]
        orders = (
            []
            if orders == "null"
            else [orders["order"]]
            if type(orders["order"]) is dict
            else orders["order"]
        )

        return [
            Order(
                id=order["id"],
                name=order["symbol"],
                side=order["side"],
                type=order["type"],
                status=OrderStatus(order["status"]),
                executed_quantity=int(float(order["exec_quantity"])),
                avg_fill_price=float(order["avg_fill_price"]),
            )
            for order in orders
        ]

    async def cancel_order(self, order_id):

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                url=self._form_url(f"/accounts/[[account]]/orders/{order_id}"),
                headers=self._headers,
            )

        if response.status_code != httpx.codes.OK:
            raise IOError(
                f"failed to delete order with a status code of "
                f"{response.status_code}: {response.text}"
            )

    async def account_pnl(self, since_date: date = None) -> List[ClosedPosition]:

        if since_date is None:
            params_ = None
        else:
            params_ = {"start": since_date.strftime("%Y-%m-%d")}

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url=self._form_url("/accounts/[[account]]/gainloss"),
                params=params_,
                headers=self._headers,
            )

        if response.status_code != codes.OK:
            raise IOError(
                f"failed to retrieve gainloss from Tradier account "
                f"with a status code of {response.status_code}: "
                f"{response.text}"
            )

        gainloss = response.json()["gainloss"]["closed_position"]

        closed_positions = [
            ClosedPosition(
                name=x["symbol"],
                size=x["quantity"],
                cost_basis=x["cost"],
                time_opened=x["open_date"],
                time_closed=x["close_date"],
                proceeds=x["proceeds"],
            )
            for x in gainloss
        ]

        return closed_positions

    async def account_history(self):

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url=self._form_url("/accounts/[[account]]/history/"),
                params=dict(
                    limit=10000,
                    type=",".join(
                        (
                            "ach",
                            "wire",
                            "dividend",
                            "fee",
                            "tax",
                            "journal",
                            "check",
                            "transfer",
                            "adjustment",
                            "interest",
                        )
                    ),
                ),
                headers=self._headers,
            )

        if response.status_code != codes.OK:
            raise IOError(
                f"failed to get account history from Tradier "
                f"with a status code of {response.status_code}: {response.text}"
            )

        actions = [
            AccountAction(type=action["type"], amount=action["amount"], date=action["date"])
            for action in response.json()["history"]["event"]
        ]

        return actions

    async def calendar(self) -> List[MarketDay]:

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url=self._form_url("/markets/calendar/"), headers=self._headers
            )

        if response.status_code != codes.OK:
            raise IOError(
                f"failed to get market calendar from Tradier "
                f"with a status code of {response.status_code}: {response.text}"
            )

        return None
