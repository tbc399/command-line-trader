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
            return self.name == other.name
        elif isinstance(other, str):
            return self.name == other


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
    async def place_market_sell(self, position: Position):
        pass

    @abstractmethod
    async def place_market_buy(self, position: Position):
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

    async def _place_order(self, position: Position, side: str):
    
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url=self._form_url('/accounts/[[account]]/orders'),
                data={
                    'class': 'equity',
                    'symbol': position.name,
                    'side': side,
                    'quantity': position.size,
                    'type': 'market',
                    'duration': 'day'
                },
                headers=self._headers
            )
    
        if response.status_code != codes.OK:
            raise IOError(
                f'failed to place market {side} order from Tradier '
                f'for {position.name} with a status code of'
                f' {response.status_code}: {response.text}'
            )
    
        return response.json()['order']['id']

    async def place_market_sell(self, position: Position):
        return await self._place_order(position, 'sell')

    async def place_market_buy(self, position: Position):
        return await self._place_order(position, 'buy')
    
    @property
    def account_balance(self) -> AccountBalance:
    
        with httpx.Client() as client:
            response = client.get(
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
    def positions(self) -> List[Position]:

        with httpx.Client() as client:
            response = client.get(
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

    def get_quote(self, name: str) -> Quote:
    
        with httpx.Client() as client:
            response = client.get(
                url=self._form_url('/markets/quotes/'),
                params=dict(symbols=name, greeks=False),
                headers = self._headers
            )
    
        if response.status_code != codes.OK:
            raise IOError(
                f'failed to get quote from Tradier for symbol(s) {name} '
                f'with a status code of {response.status_code}: {response.text}'
            )
    
        quote_object = response.json()['quotes']['quote']
    
        return Quote(
            name=quote_object['symbol'],
            price=float(quote_object['last'])
        )

    def get_quotes(self, names: Collection[str]) -> List[Quote]:
    
        with httpx.Client() as client:
            response = client.get(
                url=self._form_url('/markets/quotes/'),
                params=dict(symbols=','.join(names), greeks=False),
                headers=self._headers
            )
    
        if response.status_code != codes.OK:
            raise IOError(
                f'failed to get quotes from Tradier for symbols {names} '
                f'with a status code of {response.status_code}: {response.text}'
            )
    
        quote_objects = response.json()['quotes']['quote']
    
        return [
            Quote(
                name=quote_object['symbol'],
                price=float(quote_object['last'])
            ) for quote_object in quote_objects
        ]
