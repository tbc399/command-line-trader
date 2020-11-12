import httpx

from abc import ABC, abstractmethod
from enum import Enum
from httpx import codes
from typing import Collection, List
from pydantic import BaseModel
from datetime import datetime


class Position(BaseModel):
    name: str
    size: int
    cost_basis: float
    time_acquired: datetime

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if isinstance(other, Position):
            return self.name.lower() == other.name.lower()
        elif isinstance(other, str):
            return self.name.lower() == other.lower()


class OrderStatus(Enum):
    OPEN = 'open'
    FILLED = 'filled'
    REJECTED = 'rejected'
    EXPIRED = 'expired'
    CANCELED = 'canceled'
    PENDING = 'pending'
    PARTIALLY_FILLED = 'partially_filled'
    CALCULATED = 'calculated'
    ACCEPTED_FOR_BIDDING = 'accepted_for_bidding'
    ERROR = 'error'
    HELD = 'held'


class Order(BaseModel):
    id: str
    name: str
    side: str
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
            settled_cash: float):
        self._total_cash = total_cash
        self._total_equity = total_equity
        self._open_pl = open_pl
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
    def settled_cash(self):
        return self._settled_cash


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
 

class Tradier(Broker):

    def __init__(self, account_number: str, **kwargs):

        super().__init__(account_number)

        access_token = kwargs.get('access_token')
        if access_token is None:
            raise ValueError(
                'must have an access token to instantiate Tradier broker'
            )

        self._headers = dict(
            Accept='application/json',
            Authorization=f'Bearer {access_token}'
        )

    def _form_url(self, endpoint):

        tradier_api = 'api.tradier.com'
        tradier_api_version = 'v1'

        if tradier_api is None or tradier_api_version is None:
            raise EnvironmentError(
                'TRADIER_API and TRADIER_API_VERSION cannot be null'
            )

        base = f'https://{tradier_api}/{tradier_api_version}'
        components = (base, endpoint)
        almost_there = '/'.join(x.strip('/') for x in components)
        complete_url = almost_there.replace(
            '[[account]]',
            self._account_number
        )

        return complete_url

    async def _place_order(
                self,
                name: str,
                quantity: int,
                side: str,
                order_type: str = 'market',
                stop_price: float = None) -> str:
    
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url=self._form_url('/accounts/[[account]]/orders'),
                data={
                    'class': 'equity',
                    'symbol': name,
                    'side': side,
                    'quantity': quantity,
                    'type': order_type,
                    'duration': 'gtc',
                    'stop': stop_price
                },
                headers=self._headers
            )
    
        if response.status_code != codes.OK:
            raise IOError(
                f'failed to place market {side} order from Tradier '
                f'for {name} with a status code of'
                f' {response.status_code}: {response.text}'
            )
    
        return response.json()['order']['id']

    async def place_market_sell(self, name: str, quantity: int) -> str:
        return await self._place_order(name, quantity, 'sell')

    async def place_market_buy(self, name: str, quantity: int) -> str:
        return await self._place_order(name, quantity, 'buy')
    
    async def place_stop_loss(self, name: str, quantity: int, price: float):
        return await self._place_order(name, quantity, 'sell', 'stop', price)
    
    @property
    async def account_balance(self) -> AccountBalance:
    
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url=self._form_url('/accounts/[[account]]/balances/'),
                headers=self._headers
            )

        if response.status_code != httpx.codes.OK:
            raise IOError(
                f'failed to get account balance for account '
                f'{self._account_number} with a status code of '
                f'{response.status_code}: {response.text}'
            )
    
        balances = response.json()['balances']
    
        return AccountBalance(
            total_cash=balances['total_cash'],
            total_equity=balances['total_equity'],
            open_pl=balances['open_pl'],
            settled_cash=balances['cash']['cash_available']
        )
    
    @property
    async def positions(self) -> List[Position]:

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url=self._form_url('/accounts/[[account]]/positions/'),
                headers=self._headers
            )
        
        if response.status_code != httpx.codes.OK:
            raise IOError(
                f'failed to get account positions for account '
                f'{self._account_number} with a status code of '
                f'{response.status_code}: {response.text}'
            )

        if response.json()['positions'] in (None, 'null'):
            return list()

        positions = response.json()['positions']['position']

        if isinstance(positions, list):

            return [
                Position(
                    name=pos['symbol'],
                    size=pos['quantity'],
                    cost_basis=pos['cost_basis'],
                    time_acquired=datetime.strptime(
                        pos['date_acquired'],
                        '%Y-%m-%dT%H:%M:%S.%fZ'
                    )
                ) for pos in positions
            ]

        else:

            return [
                Position(
                    name=positions['symbol'],
                    size=positions['quantity'],
                    cost_basis=positions['cost_basis'],
                    time_acquired=datetime.strptime(
                        positions['date_acquired'],
                        '%Y-%m-%dT%H:%M:%S.%fZ'
                    )
                )
            ]

    async def get_quote(self, name: str) -> Quote:
    
        quotes = await self.get_quotes([name])
        return quotes[0]

    async def get_quotes(self, names: Collection[str]) -> List[Quote]:
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url=self._form_url('/markets/quotes/'),
                params=dict(symbols=','.join(names), greeks=False),
                headers=self._headers
            )
    
        if response.status_code != codes.OK:
            raise IOError(
                f'failed to get quotes from Tradier for symbol(s) {names} '
                f'with a status code of {response.status_code}: {response.text}'
            )
    
        quotes = response.json()['quotes']['quote']
        
        if isinstance(quotes, list):
            return [
                Quote(
                    name=quote['symbol'],
                    price=float(quote['last'])
                ) for quote in quotes
            ]
        else:
            return [Quote(
                name=quotes['symbol'],
                price=float(quotes['last'])
            )]

    async def order_status(self, order_id: str) -> Order:
    
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url=self._form_url(f'/accounts/[[account]]/orders/{order_id}'),
                headers=self._headers
            )
    
        if response.status_code != httpx.codes.OK:
            raise IOError(
                f'failed to get order status for order {order_id} '
                f'{self._account_number} with a status code of '
                f'{response.status_code}: {response.text}'
            )
    
        order = response.json()['order']
    
        return Order(
            id=order_id,
            name=order['symbol'],
            side=order['side'],
            status=OrderStatus(order['status']),
            executed_quantity=int(float(order['exec_quantity'])),
            avg_fill_price=float(order['avg_fill_price'])
        )